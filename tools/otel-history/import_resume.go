package main

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"syscall"

	"github.com/prometheus/prometheus/model/labels"
	common "go.opentelemetry.io/proto/otlp/common/v1"
	metrics "go.opentelemetry.io/proto/otlp/metrics/v1"
)

type shardPrefix struct {
	Block           string              `json:"block"`
	Samples         uint64              `json:"samples"`
	TotalSamples    uint64              `json:"totalSamples"`
	Directory       string              `json:"directory"`
	CanonicalSHA256 string              `json:"canonicalSHA256"`
	StaleMarkers    uint64              `json:"staleMarkers"`
	Inventory       map[string][4]int64 `json:"inventory"`
}
type importPrefixProof struct {
	Version        int           `json:"version"`
	Verified       bool          `json:"verified"`
	Source         string        `json:"source"`
	ManifestSHA256 string        `json:"manifestSHA256"`
	Shards         []shardPrefix `json:"shards"`
	Samples        uint64        `json:"samples"`
	Files          int           `json:"files"`
	StaleMarkers   uint64        `json:"staleMarkers"`
}

func shardInventory(root string) (map[string][4]int64, error) {
	result := map[string][4]int64{}
	err := filepath.WalkDir(root, func(path string, e os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if e.Type()&os.ModeSymlink != 0 {
			return errors.New("symlink in native resume shard")
		}
		if !e.IsDir() {
			info, err := e.Info()
			if err != nil {
				return err
			}
			if !info.Mode().IsRegular() {
				return errors.New("nonregular native shard file")
			}
			rel, _ := filepath.Rel(root, path)
			result[rel] = [4]int64{info.Size(), info.ModTime().UnixNano(), int64(info.Sys().(*syscall.Stat_t).Dev), int64(info.Sys().(*syscall.Stat_t).Ino)}
		}
		return nil
	})
	return result, err
}
func verifySourcePrefix(source string, files []string, start, end int, want uint64) (uint64, string, uint64, error) {
	if start < 0 || end > len(files) || start > end {
		return 0, "", 0, errors.New("prefix file range invalid")
	}
	h := sha256.New()
	var count, stale uint64
	var cached []*common.KeyValue
	var metricName string
	var lset labels.Labels
	var prefix []byte
	var record [16]byte
	for _, name := range files[start:end] {
		req, _, err := decodeImportBatch(filepath.Join(source, name))
		if err != nil {
			return 0, "", 0, err
		}
		n := 0
		for _, r := range req.ResourceMetrics {
			if r.Resource != nil && len(r.Resource.Attributes) != 0 {
				return 0, "", 0, errors.New("unexpected prefix resource attributes")
			}
			for _, s := range r.ScopeMetrics {
				for _, m := range s.Metrics {
					if m.GetGauge() == nil || m.Name == "" {
						return 0, "", 0, errors.New("invalid prefix metric")
					}
					for _, point := range m.GetGauge().DataPoints {
						if point == nil || point.TimeUnixNano%1000000 != 0 || point.TimeUnixNano/1000000 > math.MaxInt64 || point.StartTimeUnixNano != 0 || point.Flags & ^uint32(metrics.DataPointFlags_DATA_POINT_FLAGS_NO_RECORDED_VALUE_MASK) != 0 {
							return 0, "", 0, errors.New("invalid prefix point")
						}
						value, ok := point.Value.(*metrics.NumberDataPoint_AsDouble)
						if !ok {
							return 0, "", 0, errors.New("non-double prefix point")
						}
						if metricName != m.Name || !sameStringAttributes(cached, point.Attributes) {
							attrs := map[string]string{"__name__": m.Name}
							for _, a := range point.Attributes {
								if a == nil || a.Value == nil {
									return 0, "", 0, errors.New("nil prefix label")
								}
								if _, exists := attrs[a.Key]; exists {
									return 0, "", 0, errors.New("duplicate prefix label")
								}
								v, ok := a.Value.Value.(*common.AnyValue_StringValue)
								if !ok {
									return 0, "", 0, errors.New("nonstring prefix label")
								}
								attrs[a.Key] = v.StringValue
							}
							next := labels.FromMap(attrs)
							if metricName != "" && labels.Compare(lset, next) > 0 {
								return 0, "", 0, errors.New("prefix not in canonical label order; cannot adopt")
							}
							lset = next
							metricName = m.Name
							cached = point.Attributes
							text := lset.String()
							prefix = make([]byte, 8+len(text))
							binary.LittleEndian.PutUint64(prefix[:8], uint64(len(text)))
							copy(prefix[8:], text)
						}
						sample := value.AsDouble
						if point.Flags&uint32(metrics.DataPointFlags_DATA_POINT_FLAGS_NO_RECORDED_VALUE_MASK) != 0 {
							sample = math.Float64frombits(staleNaN)
							stale++
						}
						addSampleHash(h, prefix, record[:], int64(point.TimeUnixNano/1000000), sample)
						count++
						n++
					}
				}
			}
		}
		if n == 0 || n > batchSize {
			return 0, "", 0, errors.New("prefix batch count invalid")
		}
	}
	if count != want {
		return 0, "", 0, errors.New("source prefix sample count differs")
	}
	return count, hex.EncodeToString(h.Sum(nil)), stale, nil
}

