package main

import (
	"fmt"
	common "go.opentelemetry.io/proto/otlp/common/v1"
	"math"
	"path/filepath"
	"testing"
)

func TestCachedAndUncachedImportsBothExactAcrossShardAndBatchBoundaries(t *testing.T) {
	values := make([]float64, 10011)
	for i := range values {
		values[i] = float64(i % 17)
	}
	values[1] = math.Float64frombits(staleNaN)
	values[2] = math.Inf(-1)
	values[3] = math.Float64frombits(0x7ff8000000000042)
	source := fixture(t, values)
	encoded := filepath.Join(t.TempDir(), "otlp")
	if err := exportWithResume(source, encoded, 64<<20, "", false, 4); err != nil {
		t.Fatal(err)
	}
	for _, cache := range []bool{false, true} {
		output := filepath.Join(t.TempDir(), "import")
		if err := importBlockWithShardSize(encoded, output, 5100, cache); err != nil {
			t.Fatal(err)
		}
		blocks, err := filepath.Glob(filepath.Join(output, "*", "meta.json"))
		if err != nil || len(blocks) != 1 {
			t.Fatal("missing restored block")
		}
		if err = verifyBlock(encoded, filepath.Dir(blocks[0])); err != nil {
			t.Fatal(err)
		}
	}
}
func TestSeriesCacheRejectsDifferentAndInvalidAttributes(t *testing.T) {
	attr := func(k, v string) *common.KeyValue {
		return &common.KeyValue{Key: k, Value: &common.AnyValue{Value: &common.AnyValue_StringValue{StringValue: v}}}
	}
	a := []*common.KeyValue{attr("job", "one"), attr("instance", "two")}
	if !sameStringAttributes(a, []*common.KeyValue{attr("job", "one"), attr("instance", "two")}) {
		t.Fatal("identical rejected")
	}
	for _, b := range [][]*common.KeyValue{nil, {nil, nil}, {attr("job", "changed"), attr("instance", "two")}, {attr("instance", "two"), attr("job", "one")}, {attr("job", "one"), {Key: "instance", Value: &common.AnyValue{Value: &common.AnyValue_IntValue{IntValue: 2}}}}} {
		if sameStringAttributes(a, b) {
			t.Fatal("different/invalid cache hit")
		}
	}
}
func BenchmarkImportSeriesCache(b *testing.B) {
	values := make([]float64, 250000)
	for i := range values {
		values[i] = float64(i % 997)
	}
	source := fixture(b, values)
	encoded := filepath.Join(b.TempDir(), "otlp")
	if err := exportWithResume(source, encoded, 256<<20, "", false, 4); err != nil {
		b.Fatal(err)
	}
	for _, cache := range []bool{false, true} {
		b.Run(fmt.Sprintf("cache-%v", cache), func(b *testing.B) {
			b.SetBytes(int64(len(values) * 2 * 16))
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				output := filepath.Join(b.TempDir(), "import")
				if err := importBlockWithShardSize(encoded, output, importShardSamples, cache); err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}
