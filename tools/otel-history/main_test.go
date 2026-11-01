package main

import (
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"testing"

	"github.com/prometheus/prometheus/model/labels"
	"github.com/prometheus/prometheus/tsdb"
	collector "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	"google.golang.org/protobuf/proto"
	"io"
)

func fixture(t testing.TB, samples []float64) string {
	t.Helper()
	directory := t.TempDir()
	writer, err := tsdb.NewBlockWriter(logger, directory, int64(len(samples)+1)*10000)
	if err != nil {
		t.Fatal(err)
	}
	appender := writer.Appender(context.Background())
	for _, name := range []string{"requests_total", "temperature"} {
		for i, value := range samples {
			if _, err = appender.Append(0, labels.FromStrings("__name__", name, "instance", "10.250.0.2:9100", "job", "fixture", "region", "démo"), int64(10000+i*5000), value); err != nil {
				t.Fatal(err)
			}
		}
	}
	if err = appender.Commit(); err != nil {
		t.Fatal(err)
	}
	id, err := writer.Flush(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if err = writer.Close(); err != nil {
		t.Fatal(err)
	}
	block := filepath.Join(directory, id.String())
	path := filepath.Join(block, "meta.json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var meta map[string]any
	if err = json.Unmarshal(data, &meta); err != nil {
		t.Fatal(err)
	}
	meta["thanos"] = map[string]any{"labels": map[string]string{"prometheus": "fixture"}, "downsample": map[string]int{"resolution": 0}}
	data, _ = json.Marshal(meta)
	if err = os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	return block
}

func TestStandardOTLPRoundtrip(t *testing.T) {
	source := fixture(t, []float64{4, 6, 1, 3, math.Inf(1), math.Inf(-1), math.Float64frombits(0x7ff8000000000042)})
	workspace := t.TempDir()
	exported := filepath.Join(workspace, "export")
	imported := filepath.Join(workspace, "import")
	if err := exportBlock(source, exported, 1024*1024); err != nil {
		t.Fatal(err)
	}
	if err := importBlock(exported, imported); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(imported, "verification.json"))
	if err != nil {
		t.Fatal(err)
	}
	var receipt struct {
		Verified bool
		Samples  uint64
		Block    string
	}
	if err = json.Unmarshal(data, &receipt); err != nil {
		t.Fatal(err)
	}
	if !receipt.Verified || receipt.Samples != 14 {
		t.Fatalf("unexpected receipt: %s", data)
	}
	original, err := metadata(source)
	if err != nil {
		t.Fatal(err)
	}
	restored, err := metadata(filepath.Join(imported, receipt.Block))
	if err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"minTime", "maxTime", "compaction"} {
		var a, b any
		json.Unmarshal(original[key], &a)
		json.Unmarshal(restored[key], &b)
		x, _ := json.Marshal(a)
		y, _ := json.Marshal(b)
		if string(x) != string(y) {
			t.Fatalf("metadata changed: %s", key)
		}
	}
	manifest, err := loadManifest(exported)
	if err != nil {
		t.Fatal(err)
	}
	if err = verifyRestoredMetadata(manifest, filepath.Join(imported, receipt.Block)); err != nil {
		t.Fatal(err)
	}
	if _, err = os.Stat(filepath.Join(source, "meta.json")); err != nil {
		t.Fatal("original was removed")
	}
}

func TestStaleMarkersUseStandardNoRecordedValue(t *testing.T) {
	source := fixture(t, []float64{1, math.Float64frombits(staleNaN)})
	workspace := t.TempDir()
	exported := filepath.Join(workspace, "export")
	if err := exportBlock(source, exported, 1024*1024); err != nil {
		t.Fatal(err)
	}
	file, err := os.Open(filepath.Join(exported, "000000.otlp.pb.gz"))
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	zipped, err := gzip.NewReader(file)
	if err != nil {
		t.Fatal(err)
	}
	defer zipped.Close()
	data, err := io.ReadAll(zipped)
	if err != nil {
		t.Fatal(err)
	}
	request := &collector.ExportMetricsServiceRequest{}
	if err = proto.Unmarshal(data, request); err != nil {
		t.Fatal(err)
	}
	stale := 0
	for _, resource := range request.ResourceMetrics {
		for _, scope := range resource.ScopeMetrics {
			for _, metric := range scope.Metrics {
				for _, point := range metric.GetGauge().DataPoints {
					if point.Flags == 1 {
						stale++
					}
				}
			}
		}
	}
	if stale != 2 {
		t.Fatalf("expected two standard stale flags, got %d", stale)
	}
	if err = importBlock(exported, filepath.Join(workspace, "import")); err != nil {
		t.Fatal(err)
	}
}

