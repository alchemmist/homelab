package main

import (
	"bytes"
	"compress/gzip"
	"errors"
	"fmt"
	collector "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	"google.golang.org/protobuf/proto"
	"io"
	"os"
	"path/filepath"
	"sync"
)

type exportJob struct {
	index   int
	request *collector.ExportMetricsServiceRequest
}
type parallelExport struct {
	output  string
	budget  int64
	resume  bool
	jobs    chan exportJob
	wg      sync.WaitGroup
	once    sync.Once
	mu      sync.Mutex
	err     error
	written int64
	next    int
	files   map[string]string
}

func newParallelExport(output string, budget int64, resume bool, workers int) (*parallelExport, error) {
	if workers < 1 || workers > 50 {
		return nil, errors.New("export workers must be bounded to 1..50")
	}
	w := &parallelExport{output: output, budget: budget, resume: resume, jobs: make(chan exportJob, workers), files: map[string]string{}}
	for i := 0; i < workers; i++ {
		w.wg.Add(1)
		go func() {
			defer w.wg.Done()
			compressor := gzip.NewWriter(io.Discard)
			for job := range w.jobs {
				w.mu.Lock()
				failed := w.err != nil
				w.mu.Unlock()
				if failed {
					continue
				}
				size, digest, err := w.write(job, compressor)
				w.mu.Lock()
				if err == nil {
					w.written += size
					if w.written > w.budget {
						err = errors.New("export byte budget exceeded; partial output is not publishable")
					}
				}
				if err != nil {
					if w.err == nil {
						w.err = err
					}
				} else {
					w.files[fmt.Sprintf("%06d.otlp.pb.gz", job.index)] = digest
				}
				w.mu.Unlock()
			}
		}()
	}
	return w, nil
}

func (w *parallelExport) submit(request *collector.ExportMetricsServiceRequest) error {
	w.mu.Lock()
	err := w.err
	w.mu.Unlock()
	if err != nil {
		return err
	}
	w.jobs <- exportJob{index: w.next, request: request}
	w.next++
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.err
}
func (w *parallelExport) close() error {
	w.once.Do(func() { close(w.jobs); w.wg.Wait() })
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.err
}
func (w *parallelExport) write(job exportJob, compressor *gzip.Writer) (int64, string, error) {
	data, err := proto.Marshal(job.request)
	if err != nil {
		return 0, "", err
	}
	if len(data) > 32*1024*1024 {
		return 0, "", errors.New("OTLP batch exceeds the importer limit")
	}
	path := filepath.Join(w.output, fmt.Sprintf("%06d.otlp.pb.gz", job.index))
	info, statErr := os.Lstat(path)
	if statErr == nil && w.resume {
		if !info.Mode().IsRegular() {
			return 0, "", errors.New("existing export batch is not a regular file")
		}
		f, e := os.Open(path)
		if e != nil {
			return 0, "", e
		}
		z, e := gzip.NewReader(f)
		if e != nil {
			f.Close()
			return 0, "", e
		}
		previous, readErr := io.ReadAll(io.LimitReader(z, 32*1024*1024+1))
		if e = errors.Join(readErr, z.Close(), f.Close()); e != nil {
			return 0, "", e
		}
		if !bytes.Equal(previous, data) {
			return 0, "", errors.New("existing batch differs from source; preserve and inspect partial output")
		}
	} else {
		if statErr != nil && !errors.Is(statErr, os.ErrNotExist) {
			return 0, "", statErr
		}
		f, e := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if e != nil {
			return 0, "", e
		}
		compressor.Reset(f)
		_, writeErr := compressor.Write(data)
		if e = errors.Join(writeErr, compressor.Close(), f.Close()); e != nil {
			return 0, "", e
		}
	}
	info, err = os.Stat(path)
	if err != nil {
		return 0, "", err
	}
	digest, err := fileHash(path)
	return info.Size(), digest, err
}
