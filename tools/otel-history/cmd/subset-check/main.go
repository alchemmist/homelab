// Verify every ordinary-label/timestamp/float-bit sample of an isolated source
// exists in another raw block. This is not whole-target integrity certification.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"math"
	"os"
	"path/filepath"
	"reflect"

	"github.com/prometheus/prometheus/model/labels"
	"github.com/prometheus/prometheus/tsdb"
	"github.com/prometheus/prometheus/tsdb/chunkenc"
)

type metadata struct {
	ULID    string `json:"ulid"`
	MinTime int64  `json:"minTime"`
	MaxTime int64  `json:"maxTime"`
	Stats   struct {
		Samples uint64 `json:"numSamples"`
	} `json:"stats"`
	Thanos struct {
		Labels     map[string]string `json:"labels"`
		Downsample struct {
			Resolution int64 `json:"resolution"`
		} `json:"downsample"`
	} `json:"thanos"`
}

func readMeta(path string) (metadata, error) {
	var meta metadata
	data, err := os.ReadFile(filepath.Join(path, "meta.json"))
	if err != nil {
		return meta, err
	}
	err = json.Unmarshal(data, &meta)
	return meta, err
}

func verify(source, target string) (uint64, error) {
	sm, err := readMeta(source)
	if err != nil {
		return 0, err
	}
	tm, err := readMeta(target)
	if err != nil {
		return 0, err
	}
	if sm.ULID == tm.ULID || sm.ULID == "" || tm.ULID == "" {
		return 0, errors.New("distinct source and target identities required")
	}
	if len(sm.Thanos.Labels) == 0 || !reflect.DeepEqual(sm.Thanos.Labels, tm.Thanos.Labels) {
		return 0, errors.New("independently established identical external context required")
	}
	if sm.Thanos.Downsample.Resolution != 0 || tm.Thanos.Downsample.Resolution != 0 {
		return 0, errors.New("downsampled aggregation is not a raw subset proof")
	}
	if sm.MinTime < tm.MinTime || sm.MaxTime > tm.MaxTime || sm.MinTime >= sm.MaxTime {
		return 0, errors.New("target does not cover complete source time bounds")
	}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	sb, err := tsdb.OpenBlock(logger, source, nil, nil)
	if err != nil {
		return 0, err
	}
	defer sb.Close()
	tb, err := tsdb.OpenBlock(logger, target, nil, nil)
	if err != nil {
		return 0, err
	}
	defer tb.Close()
	sq, err := tsdb.NewBlockQuerier(sb, sm.MinTime, sm.MaxTime-1)
	if err != nil {
		return 0, err
	}
	defer sq.Close()
	tq, err := tsdb.NewBlockQuerier(tb, sm.MinTime, sm.MaxTime-1)
	if err != nil {
		return 0, err
	}
	defer tq.Close()
	set := sq.Select(context.Background(), true, nil, labels.MustNewMatcher(labels.MatchRegexp, "__name__", ".+"))
	var count uint64
	for set.Next() {
		series := set.At()
		ls := series.Labels()
		var matchers []*labels.Matcher
		ls.Range(func(label labels.Label) {
			matchers = append(matchers, labels.MustNewMatcher(labels.MatchEqual, label.Name, label.Value))
		})
		matches := tq.Select(context.Background(), true, nil, matchers...)
		var targetIt chunkenc.Iterator
		for matches.Next() {
			found := matches.At()
			if labels.Equal(ls, found.Labels()) {
				if targetIt != nil {
					return 0, errors.New("ambiguous exact target series")
				}
				targetIt = found.Iterator(nil)
			}
		}
		if err = matches.Err(); err != nil {
			return 0, err
		}
		if targetIt == nil {
			return 0, errors.New("ordinary source label set absent from target")
		}
		sourceIt := series.Iterator(nil)
		typ := targetIt.Next()
		for st := sourceIt.Next(); st != chunkenc.ValNone; st = sourceIt.Next() {
			if st != chunkenc.ValFloat {
				return 0, errors.New("native histogram cannot be certified as a float subset")
			}
			timestamp, value := sourceIt.At()
			for typ != chunkenc.ValNone && targetIt.AtT() < timestamp {
				typ = targetIt.Next()
			}
			if typ != chunkenc.ValFloat || targetIt.AtT() != timestamp {
				return 0, errors.New("source float timestamp absent from target")
			}
			_, actual := targetIt.At()
			if math.Float64bits(actual) != math.Float64bits(value) {
				return 0, errors.New("historical float bits differ")
			}
			count++
			// Consume one target point per source point: never reuse a point to claim
			// preservation of duplicate source multiplicity.
			typ = targetIt.Next()
		}
		if err = sourceIt.Err(); err != nil {
			return 0, err
		}
		if err = targetIt.Err(); err != nil {
			return 0, err
		}
	}
	if err = set.Err(); err != nil {
		return 0, err
	}
	if count == 0 || count != sm.Stats.Samples {
		return 0, errors.New("complete declared source sample count was not verified")
	}
	return count, nil
}

func main() {
	source := flag.String("source", "", "isolated complete source block")
	target := flag.String("target", "", "isolated covering raw block")
	flag.Parse()
	if *source == "" || *target == "" {
		fmt.Fprintln(os.Stderr, "source and target required")
		os.Exit(1)
	}
	count, err := verify(*source, *target)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	json.NewEncoder(os.Stdout).Encode(map[string]any{"sourceSamplesVerified": count, "fullSourceSubsetVerified": true, "ordinaryLabelsTimestampsFloatBitsAndMultiplicityVerified": true, "wholeTargetIntegrityVerified": false, "canonicalVerificationReplaced": false, "productionModified": false})
}
