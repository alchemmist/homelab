package main

import (
	"compress/gzip"
	"context"
	"io"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"testing"

	"github.com/prometheus/prometheus/model/histogram"
	"github.com/prometheus/prometheus/model/labels"
	"github.com/prometheus/prometheus/storage"
	"github.com/prometheus/prometheus/storage/remote/otlptranslator/prometheusremotewrite"
	"go.opentelemetry.io/collector/pdata/pmetric/pmetricotlp"
)

type capturedSamples struct {
	storage.AppenderV2
	samples map[string]uint64
}

func (capture *capturedSamples) Append(ref storage.SeriesRef, ls labels.Labels, st, timestamp int64, value float64, h *histogram.Histogram, fh *histogram.FloatHistogram, options storage.AppendV2Options) (storage.SeriesRef, error) {
	capture.samples[ls.String()+":"+strconv.FormatInt(timestamp, 10)] = math.Float64bits(value)
	return 1, nil
}

func TestExportThroughPrometheus315OTLPTranslator(t *testing.T) {
	source := fixture(t, []float64{1, math.Float64frombits(staleNaN), math.Inf(1), math.Inf(-1), math.Float64frombits(0x7ff8000000000042), math.Copysign(0, -1)})
	output := filepath.Join(t.TempDir(), "export")
	if err := exportBlock(source, output, 1024*1024); err != nil {
		t.Fatal(err)
	}
	file, err := os.Open(filepath.Join(output, "000000.otlp.pb.gz"))
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	reader, err := gzip.NewReader(file)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	data, err := io.ReadAll(reader)
	if err != nil {
		t.Fatal(err)
	}
	request := pmetricotlp.NewExportRequest()
	if err = request.UnmarshalProto(data); err != nil {
		t.Fatal(err)
	}
	capture := &capturedSamples{samples: map[string]uint64{}}
	converter := prometheusremotewrite.NewPrometheusConverter(capture)
	_, err = converter.FromMetrics(context.Background(), request.Metrics(), prometheusremotewrite.Settings{
		DisableTargetInfo: true, AllowUTF8: true, LabelNamePreserveMultipleUnderscores: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	count, _, err := walk(source, func(ls labels.Labels, timestamp int64, value float64) error {
		key := ls.String() + ":" + strconv.FormatInt(timestamp, 10)
		actual, exists := capture.samples[key]
		if !exists || actual != math.Float64bits(value) {
			t.Fatalf("Prometheus OTLP translation changed source sample %s", key)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if uint64(len(capture.samples)) != count {
		t.Fatal("Prometheus OTLP translation changed sample count")
	}
}
