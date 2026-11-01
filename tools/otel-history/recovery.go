package main

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"hash/crc32"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"strings"

	"github.com/prometheus/prometheus/model/labels"
	"github.com/prometheus/prometheus/storage"
	"github.com/prometheus/prometheus/tsdb"
	"github.com/prometheus/prometheus/tsdb/chunkenc"
	"github.com/prometheus/prometheus/tsdb/chunks"
	"github.com/prometheus/prometheus/tsdb/index"
	"github.com/prometheus/prometheus/tsdb/tombstones"
)

// LossApproval identifies exactly one corrupt chunk. A repair never ignores a
// general decoder/checksum error: every other chunk must remain queryable and
// must match the canonical stream of the tombstoned, isolated source copy.
type LossApproval struct {
	SchemaVersion       int               `json:"schemaVersion"`
	SourceULID          string            `json:"sourceULID"`
	ChunkRef            uint64            `json:"chunkRef"`
	LabelsSHA256        string            `json:"labelsSHA256"`
	MinTime             int64             `json:"minTime"`
	MaxTime             int64             `json:"maxTime"`
	RemovedSamples      uint64            `json:"removedSamples"`
	MaximumLossWindowMS int64             `json:"maximumLossWindowMS"`
	StoredCRC           uint32            `json:"storedCRC"`
	ActualCRC           uint32            `json:"actualCRC"`
	Files               map[string]string `json:"files"`
}