func TestDownsampledBlocksRemainNative(t *testing.T) {
	source := fixture(t, []float64{1})
	path := filepath.Join(source, "meta.json")
	data, _ := os.ReadFile(path)
	var meta map[string]any
	json.Unmarshal(data, &meta)
	meta["thanos"] = map[string]any{"downsample": map[string]int{"resolution": 300000}}
	data, _ = json.Marshal(meta)
	os.WriteFile(path, data, 0600)
	if _, err := metadata(source); err == nil {
		t.Fatal("downsampled block was accepted")
	}
}

func TestBudgetFailureDoesNotPublishExport(t *testing.T) {
	source := fixture(t, []float64{1, 2, 3})
	output := filepath.Join(t.TempDir(), "export")
	if err := exportBlock(source, output, 1); err == nil {
		t.Fatal("byte budget was ignored")
	}
	if _, err := os.Stat(filepath.Join(output, "manifest.json")); !os.IsNotExist(err) {
		t.Fatal("partial export was published")
	}
}

func TestCorruptionRejectedBeforeImport(t *testing.T) {
	source := fixture(t, []float64{1, 2, 3})
	workspace := t.TempDir()
	exported := filepath.Join(workspace, "export")
	if err := exportBlock(source, exported, 1024*1024); err != nil {
		t.Fatal(err)
	}
	os.WriteFile(filepath.Join(exported, "000000.otlp.pb.gz"), []byte("corrupt"), 0600)
	imported := filepath.Join(workspace, "import")
	if err := importBlock(exported, imported); err == nil {
		t.Fatal("corruption was accepted")
	}
	if _, err := os.Stat(imported); !os.IsNotExist(err) {
		t.Fatal("import output was created before integrity validation")
	}
}

func TestOutputIsExclusiveAndProductionPathsRejected(t *testing.T) {
	existing := t.TempDir()
	if err := newOutput(existing); err == nil {
		t.Fatal("existing output was accepted")
	}
	if err := newOutput("/etc/otel-history-test"); err == nil {
		t.Fatal("production output was accepted")
	}
}

func TestLongSeriesAcrossOTLPBatchCommits(t *testing.T) {
	values := make([]float64, 6000)
	for i := range values {
		values[i] = float64(i)
	}
	source := fixture(t, values)
	workspace := t.TempDir()
	exported := filepath.Join(workspace, "export")
	if err := exportBlock(source, exported, 16*1024*1024); err != nil {
		t.Fatal(err)
	}
	if err := importBlock(exported, filepath.Join(workspace, "import")); err != nil {
		t.Fatal(err)
	}
}

func TestSelectedPilotIsNotReportedAsCompleteBlock(t *testing.T) {
	source := fixture(t, []float64{1, 2, 3})
	workspace := t.TempDir()
	exported := filepath.Join(workspace, "export")
	if err := exportBlock(source, exported, 1024*1024, "requests_total"); err != nil {
		t.Fatal(err)
	}
	manifest, err := loadManifest(exported)
	if err != nil {
		t.Fatal(err)
	}
	if manifest.CompleteSourceBlock || manifest.Samples != 3 || manifest.MetricSelection != "requests_total" {
		t.Fatal("pilot incorrectly reported as a complete export")
	}
	if err = importBlock(exported, filepath.Join(workspace, "import")); err != nil {
		t.Fatal(err)
	}
}

func TestChunkCapabilitiesIncludeStandardStaleness(t *testing.T) {
	source := fixture(t, []float64{1, math.Float64frombits(staleNaN)})
	report, err := capabilities(source)
	if err != nil {
		t.Fatal(err)
	}
	if report["standardOTLPRepresentable"] != true || report["canonicalSamplesVerified"] != false || report["samplesInChunks"] != uint64(4) {
		t.Fatalf("unexpected report: %+v", report)
	}
}

