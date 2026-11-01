package main

import (
	"path/filepath"
	"strconv"
	"testing"
)

func BenchmarkWalk(b *testing.B) {
	samples := make([]float64, 10000)
	for index := range samples {
		samples[index] = float64(index)
	}
	source := fixture(b, samples)
	b.ReportAllocs()
	b.ResetTimer()
	for index := 0; index < b.N; index++ {
		if _, _, err := walk(source, nil); err != nil {
			b.Fatal(err)
		}
	}
}

func BenchmarkExport(b *testing.B) {
	samples := make([]float64, 10000)
	for index := range samples {
		samples[index] = float64(index)
	}
	source := fixture(b, samples)
	output := b.TempDir()
	b.ReportAllocs()
	b.ResetTimer()
	for index := 0; index < b.N; index++ {
		if err := exportBlock(source, filepath.Join(output, strconv.Itoa(index)), 64*1024*1024); err != nil {
			b.Fatal(err)
		}
	}
}