func recoverApprovedChunk(source, output string, a LossApproval) error {
	if a.SchemaVersion != 1 || a.MaximumLossWindowMS <= 0 || a.MaximumLossWindowMS > 86400000 || a.MinTime < 0 || a.MaxTime < a.MinTime || a.MaxTime-a.MinTime >= a.MaximumLossWindowMS || a.RemovedSamples == 0 || len(a.Files) == 0 {
		return errors.New("invalid or excessive loss approval")
	}
	sourceAbsolute, err := filepath.Abs(source)
	if err != nil {
		return err
	}
	outputAbsolute, err := filepath.Abs(output)
	if err != nil {
		return err
	}
	if outputAbsolute == sourceAbsolute || strings.HasPrefix(outputAbsolute, sourceAbsolute+string(os.PathSeparator)) {
		return errors.New("recovery output must not be inside the preserved source")
	}
	sourceMeta, err := metadata(source)
	if err != nil {
		return err
	}
	var sourceID string
	if err = json.Unmarshal(sourceMeta["ulid"], &sourceID); err != nil {
		return err
	}
	if sourceID != a.SourceULID {
		return errors.New("loss approval is for another source block")
	}
	// Verify the complete captured input inventory before making a private copy.
	seen := map[string]bool{}
	var bytes uint64
	err = filepath.WalkDir(source, func(path string, e os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if e.Type()&os.ModeSymlink != 0 {
			return errors.New("symlink in recovery source")
		}
		if e.IsDir() {
			return nil
		}
		rel, err := filepath.Rel(source, path)
		if err != nil {
			return err
		}
		expected, ok := a.Files[filepath.ToSlash(rel)]
		if !ok {
			return errors.New("unapproved recovery input file")
		}
		digest, err := fileHash(path)
		if err != nil {
			return err
		}
		if digest != expected {
			return errors.New("recovery input SHA256 differs from preservation receipt")
		}
		seen[filepath.ToSlash(rel)] = true
		stat, err := e.Info()
		if err != nil {
			return err
		}
		bytes += uint64(stat.Size())
		return nil
	})
	if err != nil {
		return err
	}
	if len(seen) != len(a.Files) {
		return errors.New("missing recovery input file")
	}
	b, err := tsdb.OpenBlock(logger, source, nil, nil)
	if err != nil {
		return err
	}
	tr, err := b.Tombstones()
	if err != nil {
		b.Close()
		return err
	}
	if tr.Total() != 0 {
		tr.Close()
		b.Close()
		return errors.New("recovery with preexisting tombstones requires separate loss accounting")
	}
	tr.Close()
	sourceStats := b.Meta().Stats
	b.Close()
	if sourceStats.NumSamples <= a.RemovedSamples {
		return errors.New("approved loss would remove entire block")
	}
	ir, err := index.NewFileReader(filepath.Join(source, "index"), index.DecodePostingsRaw)
	if err != nil {
		return err
	}
	key, value := index.AllPostingsKey()
	postings, err := ir.Postings(context.Background(), key, value)
	if err != nil {
		ir.Close()
		return err
	}
	var builder labels.ScratchBuilder
	var metas []chunks.Meta
	var selected storage.SeriesRef
	var matched int
	var metricName string
	for postings.Next() {
		metas = metas[:0]
		if err = ir.Series(postings.At(), &builder, &metas); err != nil {
			ir.Close()
			return err
		}
		for _, m := range metas {
			if uint64(m.Ref) != a.ChunkRef {
				continue
			}
			ls := builder.Labels()
			h := sha256.Sum256([]byte(ls.String()))
			if hex.EncodeToString(h[:]) != a.LabelsSHA256 || m.MinTime != a.MinTime || m.MaxTime != a.MaxTime {
				ir.Close()
				return errors.New("approved chunk identity/time bounds differ")
			}
			matched++
			selected = postings.At()
			metricName = ls.Get("__name__")
		}
	}
	err = postings.Err()
	ir.Close()
	if err != nil {
		return err
	}
	if matched != 1 {
		return errors.New("approved chunk is not uniquely indexed")
	}
	segment, offset := chunks.BlockChunkRef(a.ChunkRef).Unpack()
	f, err := os.Open(filepath.Join(source, "chunks", fmt.Sprintf("%06d", segment+1)))
	if err != nil {
		return err
	}
	if _, err = f.Seek(int64(offset), io.SeekStart); err != nil {
		f.Close()
		return err
	}
	header := make([]byte, 10)
	if _, err = io.ReadFull(f, header); err != nil {
		f.Close()
		return err
	}
	size, n := binary.Uvarint(header)
	if n <= 0 || size < 2 || size > 1024*1024 {
		f.Close()
		return errors.New("invalid approved chunk frame")
	}
	if _, err = f.Seek(int64(offset+n), io.SeekStart); err != nil {
		f.Close()
		return err
	}
	body := make([]byte, int(size)+5)
	_, err = io.ReadFull(f, body)
	f.Close()
	if err != nil {
		return err
	}
	actual := crc32.Checksum(body[:int(size)+1], crc32.MakeTable(crc32.Castagnoli))
	stored := binary.BigEndian.Uint32(body[int(size)+1:])
	if body[0] != byte(chunkenc.EncXOR) || uint64(binary.BigEndian.Uint16(body[1:3])) != a.RemovedSamples || stored != a.StoredCRC || actual != a.ActualCRC || stored == actual {
		return errors.New("corrupt chunk does not match the explicit loss approval")
	}
	if err = newOutput(output); err != nil {
		return err
	}
	if err = requireImportSpace(output, 2*bytes); err != nil {
		return err
	}
	clone := filepath.Join(output, "source-with-approved-tombstone")
	if err = os.Mkdir(clone, 0700); err != nil {
		return err
	}
	for rel, expected := range a.Files {
		target := filepath.Join(clone, filepath.FromSlash(rel))
		if err = os.MkdirAll(filepath.Dir(target), 0700); err != nil {
			return err
		}
		input, err := os.Open(filepath.Join(source, filepath.FromSlash(rel)))
		if err != nil {
			return err
		}
		out, err := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if err != nil {
			input.Close()
			return err
		}
		_, copyErr := io.Copy(out, input)
		err = errors.Join(copyErr, out.Close(), input.Close())
		if err != nil {
			return err
		}
		digest, err := fileHash(target)
		if err != nil {
			return err
		}
		if digest != expected {
			return errors.New("recovery clone changed during copy")
		}
	}
	ts := tombstones.NewMemTombstones()
	ts.AddInterval(selected, tombstones.Interval{Mint: a.MinTime, Maxt: a.MaxTime})
	if _, err = tombstones.WriteFile(logger, clone, ts); err != nil {
		return err
	}
	if err = writeJSON(filepath.Join(output, "loss-approval.json"), a); err != nil {
		return err
	}
	fmt.Fprintln(os.Stderr, "recovery: verifying all source samples outside the explicitly approved tombstone")
	count, digest, err := walk(clone, nil)
	if err != nil {
		return err
	}
	if count != sourceStats.NumSamples-a.RemovedSamples {
		return errors.New("source loss is larger than explicitly approved")
	}
	if err = writeJSON(filepath.Join(output, "source-verification.json"), map[string]any{"samples": count, "canonicalSHA256": digest, "removedSamples": a.RemovedSamples, "productionModified": false}); err != nil {
		return err
	}
	b, err = tsdb.OpenBlock(logger, clone, nil, nil)
	if err != nil {
		return err
	}
	closed := false
	defer func() {
		if !closed {
			_ = b.Close()
		}
	}()
	meta := b.Meta()
	compactor, err := tsdb.NewLeveledCompactor(context.Background(), nil, logger, []int64{2 * (meta.MaxTime - meta.MinTime + 1)}, chunkenc.NewPool(), nil)
	if err != nil {
		return err
	}
	ids, err := compactor.Write(output, b, meta.MinTime, meta.MaxTime, nil)
	if err != nil {
		return err
	}
	// Release the source mmap before opening the target for its independent pass.
	err = b.Close()
	closed = true
	if err != nil {
		return err
	}
	if len(ids) != 1 {
		return errors.New("recovery did not produce exactly one native block")
	}
	target := filepath.Join(output, ids[0].String())
	data, err := os.ReadFile(filepath.Join(target, "meta.json"))
	if err != nil {
		return err
	}
	var recovered map[string]json.RawMessage
	if err = json.Unmarshal(data, &recovered); err != nil {
		return err
	}
	// Preserve semantic identity and ancestry, but regenerate physical file metadata.
	for _, k := range []string{"minTime", "maxTime", "compaction"} {
		if v, ok := sourceMeta[k]; ok {
			recovered[k] = v
		}
	}
	if v, ok := sourceMeta["thanos"]; ok {
		var tm map[string]any
		if err = json.Unmarshal(v, &tm); err != nil {
			return err
		}
		delete(tm, "index_stats")
		delete(tm, "upload_time")
		var inventory []map[string]any
		var segments []string
		files, err := os.ReadDir(filepath.Join(target, "chunks"))
		if err != nil {
			return err
		}
		for _, file := range files {
			if file.IsDir() || file.Type()&os.ModeSymlink != 0 {
				return errors.New("unexpected recovered segment")
			}
			info, err := file.Info()
			if err != nil {
				return err
			}
			segments = append(segments, file.Name())
			inventory = append(inventory, map[string]any{"rel_path": "chunks/" + file.Name(), "size_bytes": info.Size()})
		}
		stat, err := os.Stat(filepath.Join(target, "index"))
		if err != nil {
			return err
		}
		inventory = append(inventory, map[string]any{"rel_path": "index", "size_bytes": stat.Size()}, map[string]any{"rel_path": "meta.json"})
		tm["files"] = inventory
		tm["segment_files"] = segments
		recovered["thanos"], err = json.Marshal(tm)
		if err != nil {
			return err
		}
	}
	data, err = json.MarshalIndent(recovered, "", "  ")
	if err != nil {
		return err
	}
	if err = os.WriteFile(filepath.Join(target, "meta.json"), data, 0600); err != nil {
		return err
	}
	fmt.Fprintln(os.Stderr, "recovery: independently verifying the compacted native block")
	actualCount, actualDigest, err := walk(target, nil)
	if err != nil {
		return err
	}
	if actualCount != count || actualDigest != digest {
		return errors.New("canonical samples outside approved loss changed")
	}
	targetMeta, err := metadata(target)
	if err != nil {
		return err
	}
	for _, k := range []string{"minTime", "maxTime", "compaction"} {
		var a, b any
		json.Unmarshal(sourceMeta[k], &a)
		json.Unmarshal(targetMeta[k], &b)
		if !reflect.DeepEqual(a, b) {
			return errors.New("recovery changed time bounds or ancestry")
		}
	}
	var originalThanos, targetThanos map[string]any
	if value, ok := sourceMeta["thanos"]; ok {
		if err = json.Unmarshal(value, &originalThanos); err != nil {
			return err
		}
		if err = json.Unmarshal(targetMeta["thanos"], &targetThanos); err != nil {
			return err
		}
		for _, key := range []string{"labels", "downsample", "source"} {
			if !reflect.DeepEqual(originalThanos[key], targetThanos[key]) {
				return errors.New("recovery changed semantic Thanos metadata")
			}
		}
	}
	return writeJSON(filepath.Join(output, "recovery-verification.json"), map[string]any{"verified": true, "block": ids[0].String(), "sourceULID": a.SourceULID, "samples": count, "canonicalSHA256": digest, "removedSamples": a.RemovedSamples, "removedMetric": metricName, "removedMinTime": a.MinTime, "removedMaxTime": a.MaxTime, "maximumLossWindowMS": a.MaximumLossWindowMS, "originalsDeleted": false, "productionModified": false, "allOtherSamplesCanonicalVerified": true})
}