// Read-only proof, never imports/appends. Closed immutable shards are checked
// independently against their exact contiguous OTLP prefix, not trusted by count.
func proveImportPrefix(source, previous string, workers int) (importPrefixProof, error) {
	proof := importPrefixProof{Version: 1, Source: source}
	if workers < 1 || workers > 8 {
		return proof, errors.New("prefix proof workers must be1..8")
	}
	manifest, err := loadManifestWithWorkers(source, workers)
	if err != nil {
		return proof, err
	}
	files, err := orderedFiles(manifest.Files)
	if err != nil {
		return proof, err
	}
	proof.ManifestSHA256, err = fileHash(filepath.Join(source, "manifest.json"))
	if err != nil {
		return proof, err
	}
	checkpoints, err := filepath.Glob(filepath.Join(previous, ".import-work", "shard-*.json"))
	if err != nil {
		return proof, err
	}
	sort.Strings(checkpoints)
	// A live writer may still be finishing its newest receipt; use only the sealed prefix before it.
	if len(checkpoints) > 1 {
		checkpoints = checkpoints[:len(checkpoints)-1]
	}
	if len(checkpoints) == 0 {
		return proof, errors.New("no closed native shards to adopt")
	}
	var total uint64
	for i, path := range checkpoints {
		if filepath.Base(path) != fmt.Sprintf("shard-%06d.json", i+1) {
			return proof, errors.New("noncontiguous shard receipts")
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return proof, err
		}
		var shard shardPrefix
		if err = json.Unmarshal(data, &shard); err != nil {
			return proof, err
		}
		if shard.Samples == 0 || shard.Samples > importShardSamples+batchSize || len(shard.Block) != 26 || filepath.Base(shard.Block) != shard.Block || total%batchSize != 0 {
			return proof, errors.New("unsafe shard checkpoint")
		}
		total += shard.Samples
		if total != shard.TotalSamples || total > manifest.Samples {
			return proof, errors.New("shard prefix totals differ")
		}
		shard.Directory = filepath.Join(previous, ".import-work", shard.Block)
		proof.Shards = append(proof.Shards, shard)
	}
	jobs := make(chan int)
	var wg sync.WaitGroup
	var mu sync.Mutex
	var first error
	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range jobs {
				mu.Lock()
				failed := first != nil
				mu.Unlock()
				if failed {
					continue
				}
				shard := &proof.Shards[i]
				start := int((shard.TotalSamples - shard.Samples) / batchSize)
				end := int((shard.TotalSamples + batchSize - 1) / batchSize)
				_, expected, stale, err := verifySourcePrefix(source, files, start, end, shard.Samples)
				if err == nil {
					var count uint64
					var actual string
					count, actual, err = walk(shard.Directory, nil)
					if err == nil && (count != shard.Samples || expected != actual) {
						err = errors.New("native shard canonical differs from exact OTLP prefix")
					}
				}
				if err == nil {
					shard.CanonicalSHA256 = expected
					shard.StaleMarkers = stale
					shard.Inventory, err = shardInventory(shard.Directory)
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
	for i := range proof.Shards {
		jobs <- i
	}
	close(jobs)
	wg.Wait()
	if first != nil {
		return proof, first
	}
	for _, s := range proof.Shards {
		proof.StaleMarkers += s.StaleMarkers
	}
	proof.Samples = total
	proof.Files = int((total + batchSize - 1) / batchSize)
	proof.Verified = true
	return proof, nil
}
func loadImportPrefix(path, source string) (importPrefixProof, error) {
	var proof importPrefixProof
	info, err := os.Lstat(path)
	if err != nil {
		return proof, err
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !ok || st.Uid != uint32(os.Geteuid()) || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 {
		return proof, errors.New("untrusted native prefix proof")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return proof, err
	}
	if err = json.Unmarshal(data, &proof); err != nil {
		return proof, err
	}
	if !proof.Verified || proof.Version != 1 || proof.Source != source || len(proof.Shards) == 0 {
		return proof, errors.New("invalid native prefix proof")
	}
	hash, err := fileHash(filepath.Join(source, "manifest.json"))
	if err != nil || hash != proof.ManifestSHA256 {
		return proof, errors.New("resume manifest differs")
	}
	var total, stale uint64
	for _, s := range proof.Shards {
		inventory, err := shardInventory(s.Directory)
		if err != nil {
			return proof, err
		}
		if len(inventory) != len(s.Inventory) {
			return proof, errors.New("verified shard inventory differs")
		}
		for k, v := range inventory {
			if s.Inventory[k] != v {
				return proof, errors.New("verified shard file changed")
			}
		}
		if s.CanonicalSHA256 == "" || s.Samples == 0 {
			return proof, errors.New("unverified prefix shard")
		}
		total += s.Samples
		stale += s.StaleMarkers
		if total != s.TotalSamples {
			return proof, errors.New("prefix checkpoint totals differ")
		}
	}
	if total != proof.Samples || stale != proof.StaleMarkers || proof.Files != int((total+batchSize-1)/batchSize) {
		return proof, errors.New("prefix proof totals differ")
	}
	return proof, nil
}
