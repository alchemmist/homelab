package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"syscall"

	"github.com/prometheus/prometheus/storage"
	"github.com/prometheus/prometheus/tsdb"
)

const importShardSamples uint64 = 2_500_000
const importCompactFanIn = 16

// boundedBlockWriter bounds the mutable Head by samples, not by time: OTLP
// exports are series-major and a source block may span several days. All disk
// blocks and compaction use upstream TSDB APIs; intermediate blocks stay private.
type boundedBlockWriter struct {
	output, work          string
	blockSize             int64
	limit, pending, total uint64
	pendingInputBytes     uint64
	writer                *tsdb.BlockWriter
	compactWorkers        int
	blocks                []string
}

func newBoundedBlockWriter(output string, blockSize int64, limit uint64) (*boundedBlockWriter, error) {
	if limit == 0 {
		return nil, errors.New("import shard sample limit must be positive")
	}
	work := filepath.Join(output, ".import-work")
	if err := os.Mkdir(work, 0700); err != nil {
		return nil, err
	}
	return &boundedBlockWriter{output: output, work: work, blockSize: blockSize, limit: limit}, nil
}

func (w *boundedBlockWriter) Appender(ctx context.Context) (storage.Appender, error) {
	if w.writer == nil {
		var err error
		w.writer, err = tsdb.NewBlockWriter(logger, w.work, w.blockSize)
		if err != nil {
			return nil, err
		}
	}
	return w.writer.Appender(ctx), nil
}

func (w *boundedBlockWriter) CommitBatch(samples, inputBytes uint64) error {
	w.pending += samples
	w.total += samples
	w.pendingInputBytes += inputBytes
	if w.pending >= w.limit {
		return w.flush()
	}
	return nil
}

// Keep the same 20% filesystem reserve as the coordinator. Compaction can
// temporarily require another full copy; conservatively reserve twice its
// source bytes before starting each bounded fan-in group.
func requireImportSpace(path string, projected uint64) error {
	var stat syscall.Statfs_t
	if err := syscall.Statfs(path, &stat); err != nil {
		return err
	}
	available := uint64(stat.Bavail) * uint64(stat.Bsize)
	reserve := uint64(stat.Blocks) * uint64(stat.Bsize) / 5
	if projected > available || available-projected < reserve {
		return errors.New("import would breach the 20% filesystem reserve")
	}
	return nil
}

func (w *boundedBlockWriter) flush() error {
	if w.pending == 0 {
		return nil
	}
	if err := requireImportSpace(w.work, 2*w.pendingInputBytes+64*1024*1024); err != nil {
		return err
	}
	id, err := w.writer.Flush(context.Background())
	if err != nil {
		return err
	}
	finished := w.writer
	w.writer = nil
	if err = finished.Close(); err != nil {
		return err
	}
	w.blocks = append(w.blocks, filepath.Join(w.work, id.String()))
	if err = writeJSON(filepath.Join(w.work, fmt.Sprintf("shard-%06d.json", len(w.blocks))), map[string]any{
		"block": id.String(), "samples": w.pending, "totalSamples": w.total,
		"canonicalVerified": false, "productionModified": false,
	}); err != nil {
		return err
	}
	fmt.Fprintf(os.Stderr, "import checkpoint: shards=%d samples=%d\n", len(w.blocks), w.total)
	w.pending = 0
	w.pendingInputBytes = 0
	return nil
}

func (w *boundedBlockWriter) Finish() (string, error) {
	if err := w.flush(); err != nil {
		return "", err
	}
	if len(w.blocks) == 0 {
		return "", errors.New("no imported samples")
	}
	blocks := append([]string(nil), w.blocks...)
	for level := 0; len(blocks) > 1; level++ {
		next, err := w.compactLevel(blocks, level)
		if err != nil {
			return "", err
		}
		blocks = next
	}
	target := filepath.Join(w.output, filepath.Base(blocks[0]))
	if err := os.Rename(blocks[0], target); err != nil {
		return "", err
	}
	return target, nil
}

func (w *boundedBlockWriter) Close() error {
	if w.writer != nil {
		return w.writer.Close()
	}
	return nil
}
