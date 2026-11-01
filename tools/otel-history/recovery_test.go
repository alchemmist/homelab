package main

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"hash/crc32"
	"math"
	"os"
	"path/filepath"
	"testing"

	"github.com/prometheus/prometheus/model/labels"
	"github.com/prometheus/prometheus/tsdb"
	"github.com/prometheus/prometheus/tsdb/chunks"
	"github.com/prometheus/prometheus/tsdb/index"
)

func corruptRecoveryFixture(t *testing.T) (string, LossApproval, uint64, string) {
	t.Helper()
	values := make([]float64, 1000)
	for i := range values {
		values[i] = float64(i % 131)
		if i%77 == 0 {
			values[i] = math.Float64frombits(staleNaN)
		}
	}
	source := fixture(t, values)
	b, err := tsdb.OpenBlock(logger, source, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	ir, err := b.Index()
	if err != nil {
		t.Fatal(err)
	}
	key, val := index.AllPostingsKey()
	p, err := ir.Postings(context.Background(), key, val)
	if err != nil {
		t.Fatal(err)
	}
	if !p.Next() {
		t.Fatal("no fixture series")
	}
	var builder labels.ScratchBuilder
	var metas []chunks.Meta
	if err = ir.Series(p.At(), &builder, &metas); err != nil {
		t.Fatal(err)
	}
	m := metas[1]
	ls := builder.Labels()
	h := sha256.Sum256([]byte(ls.String()))
	a := LossApproval{SchemaVersion: 1, SourceULID: b.Meta().ULID.String(), ChunkRef: uint64(m.Ref), LabelsSHA256: hex.EncodeToString(h[:]), MinTime: m.MinTime, MaxTime: m.MaxTime, MaximumLossWindowMS: 86400000, Files: map[string]string{}}
	cr, err := b.Chunks()
	if err != nil {
		t.Fatal(err)
	}
	chunk, _, err := cr.ChunkOrIterable(m)
	if err != nil {
		t.Fatal(err)
	}
	a.RemovedSamples = uint64(chunk.NumSamples())
	cr.Close()
	ir.Close()
	b.Close()
	expected := sha256.New()
	var count uint64
	var buffer [16]byte
	_, _, err = walk(source, func(ls labels.Labels, ts int64, v float64) error {
		hash := sha256.Sum256([]byte(ls.String()))
		if hex.EncodeToString(hash[:]) == a.LabelsSHA256 && ts >= a.MinTime && ts <= a.MaxTime {
			return nil
		}
		str := ls.String()
		prefix := make([]byte, 8+len(str))
		binary.LittleEndian.PutUint64(prefix[:8], uint64(len(str)))
		copy(prefix[8:], str)
		addSampleHash(expected, prefix, buffer[:], ts, v)
		count++
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	segment, off := chunks.BlockChunkRef(m.Ref).Unpack()
	name := filepath.Join(source, "chunks", fmtSegment(segment+1))
	f, err := os.OpenFile(name, os.O_RDWR, 0)
	if err != nil {
		t.Fatal(err)
	}
	header := make([]byte, 10)
	if _, err = f.ReadAt(header, int64(off)); err != nil {
		t.Fatal(err)
	}
	size, n := binary.Uvarint(header)
	data := make([]byte, int(size)+5)
	if _, err = f.ReadAt(data, int64(off+n)); err != nil {
		t.Fatal(err)
	}
	a.StoredCRC = binary.BigEndian.Uint32(data[int(size)+1:])
	data[int(size)] ^= 1
	a.ActualCRC = crc32.Checksum(data[:int(size)+1], crc32.MakeTable(crc32.Castagnoli))
	if _, err = f.WriteAt(data, int64(off+n)); err != nil {
		t.Fatal(err)
	}
	f.Close()
	err = filepath.WalkDir(source, func(path string, e os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if e.IsDir() {
			return nil
		}
		rel, _ := filepath.Rel(source, path)
		digest, err := fileHash(path)
		a.Files[filepath.ToSlash(rel)] = digest
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
	return source, a, count, hex.EncodeToString(expected.Sum(nil))
}

func fmtSegment(segment int) string { return fmt.Sprintf("%06d", segment) }

func TestApprovedRecoveryDropsOnlyExactChunkAndPreservesAllOtherBits(t *testing.T) {
	source, approval, count, digest := corruptRecoveryFixture(t)
	if _, _, err := walk(source, nil); err == nil {
		t.Fatal("fixture CRC corruption was not detected")
	}
	out := filepath.Join(t.TempDir(), "recovery")
	if err := recoverApprovedChunk(source, out, approval); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(out, "recovery-verification.json"))
	if err != nil {
		t.Fatal(err)
	}
	var receipt struct {
		Verified        bool
		Block           string
		Samples         uint64
		CanonicalSHA256 string
	}
	if err = json.Unmarshal(data, &receipt); err != nil {
		t.Fatal(err)
	}
	if !receipt.Verified || receipt.Samples != count || receipt.CanonicalSHA256 != digest {
		t.Fatalf("changed healthy samples: %s", data)
	}
	for rel, expected := range approval.Files {
		actual, err := fileHash(filepath.Join(source, rel))
		if err != nil || actual != expected {
			t.Fatal("original was modified")
		}
	}
	if _, _, err = walk(source, nil); err == nil {
		t.Fatal("original corrupt source was repaired in place")
	}
	meta, err := metadata(filepath.Join(out, receipt.Block))
	if err != nil {
		t.Fatal(err)
	}
	var thanos map[string]any
	if err = json.Unmarshal(meta["thanos"], &thanos); err != nil {
		t.Fatal(err)
	}
	if len(thanos["files"].([]any)) < 3 {
		t.Fatal("physical file inventory was not regenerated")
	}
}

func TestRecoveryRejectsUnapprovedIdentityBudgetAndInputChanges(t *testing.T) {
	source, a, _, _ := corruptRecoveryFixture(t)
	for _, change := range []func(*LossApproval){func(a *LossApproval) { a.LabelsSHA256 = "wrong" }, func(a *LossApproval) { a.MaxTime++ }, func(a *LossApproval) { a.RemovedSamples++ }, func(a *LossApproval) { a.MaximumLossWindowMS = 86400001 }, func(a *LossApproval) { a.ActualCRC++ }, func(a *LossApproval) { a.SourceULID = "other" }} {
		copy := a
		change(&copy)
		if err := recoverApprovedChunk(source, filepath.Join(t.TempDir(), "bad"), copy); err == nil {
			t.Fatal("invalid approval accepted")
		}
	}
	a.Files["index"] = "wrong"
	if err := recoverApprovedChunk(source, filepath.Join(t.TempDir(), "bad"), a); err == nil {
		t.Fatal("input drift accepted")
	}
}
