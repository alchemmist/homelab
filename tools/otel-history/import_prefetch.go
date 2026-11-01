package main

import (
	"compress/gzip"
	"context"
	"errors"
	collector "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	"google.golang.org/protobuf/proto"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

type decodedBatch struct {
	index, bytes int
	request      *collector.ExportMetricsServiceRequest
	err          error
}
type importPrefetch struct {
	lanes  []chan decodedBatch
	cancel context.CancelFunc
	wg     sync.WaitGroup
	once   sync.Once
}

// Each lane emits strictly increasing indices. One ready + one decoding batch
// per lane bounds memory regardless of total files. Only the ordered consumer
// appends to upstream TSDB; this is not multiple native history importers.
func newImportPrefetch(source string, files []string, workers int) (*importPrefetch, error) {
	if workers < 1 || workers > 16 {
		return nil, errors.New("import prefetch workers must be 1..16")
	}
	ctx, cancel := context.WithCancel(context.Background())
	p := &importPrefetch{cancel: cancel}
	for lane := 0; lane < workers; lane++ {
		out := make(chan decodedBatch, 1)
		p.lanes = append(p.lanes, out)
		p.wg.Add(1)
		go func(lane int, out chan decodedBatch) {
			defer p.wg.Done()
			defer close(out)
			for index := lane; index < len(files); index += workers {
				select {
				case <-ctx.Done():
					return
				default:
				}
				request, size, err := decodeImportBatch(filepath.Join(source, files[index]))
				select {
				case out <- decodedBatch{index: index, bytes: size, request: request, err: err}:
				case <-ctx.Done():
					return
				}
				if err != nil {
					return
				}
			}
		}(lane, out)
	}
	return p, nil
}
func (p *importPrefetch) next(index int) (decodedBatch, error) {
	batch, ok := <-p.lanes[index%len(p.lanes)]
	if !ok {
		return batch, errors.New("prefetch ended before ordered batch")
	}
	if batch.index != index {
		return batch, errors.New("prefetch batch ordering differs")
	}
	return batch, batch.err
}
func (p *importPrefetch) close() { p.once.Do(func() { p.cancel(); p.wg.Wait() }) }
func decodeImportBatch(path string) (*collector.ExportMetricsServiceRequest, int, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, 0, err
	}
	if !info.Mode().IsRegular() {
		return nil, 0, errors.New("OTLP batch is not a regular file")
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, 0, err
	}
	zipped, err := gzip.NewReader(file)
	if err != nil {
		file.Close()
		return nil, 0, err
	}
	data, readErr := io.ReadAll(io.LimitReader(zipped, 32*1024*1024+1))
	if err = errors.Join(readErr, zipped.Close(), file.Close()); err != nil {
		return nil, 0, err
	}
	if len(data) > 32*1024*1024 {
		return nil, 0, errors.New("oversized OTLP batch")
	}
	request := &collector.ExportMetricsServiceRequest{}
	if err = proto.Unmarshal(data, request); err != nil {
		return nil, 0, err
	}
	return request, len(data), nil
}

func verifyManifestFiles(source string, files map[string]string, workers int) error {
	if workers < 1 || workers > 16 {
		return errors.New("checksum workers must be 1..16")
	}
	// Validate the entire path namespace before any parallel file access.
	for name := range files {
		if filepath.Base(name) != name || !strings.HasSuffix(name, ".otlp.pb.gz") {
			return errors.New("invalid export path")
		}
	}
	jobs := make(chan string)
	var wg sync.WaitGroup
	var mu sync.Mutex
	var first error
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for name := range jobs {
				mu.Lock()
				failed := first != nil
				mu.Unlock()
				if failed {
					continue
				}
				path := filepath.Join(source, name)
				info, err := os.Lstat(path)
				if err == nil && !info.Mode().IsRegular() {
					err = errors.New("export checksum target is not a regular file")
				}
				if err == nil {
					var digest string
					digest, err = fileHash(path)
					if err == nil && digest != files[name] {
						err = errors.New("export file checksum mismatch")
					}
				}
				if err != nil {
					mu.Lock()
					if first == nil {
						first = err
					}
					mu.Unlock()
				}
			}
		}()
	}
	for name := range files {
		jobs <- name
	}
	close(jobs)
	wg.Wait()
	return first
}
