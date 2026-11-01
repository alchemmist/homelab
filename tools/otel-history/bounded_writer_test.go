package main

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	collector "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	"google.golang.org/protobuf/proto"
	"io"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func TestBoundedImportPreservesCanonicalAcrossShardsAndMergeLevels(t *testing.T) {
	for _, points := range []int{6200, 90001} {
		t.Run(strconv.Itoa(points), func(t *testing.T) {
			values := make([]float64, points)
			special := []float64{math.Float64frombits(staleNaN), math.Float64frombits(0x7ff8000000000042), math.Inf(1), math.Inf(-1), math.Copysign(0, -1), 0, -2}
			for i := range values {
				values[i] = float64(i % 5003)
				if i%997 == 0 {
					values[i] = special[(i/997)%len(special)]
				}
			}
			source := fixture(t, values)
			root := t.TempDir()
			exported, imported := filepath.Join(root, "export"), filepath.Join(root, "import")
			if err := exportBlock(source, exported, 64*1024*1024); err != nil {
				t.Fatal(err)
			}
			if err := importBlockWithShardSize(exported, imported, batchSize); err != nil {
				t.Fatal(err)
			}
			checkpoints, err := filepath.Glob(filepath.Join(imported, ".import-work", "shard-*.json"))
			if err != nil {
				t.Fatal(err)
			}
			if len(checkpoints) < 2 {
				t.Fatal("test did not cross shard boundary")
			}
			if points > 90000 && len(checkpoints) <= importCompactFanIn {
				t.Fatal("test did not exercise multiple compaction levels")
			}
			var total uint64
			for _, path := range checkpoints {
				data, err := os.ReadFile(path)
				if err != nil {
					t.Fatal(err)
				}
				var shard struct {
					Samples           uint64 `json:"samples"`
					CanonicalVerified bool   `json:"canonicalVerified"`
				}
				if err := json.Unmarshal(data, &shard); err != nil {
					t.Fatal(err)
				}
				if shard.CanonicalVerified || shard.Samples > batchSize {
					t.Fatalf("unbounded or prematurely verified shard: %+v", shard)
				}
				total += shard.Samples
			}
			if total != uint64(points*2) {
				t.Fatalf("lost samples in checkpoints: %d", total)
			}
			blocks, err := filepath.Glob(filepath.Join(imported, "*", "meta.json"))
			if err != nil {
				t.Fatal(err)
			}
			if len(blocks) != 1 {
				t.Fatalf("expected one published block, got %d", len(blocks))
			}
			if err := verifyBlock(exported, filepath.Dir(blocks[0])); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestBoundedImportRejectsZeroLimitBeforeCreatingOutput(t *testing.T) {
	output := filepath.Join(t.TempDir(), "not-created")
	if err := importBlockWithShardSize("missing", output, 0); err == nil {
		t.Fatal("accepted zero shard limit")
	}
	if _, err := os.Stat(output); !os.IsNotExist(err) {
		t.Fatal("invalid request created output")
	}
}

func TestBoundedImportRejectsInvalidPointBatches(t *testing.T) {
	for _, mode := range []string{"oversized", "empty"} {
		t.Run(mode, func(t *testing.T) {
			source := fixture(t, []float64{1})
			root := t.TempDir()
			exported := filepath.Join(root, "export")
			if err := exportBlock(source, exported, 1024*1024); err != nil {
				t.Fatal(err)
			}
			manifest, err := loadManifest(exported)
			if err != nil {
				t.Fatal(err)
			}
			names, err := orderedFiles(manifest.Files)
			if err != nil {
				t.Fatal(err)
			}
			name := names[0]
			f, err := os.Open(filepath.Join(exported, name))
			if err != nil {
				t.Fatal(err)
			}
			gz, err := gzip.NewReader(f)
			if err != nil {
				t.Fatal(err)
			}
			data, err := io.ReadAll(gz)
			if err != nil {
				t.Fatal(err)
			}
			gz.Close()
			f.Close()
			request := &collector.ExportMetricsServiceRequest{}
			if err := proto.Unmarshal(data, request); err != nil {
				t.Fatal(err)
			}
			gauge := request.ResourceMetrics[0].ScopeMetrics[0].Metrics[0].GetGauge()
			needle := "point limit"
			if mode == "empty" {
				for _, metric := range request.ResourceMetrics[0].ScopeMetrics[0].Metrics {
					metric.GetGauge().DataPoints = nil
				}
				needle = "empty OTLP"
			} else {
				for len(gauge.DataPoints) <= batchSize {
					gauge.DataPoints = append(gauge.DataPoints, gauge.DataPoints[0])
				}
			}
			data, err = proto.Marshal(request)
			if err != nil {
				t.Fatal(err)
			}
			var buf bytes.Buffer
			writer := gzip.NewWriter(&buf)
			if _, err = writer.Write(data); err != nil {
				t.Fatal(err)
			}
			if err = writer.Close(); err != nil {
				t.Fatal(err)
			}
			if err = os.WriteFile(filepath.Join(exported, name), buf.Bytes(), 0600); err != nil {
				t.Fatal(err)
			}
			manifest.Files[name], err = fileHash(filepath.Join(exported, name))
			if err != nil {
				t.Fatal(err)
			}
			encoded, err := json.Marshal(manifest)
			if err != nil {
				t.Fatal(err)
			}
			if err = os.WriteFile(filepath.Join(exported, "manifest.json"), encoded, 0600); err != nil {
				t.Fatal(err)
			}
			imported := filepath.Join(root, "import")
			err = importBlock(exported, imported)
			if err == nil || !strings.Contains(err.Error(), needle) {
				t.Fatalf("batch limit was not enforced before appending: %v", err)
			}
			if _, err = os.Stat(filepath.Join(imported, "verification.json")); !os.IsNotExist(err) {
				t.Fatal("invalid batch was published")
			}
		})
	}
}

func TestImportReserveRejectsImpossibleProjection(t *testing.T) {
	if err := requireImportSpace(t.TempDir(), ^uint64(0)); err == nil {
		t.Fatal("disk projection overflow was accepted")
	}
}
