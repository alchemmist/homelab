package main

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestParallelExportExactSerialBytesAndRoundtrip(t *testing.T) {
	values := make([]float64, 16001)
	for i := range values {
		values[i] = float64(i) / 7
	}
	values[2] = math.Inf(1)
	values[3] = math.Inf(-1)
	values[4] = math.Float64frombits(staleNaN)
	values[5] = math.Float64frombits(0x7ff8000000000042)
	source := fixture(t, values)
	serial := filepath.Join(t.TempDir(), "serial")
	parallel := filepath.Join(t.TempDir(), "parallel")
	if err := exportWithResume(source, serial, 64<<20, "", false, 1); err != nil {
		t.Fatal(err)
	}
	if err := exportWithResume(source, parallel, 64<<20, "", false, 16); err != nil {
		t.Fatal(err)
	}
	a, err := os.ReadFile(filepath.Join(serial, "manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(filepath.Join(parallel, "manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	var x, y Manifest
	if err = json.Unmarshal(a, &x); err != nil {
		t.Fatal(err)
	}
	if err = json.Unmarshal(b, &y); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(x, y) {
		t.Fatal("parallel manifest/count/digest/filenames/compressed hashes differ")
	}
	if len(x.Files) < 6 {
		t.Fatal("fixture must span concurrent batches")
	}
	restored := filepath.Join(t.TempDir(), "restored")
	if err = importBlock(parallel, restored); err != nil {
		t.Fatal(err)
	}
	// A completed manifest never permits overwrite, even in resume mode.
	if err = exportWithResume(source, parallel, 64<<20, "", true, 16); err == nil {
		t.Fatal("completed export overwritten")
	}
	if err = os.Remove(filepath.Join(parallel, "manifest.json")); err != nil {
		t.Fatal(err)
	}
	if err = exportWithResume(source, parallel, 64<<20, "", true, 16); err != nil {
		t.Fatal(err)
	}
	b, _ = os.ReadFile(filepath.Join(parallel, "manifest.json"))
	if string(a) != string(b) {
		t.Fatal("resume changed manifest bytes")
	}
	// Parallel interruption may leave a hole before a later completed batch.
	if err = os.Remove(filepath.Join(parallel, "manifest.json")); err != nil {
		t.Fatal(err)
	}
	if err = os.Remove(filepath.Join(parallel, "000002.otlp.pb.gz")); err != nil {
		t.Fatal(err)
	}
	if err = exportWithResume(source, parallel, 64<<20, "", true, 16); err != nil {
		t.Fatal(err)
	}
	b, _ = os.ReadFile(filepath.Join(parallel, "manifest.json"))
	if string(a) != string(b) {
		t.Fatal("sparse resume changed exact batch manifest")
	}
}

func TestParallelExportFailuresNeverWriteSuccessManifest(t *testing.T) {
	source := fixture(t, []float64{1, 2, 3})
	for _, workers := range []int{0, 51, 4} {
		output := filepath.Join(t.TempDir(), "export")
		if err := exportWithResume(source, output, 1, "", false, workers); err == nil {
			t.Fatal("invalid workers/budget accepted")
		}
		if _, err := os.Stat(filepath.Join(output, "manifest.json")); !os.IsNotExist(err) {
			t.Fatal("failed export created success manifest")
		}
	}
	output := filepath.Join(t.TempDir(), "export")
	if err := exportWithResume(source, output, 64<<20, "", false, 4); err != nil {
		t.Fatal(err)
	}
	os.Remove(filepath.Join(output, "manifest.json"))
	if err := os.WriteFile(filepath.Join(output, "000000.otlp.pb.gz"), []byte("corrupt"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := exportWithResume(source, output, 64<<20, "", true, 4); err == nil {
		t.Fatal("corrupt resume accepted")
	}
	if _, err := os.Stat(filepath.Join(output, "manifest.json")); !os.IsNotExist(err) {
		t.Fatal("failed resume published manifest")
	}
}

func BenchmarkExportWorkers(b *testing.B) {
	values := make([]float64, 250000)
	for i := range values {
		values[i] = math.Sin(float64(i)) * float64(i%997)
	}
	source := fixture(b, values)
	for _, workers := range []int{16, 32, 50} {
		b.Run(fmt.Sprintf("workers-%d", workers), func(b *testing.B) {
			b.SetBytes(int64(len(values) * 2 * 16))
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				output := filepath.Join(b.TempDir(), "export")
				if err := exportWithResume(source, output, 256<<20, "", false, workers); err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}

func TestFiftyWorkersPreserveSerialManifest(t *testing.T) {
	values := make([]float64, 15001)
	for i := range values {
		values[i] = math.Float64frombits(uint64(i))
	}
	source := fixture(t, values)
	a := filepath.Join(t.TempDir(), "serial")
	b := filepath.Join(t.TempDir(), "fifty")
	if err := exportWithResume(source, a, 64<<20, "", false, 1); err != nil {
		t.Fatal(err)
	}
	if err := exportWithResume(source, b, 64<<20, "", false, 50); err != nil {
		t.Fatal(err)
	}
	x, _ := os.ReadFile(filepath.Join(a, "manifest.json"))
	y, _ := os.ReadFile(filepath.Join(b, "manifest.json"))
	if string(x) != string(y) {
		t.Fatal("50 workers changed exact bytes/digest/count")
	}
}
