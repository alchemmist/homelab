package main

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"math"
	"os"
	"path/filepath"
	"testing"

	"github.com/prometheus/prometheus/model/labels"
	"github.com/prometheus/prometheus/tsdb"
)

func fixture(t *testing.T, times []int64, values []float64, job string) string {
	t.Helper()
	root := t.TempDir()
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	writer, err := tsdb.NewBlockWriter(logger, root, 1000000)
	if err != nil {
		t.Fatal(err)
	}
	app := writer.Appender(context.Background())
	for i, timestamp := range times {
		if _, err = app.Append(0, labels.FromStrings("__name__", "test_metric", "job", job), timestamp, values[i]); err != nil {
			t.Fatal(err)
		}
	}
	if err = app.Commit(); err != nil {
		t.Fatal(err)
	}
	id, err := writer.Flush(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if err = writer.Close(); err != nil {
		t.Fatal(err)
	}
	block := filepath.Join(root, id.String())
	rewrite(t, block, func(meta map[string]any) {
		meta["thanos"] = map[string]any{"labels": map[string]string{"prometheus": "original"}, "downsample": map[string]int{"resolution": 0}}
	})
	return block
}

func rewrite(t *testing.T, block string, change func(map[string]any)) {
	t.Helper()
	path := filepath.Join(block, "meta.json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var meta map[string]any
	if err = json.Unmarshal(data, &meta); err != nil {
		t.Fatal(err)
	}
	change(meta)
	data, err = json.Marshal(meta)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
}

func TestCompleteSourceSubsetPreservesSpecialFloatBits(t *testing.T) {
	negativeZero := math.Copysign(0, -1)
	stale := math.Float64frombits(0x7ff0000000000002)
	source := fixture(t, []int64{10, 20, 30}, []float64{negativeZero, math.Inf(1), stale}, "same")
	target := fixture(t, []int64{0, 10, 20, 30, 40}, []float64{7, negativeZero, math.Inf(1), stale, 8}, "same")
	count, err := verify(source, target)
	if err != nil || count != 3 {
		t.Fatalf("count=%d error=%v", count, err)
	}
}

func TestMissingTimestampOrSignedZeroChangeFails(t *testing.T) {
	source := fixture(t, []int64{10}, []float64{math.Copysign(0, -1)}, "same")
	for _, target := range []string{
		fixture(t, []int64{0, 10, 20}, []float64{1, 0, 1}, "same"),
		fixture(t, []int64{0, 20}, []float64{1, 1}, "same"),
		fixture(t, []int64{0, 10, 20}, []float64{1, math.Copysign(0, -1), 1}, "different"),
	} {
		if _, err := verify(source, target); err == nil {
			t.Fatal("nonmatching historical source accepted")
		}
	}
}

func TestNoSelfOrDownsampleOrUnboundContextCertification(t *testing.T) {
	source := fixture(t, []int64{10}, []float64{1}, "same")
	if _, err := verify(source, source); err == nil {
		t.Fatal("self-proof accepted")
	}
	target := fixture(t, []int64{0, 10, 20}, []float64{1, 1, 1}, "same")
	rewrite(t, target, func(meta map[string]any) {
		meta["thanos"].(map[string]any)["downsample"] = map[string]int{"resolution": 300000}
	})
	if _, err := verify(source, target); err == nil {
		t.Fatal("downsample proof accepted")
	}
	rewrite(t, source, func(meta map[string]any) { delete(meta, "thanos") })
	if _, err := verify(source, target); err == nil {
		t.Fatal("invented missing context")
	}
}

func TestDeclaredSampleCountMustBeCompletelyCovered(t *testing.T) {
	source := fixture(t, []int64{10}, []float64{1}, "same")
	target := fixture(t, []int64{0, 10, 20}, []float64{1, 1, 1}, "same")
	rewrite(t, source, func(meta map[string]any) { meta["stats"].(map[string]any)["numSamples"] = 2 })
	if _, err := verify(source, target); err == nil {
		t.Fatal("partial source coverage accepted")
	}
}
