package main

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func TestCanonicalStreamMatchesLegacyBytesAndBoundaries(t *testing.T) {
	expected := sha256.New()
	actual := newCanonicalStream()
	for i := 0; i < 513; i++ {
		data := make([]byte, 10001+i)
		for j := range data {
			data[j] = byte(i + j)
		}
		expected.Write(data)
		actual.Write(data)
	}
	want := hex.EncodeToString(expected.Sum(nil))
	if got := actual.close(); got != want {
		t.Fatalf("canonical stream changed: %s vs %s", got, want)
	}
	if actual.close() != want {
		t.Fatal("close is not idempotent")
	}
}
func TestParallelPrefetchImportExactAndCancel(t *testing.T) {
	values := make([]float64, 20001)
	for i := range values {
		values[i] = float64(i % 991)
	}
	source := fixture(t, values)
	encoded := filepath.Join(t.TempDir(), "otlp")
	if err := exportWithResume(source, encoded, 64<<20, "", false, 16); err != nil {
		t.Fatal(err)
	}
	for _, workers := range []int{1, 4, 16} {
		out := filepath.Join(t.TempDir(), "import")
		if err := importBlockWithOptions(encoded, out, 5100, true, workers); err != nil {
			t.Fatal(err)
		}
		blocks, _ := filepath.Glob(filepath.Join(out, "*", "meta.json"))
		if len(blocks) != 1 {
			t.Fatal("missing native block")
		}
		if err := verifyBlock(encoded, filepath.Dir(blocks[0])); err != nil {
			t.Fatal(err)
		}
	}
	manifest, err := loadManifestWithWorkers(encoded, 16)
	if err != nil {
		t.Fatal(err)
	}
	files, err := orderedFiles(manifest.Files)
	if err != nil {
		t.Fatal(err)
	}
	p, err := newImportPrefetch(encoded, files, 16)
	if err != nil {
		t.Fatal(err)
	}
	p.close()
	p.close()
	os.WriteFile(filepath.Join(encoded, files[0]), []byte("corrupt"), 0600)
	if _, err = loadManifestWithWorkers(encoded, 16); err == nil {
		t.Fatal("parallel SHA accepted corruption")
	}
	p, err = newImportPrefetch(encoded, files, 16)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = p.next(0); err == nil {
		p.close()
		t.Fatal("prefetch accepted corrupt gzip")
	}
	p.close()
}
func BenchmarkImportPrefetch(b *testing.B) {
	values := make([]float64, 250000)
	for i := range values {
		values[i] = float64(i % 997)
	}
	source := fixture(b, values)
	encoded := filepath.Join(b.TempDir(), "otlp")
	if err := exportWithResume(source, encoded, 256<<20, "", false, 16); err != nil {
		b.Fatal(err)
	}
	for _, workers := range []int{1, 4, 16} {
		b.Run(fmt.Sprintf("workers-%d", workers), func(b *testing.B) {
			for i := 0; i < b.N; i++ {
				out := filepath.Join(b.TempDir(), "import")
				if err := importBlockWithOptions(encoded, out, importShardSamples, true, workers); err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}

func TestConcurrentNativeCompactionPreservesFullCanonical(t *testing.T) {
	values := make([]float64, 50001)
	for i := range values {
		values[i] = float64(i % 911)
	}
	source := fixture(t, values)
	encoded := filepath.Join(t.TempDir(), "otlp")
	if err := exportWithResume(source, encoded, 64<<20, "", false, 16); err != nil {
		t.Fatal(err)
	}
	// >16shards forces independent level0 compactions followed by ordered merge.
	out := filepath.Join(t.TempDir(), "import")
	if err := importBlockWithOptions(encoded, out, 1000, true, 16); err != nil {
		t.Fatal(err)
	}
	blocks, _ := filepath.Glob(filepath.Join(out, "*", "meta.json"))
	if len(blocks) != 1 {
		t.Fatal("missing final native block")
	}
	if err := verifyBlock(encoded, filepath.Dir(blocks[0])); err != nil {
		t.Fatal(err)
	}
}
