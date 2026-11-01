package main

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"testing"
)

func TestExactNativePrefixResumeAndChangedShardRefusal(t *testing.T) {
	values := make([]float64, 12001)
	for i := range values {
		values[i] = float64(i % 199)
	}
	values[1] = math.Float64frombits(staleNaN)
	values[2] = math.Inf(1)
	source := fixture(t, values)
	encoded := filepath.Join(t.TempDir(), "otlp")
	if err := exportWithResume(source, encoded, 64<<20, "", false, 16); err != nil {
		t.Fatal(err)
	}
	previous := filepath.Join(t.TempDir(), "previous")
	if err := importBlockWithOptions(encoded, previous, 5000, true, 4); err != nil {
		t.Fatal(err)
	}
	proof, err := proveImportPrefix(encoded, previous, 4)
	if err != nil {
		t.Fatal(err)
	}
	if !proof.Verified || proof.Samples != 20000 || proof.Files != 4 {
		t.Fatalf("bad prefix: %+v", proof)
	}
	path := filepath.Join(t.TempDir(), "proof.json")
	data, _ := json.Marshal(proof)
	os.WriteFile(path, data, 0600)
	out := filepath.Join(t.TempDir(), "resumed")
	if err = importBlockWithOptions(encoded, out, importShardSamples, true, 16, path); err != nil {
		t.Fatal(err)
	}
	blocks, _ := filepath.Glob(filepath.Join(out, "*", "meta.json"))
	if len(blocks) != 1 {
		t.Fatal("missing resumed native block")
	}
	if err = verifyBlock(encoded, filepath.Dir(blocks[0])); err != nil {
		t.Fatal(err)
	}
	// A closed native block cannot be adopted after modification, even if its old
	// source count/checkpoint receipt remains unchanged.
	native := filepath.Join(proof.Shards[0].Directory, "meta.json")
	old, _ := os.ReadFile(native)
	os.WriteFile(native, append(old, ' '), 0600)
	if _, err = loadImportPrefix(path, encoded); err == nil {
		t.Fatal("changed prefix shard accepted")
	}
}
