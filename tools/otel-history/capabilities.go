package main

import (
	"context"
	"encoding/json"
	"errors"
	"math"

	"github.com/prometheus/prometheus/model/labels"
	"github.com/prometheus/prometheus/tsdb"
	"github.com/prometheus/prometheus/tsdb/chunkenc"
	"github.com/prometheus/prometheus/tsdb/chunks"
)

func capabilities(path string) (map[string]any, error) {
	meta, err := metadata(path)
	if err != nil {
		return nil, err
	}
	var minimum, maximum int64
	if err = json.Unmarshal(meta["minTime"], &minimum); err != nil {
		return nil, err
	}
	if err = json.Unmarshal(meta["maxTime"], &maximum); err != nil {
		return nil, err
	}
	if minimum < 0 || maximum <= minimum || maximum > math.MaxInt64/1000000 {
		return nil, errors.New("timestamp cannot be represented by standard OTLP")
	}
	block, err := tsdb.OpenBlock(logger, path, nil, nil)
	if err != nil {
		return nil, err
	}
	defer block.Close()
	querier, err := tsdb.NewBlockChunkQuerier(block, math.MinInt64, math.MaxInt64)
	if err != nil {
		return nil, err
	}
	defer querier.Close()
	set := querier.Select(context.Background(), false, nil, labels.MustNewMatcher(labels.MatchRegexp, "__name__", ".+"))
	var iterator chunks.Iterator
	var series, count, samples uint64
	for set.Next() {
		series++
		iterator = set.At().Iterator(iterator)
		for iterator.Next() {
			meta := iterator.At()
			if meta.Chunk == nil {
				return nil, errors.New("unpopulated chunk cannot be classified")
			}
			if meta.Chunk.Encoding() != chunkenc.EncXOR {
				return nil, errors.New("native histogram samples require native preservation")
			}
			count++
			samples += uint64(meta.Chunk.NumSamples())
		}
		if err = iterator.Err(); err != nil {
			return nil, err
		}
	}
	if err = set.Err(); err != nil {
		return nil, err
	}
	return map[string]any{
		"standardOTLPRepresentable": true, "stalenessEncoding": "NoRecordedValue",
		"series": series, "chunks": count, "samplesInChunks": samples,
		"canonicalSamplesVerified": false,
	}, nil
}
