package main

import common "go.opentelemetry.io/proto/otlp/common/v1"

// Cache only consecutive identical, already-validated attributes. Different
// order, type, name, value, nil or cardinality takes the original validation
// path. Ref and labels reset for every appender/batch, including shard changes.
func sameStringAttributes(a, b []*common.KeyValue) bool {
	if len(a) != len(b) {
		return false
	}
	for i, x := range a {
		y := b[i]
		if x == nil || y == nil || x.Key != y.Key || x.Value == nil || y.Value == nil {
			return false
		}
		xs, xok := x.Value.Value.(*common.AnyValue_StringValue)
		ys, yok := y.Value.Value.(*common.AnyValue_StringValue)
		if !xok || !yok || xs.StringValue != ys.StringValue {
			return false
		}
	}
	return true
}