func TestCanonicalHashIsUnchangedByPrefixCaching(t *testing.T) {
	source := fixture(t, []float64{1, math.Float64frombits(staleNaN), math.Inf(-1)})
	legacy := sha256.New()
	_, actual, err := walk(source, func(ls labels.Labels, timestamp int64, value float64) error {
		text := ls.String()
		binary.Write(legacy, binary.LittleEndian, uint64(len(text)))
		legacy.Write([]byte(text))
		binary.Write(legacy, binary.LittleEndian, timestamp)
		binary.Write(legacy, binary.LittleEndian, math.Float64bits(value))
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if actual != hex.EncodeToString(legacy.Sum(nil)) {
		t.Fatal("canonical digest format changed")
	}
}

func TestVerificationRejectsChangedExternalLabels(t *testing.T) {
	source := fixture(t, []float64{1, 2})
	root := t.TempDir()
	exported, imported := filepath.Join(root, "exported"), filepath.Join(root, "imported")
	if err := exportBlock(source, exported, 1024*1024); err != nil {
		t.Fatal(err)
	}
	if err := importBlock(exported, imported); err != nil {
		t.Fatal(err)
	}
	files, err := filepath.Glob(filepath.Join(imported, "*", "meta.json"))
	if err != nil || len(files) != 1 {
		t.Fatal("restored metadata not found")
	}
	data, err := os.ReadFile(files[0])
	if err != nil {
		t.Fatal(err)
	}
	var metadata map[string]any
	if err = json.Unmarshal(data, &metadata); err != nil {
		t.Fatal(err)
	}
	metadata["thanos"].(map[string]any)["labels"] = map[string]string{"prometheus": "unexpected"}
	data, err = json.Marshal(metadata)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(files[0], data, 0600); err != nil {
		t.Fatal(err)
	}
	if err = verifyBlock(exported, filepath.Dir(files[0])); err == nil {
		t.Fatal("external label changes were not detected")
	}
}

func TestResumeExportVerifiesAndReusesExistingBatches(t *testing.T) {
	source := fixture(t, make([]float64, 6000))
	output := filepath.Join(t.TempDir(), "export")
	if err := exportBlock(source, output, 1); err == nil {
		t.Fatal("expected bounded partial export")
	}
	path := filepath.Join(output, "000000.otlp.pb.gz")
	before, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if err = exportWithResume(source, output, 1024*1024, "", true); err != nil {
		t.Fatal(err)
	}
	after, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if !before.ModTime().Equal(after.ModTime()) {
		t.Fatal("verified batch was rewritten")
	}
	if err = importBlock(output, filepath.Join(t.TempDir(), "restored")); err != nil {
		t.Fatal(err)
	}
	if err = exportWithResume(source, output, 1024*1024, "", true); err == nil {
		t.Fatal("completed export was overwritten")
	}
}

func TestResumeCorruptionNeverPublishesManifest(t *testing.T) {
	source := fixture(t, make([]float64, 6000))
	output := filepath.Join(t.TempDir(), "export")
	if err := exportBlock(source, output, 1); err == nil {
		t.Fatal("expected partial export")
	}
	path := filepath.Join(output, "000000.otlp.pb.gz")
	if err := os.WriteFile(path, []byte("retained-corruption"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := exportWithResume(source, output, 1024*1024, "", true); err == nil {
		t.Fatal("corrupt prefix was accepted")
	}
	if _, err := os.Stat(filepath.Join(output, "manifest.json")); !os.IsNotExist(err) {
		t.Fatal("corrupt export published a manifest")
	}
	data, err := os.ReadFile(path)
	if err != nil || string(data) != "retained-corruption" {
		t.Fatal("failed artifact was modified")
	}
}

func TestNumericBatchOrderingAcrossOneMillion(t *testing.T) {
	samples := make([]float64, 6000)
	for index := range samples {
		samples[index] = float64(index)
	}
	source := fixture(t, samples)
	output := filepath.Join(t.TempDir(), "export")
	if err := exportBlock(source, output, 1024*1024); err != nil {
		t.Fatal(err)
	}
	manifest, err := loadManifest(output)
	if err != nil {
		t.Fatal(err)
	}
	names, err := orderedFiles(manifest.Files)
	if err != nil {
		t.Fatal(err)
	}
	renamed := map[string]string{}
	for index, name := range names {
		target := fmt.Sprintf("%d.otlp.pb.gz", 999999+index)
		if err = os.Rename(filepath.Join(output, name), filepath.Join(output, target)); err != nil {
			t.Fatal(err)
		}
		renamed[target] = manifest.Files[name]
	}
	manifest.Files = renamed
	data, err := json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(output, "manifest.json"), data, 0600); err != nil {
		t.Fatal(err)
	}
	if err = importBlock(output, filepath.Join(t.TempDir(), "restored")); err != nil {
		t.Fatal(err)
	}
	if _, err = orderedFiles(map[string]string{"000001.otlp.pb.gz": "a", "1.otlp.pb.gz": "b"}); err == nil {
		t.Fatal("duplicate numeric sequence was accepted")
	}
}
