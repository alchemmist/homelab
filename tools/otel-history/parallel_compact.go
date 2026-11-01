package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/prometheus/prometheus/tsdb"
	"github.com/prometheus/prometheus/tsdb/chunkenc"
	"os"
	"path/filepath"
	"sync"
)

type compactGroup struct {
	paths                  []string
	bytes, estimatedMemory uint64
}

func inspectCompactGroup(paths []string) (compactGroup, error) {
	g := compactGroup{paths: paths, estimatedMemory: 256 << 20}
	for _, block := range paths {
		data, err := os.ReadFile(filepath.Join(block, "meta.json"))
		if err != nil {
			return g, err
		}
		var meta struct {
			Stats struct {
				NumSeries uint64 `json:"numSeries"`
			} `json:"stats"`
		}
		if err = json.Unmarshal(data, &meta); err != nil {
			return g, err
		}
		if meta.Stats.NumSeries > (1 << 40) {
			return g, errors.New("implausible compaction series count")
		}
		g.estimatedMemory += meta.Stats.NumSeries * 4096
		err = filepath.WalkDir(block, func(path string, entry os.DirEntry, e error) error {
			if e != nil {
				return e
			}
			if entry.Type()&os.ModeSymlink != 0 {
				return errors.New("symlink in import intermediate")
			}
			if !entry.IsDir() {
				info, e := entry.Info()
				if e != nil {
					return e
				}
				g.bytes += uint64(info.Size())
			}
			return nil
		})
		if err != nil {
			return g, err
		}
	}
	return g, nil
}

// Independent groups use distinct upstream compactor instances. Waves reserve
// combined projected disk space before starting, and limit concurrent metadata
// projection to4GiB. A failed concurrent reservation falls back to serial,
// never a lowered disk reserve. Completed inputs/failed outputs are retained.
func (w *boundedBlockWriter) compactLevel(blocks []string, level int) ([]string, error) {
	groups := []compactGroup{}
	for start := 0; start < len(blocks); start += importCompactFanIn {
		end := min(start+importCompactFanIn, len(blocks))
		g, err := inspectCompactGroup(blocks[start:end])
		if err != nil {
			return nil, err
		}
		groups = append(groups, g)
	}
	next := make([]string, len(groups))
	workers := max(1, min(w.compactWorkers, 4))
	for start := 0; start < len(groups); {
		end := min(start+workers, len(groups))
		for {
			var bytes, memory uint64
			for _, g := range groups[start:end] {
				if len(g.paths) > 1 {
					bytes += g.bytes
					memory += g.estimatedMemory
				}
			}
			if end-start > 1 && memory > 4*1024*1024*1024 {
				end--
				continue
			}
			if err := requireImportSpace(w.work, 2*bytes); err != nil {
				if end-start > 1 {
					end--
					continue
				}
				return nil, err
			}
			break
		}
		var wg sync.WaitGroup
		var mu sync.Mutex
		var first error
		for i := start; i < end; i++ {
			wg.Add(1)
			go func(i int) {
				defer wg.Done()
				g := groups[i]
				if len(g.paths) == 1 {
					next[i] = g.paths[0]
					return
				}
				compactor, err := tsdb.NewLeveledCompactor(context.Background(), nil, logger, []int64{w.blockSize}, chunkenc.NewPool(), nil)
				if err == nil {
					result, e := compactor.Compact(w.work, g.paths, nil)
					err = e
					if err == nil {
						if len(result) != 1 {
							err = errors.New("import compaction did not produce exactly one block")
						} else {
							next[i] = filepath.Join(w.work, result[0].String())
						}
					}
				}
				if err != nil {
					mu.Lock()
					if first == nil {
						first = err
					}
					mu.Unlock()
				} else {
					fmt.Fprintf(os.Stderr, "import compaction: level=%d inputs=%d concurrentLimit=%d\n", level, len(g.paths), workers)
				}
			}(i)
		}
		wg.Wait()
		if first != nil {
			return nil, first
		}
		start = end
	}
	return next, nil
}
