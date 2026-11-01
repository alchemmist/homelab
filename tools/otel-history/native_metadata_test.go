package main

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"testing"
)

func readMap(t *testing.T, path string) map[string]any {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err = json.Unmarshal(data, &m); err != nil {
		t.Fatal(err)
	}
	return m
}
func saveMap(t *testing.T, path string, m map[string]any) {
	t.Helper()
	data, err := json.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
}
func importedFixture(t *testing.T) (string, string, string) {
	t.Helper()
	source := fixture(t, []float64{1, math.Float64frombits(staleNaN), math.Inf(-1), math.Copysign(0, -1)})
	root := t.TempDir()
	exported, imported := filepath.Join(root, "otlp"), filepath.Join(root, "restored")
	if err := exportBlock(source, exported, 1024*1024); err != nil {
		t.Fatal(err)
	}
	if err := importBlock(exported, imported); err != nil {
		t.Fatal(err)
	}
	files, err := filepath.Glob(filepath.Join(imported, "*", "meta.json"))
	if err != nil || len(files) != 1 {
		t.Fatal("missing restored fixture")
	}
	return source, exported, filepath.Dir(files[0])
}

func TestNativeMetadataRejectsStaleFileSizesAndChangesToAncestry(t *testing.T) {
	_, exported, block := importedFixture(t)
	path := filepath.Join(block, "meta.json")
	original := readMap(t, path)
	broken := readMap(t, path)
	files := broken["thanos"].(map[string]any)["files"].([]any)
	files[0].(map[string]any)["size_bytes"] = float64(1)
	saveMap(t, path, broken)
	if err := verifyBlock(exported, block); err == nil {
		t.Fatal("stale physical inventory accepted")
	}
	saveMap(t, path, original)
	broken = readMap(t, path)
	broken["compaction"].(map[string]any)["level"] = float64(99)
	saveMap(t, path, broken)
	if err := verifyBlock(exported, block); err == nil {
		t.Fatal("changed whole-source ancestry accepted")
	}
}

func TestNormalizeLegacyMetadataCopiesOnlyAndPreservesExactCanonicalData(t *testing.T) {
	_, exported, block := importedFixture(t)
	path := filepath.Join(block, "meta.json")
	legacy := readMap(t, path)
	legacy["thanos"].(map[string]any)["files"] = []any{map[string]any{"rel_path": "index", "size_bytes": float64(1)}}
	legacy["thanos"].(map[string]any)["index_stats"] = map[string]any{"series_max_size": float64(99)}
	legacy["thanos"].(map[string]any)["upload_time"] = "2026-10-28T00:00:00Z"
	legacy["compaction"].(map[string]any)["level"] = float64(99)
	saveMap(t, path, legacy)
	before, err := fileHash(path)
	if err != nil {
		t.Fatal(err)
	}
	if err = normalizeNativeMetadata(exported, block, filepath.Join(block, "nested")); err == nil {
		t.Fatal("nested output accepted")
	}
	out := filepath.Join(t.TempDir(), "normalized")
	if err = normalizeNativeMetadata(exported, block, out); err != nil {
		t.Fatal(err)
	}
	after, err := fileHash(path)
	if err != nil || before != after {
		t.Fatal("coordinator-owned original was modified")
	}
	receipt := readMap(t, filepath.Join(out, "verification.json"))
	if receipt["verified"] != true || receipt["originalOutputModified"] != false || receipt["sourceAncestryPreserved"] != true {
		t.Fatal("incorrect normalization receipt")
	}
	restored := filepath.Join(out, receipt["block"].(string))
	if err = verifyBlock(exported, restored); err != nil {
		t.Fatal(err)
	}
	var beforeData, afterData string
	_, beforeData, err = walk(block, nil)
	if err != nil {
		t.Fatal(err)
	}
	_, afterData, err = walk(restored, nil)
	if err != nil || beforeData != afterData {
		t.Fatal("normalization changed samples")
	}
}

func TestNormalizationNeverRepairsSemanticLabelChanges(t *testing.T) {
	_, exported, block := importedFixture(t)
	path := filepath.Join(block, "meta.json")
	m := readMap(t, path)
	m["thanos"].(map[string]any)["labels"].(map[string]any)["prometheus"] = "another-cluster"
	saveMap(t, path, m)
	if err := normalizeNativeMetadata(exported, block, filepath.Join(t.TempDir(), "normalized")); err == nil {
		t.Fatal("semantic source change normalized away")
	}
}

func TestMetricPilotDoesNotClaimWholeBlockAncestry(t *testing.T) {
	source := fixture(t, []float64{1, 2, 3})
	root := t.TempDir()
	exported, imported := filepath.Join(root, "otlp"), filepath.Join(root, "restored")
	if err := exportWithResume(source, exported, 1024*1024, "requests_total", false); err != nil {
		t.Fatal(err)
	}
	if err := importBlock(exported, imported); err != nil {
		t.Fatal(err)
	}
	files, _ := filepath.Glob(filepath.Join(imported, "*", "meta.json"))
	if len(files) != 1 {
		t.Fatal("missing pilot block")
	}
	src, _ := metadata(source)
	dst, _ := metadata(filepath.Dir(files[0]))
	if equalJSON(src["compaction"], dst["compaction"]) {
		t.Fatal("partial pilot falsely claims all original ancestors")
	}
	if err := verifyBlock(exported, filepath.Dir(files[0])); err != nil {
		t.Fatal(err)
	}
}

func TestMetadataNumbersAreExactAndNullThanosRejected(t *testing.T) {
	if equalJSON(json.RawMessage(`9007199254740992`), json.RawMessage(`9007199254740993`)) {
		t.Fatal("metadata integers rounded through float64")
	}
	if _, err := semanticThanos(json.RawMessage(`null`)); err == nil {
		t.Fatal("present null Thanos metadata accepted")
	}
}
