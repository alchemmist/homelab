// Select finite native TSDB anchors for independent stock Store/Query checks.
// This does not replace the complete canonical verification.
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

	"github.com/prometheus/prometheus/model/labels"
	"github.com/prometheus/prometheus/tsdb"
	"github.com/prometheus/prometheus/tsdb/chunkenc"
)

type anchor struct {
	Selector  string            `json:"selector"`
	Labels    map[string]string `json:"labels"`
	Timestamp int64             `json:"timestampMilliseconds"`
	ValueBits string            `json:"valueBits"`
}

func run(block string) error {
	return runMode(block, false)
}

// sourceOnly extracts ordinary source labels for independent historical context discovery.
// It never adds metadata or claims that missing external context has been verified.
func runMode(block string, sourceOnly bool) error {
	data, err := os.ReadFile(filepath.Join(block, "meta.json"))
	if err != nil {
		return err
	}
	var meta struct {
		ULID   string `json:"ulid"`
		Thanos struct {
			Labels map[string]string `json:"labels"`
		} `json:"thanos"`
	}
	if err = json.Unmarshal(data, &meta); err != nil {
		return err
	}
	if len(meta.Thanos.Labels) == 0 && !sourceOnly {
		return errors.New("external Thanos context is absent; must be established independently before Query validation")
	}
	if sourceOnly {
		meta.Thanos.Labels = nil
	}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	native, err := tsdb.OpenBlock(logger, block, nil, nil)
	if err != nil {
		return err
	}
	defer native.Close()
	querier, err := tsdb.NewBlockQuerier(native, math.MinInt64, math.MaxInt64)
	if err != nil {
		return err
	}
	defer querier.Close()
	set := querier.Select(context.Background(), true, nil, labels.MustNewMatcher(labels.MatchRegexp, "__name__", "node_uname_info|node_memory_MemTotal_bytes|node_boot_time_seconds"))
	seen := map[string]bool{}
	var out []anchor
	for set.Next() {
		series := set.At()
		ls := series.Labels()
		name := ls.Get("__name__")
		if seen[name] {
			continue
		}
		it := series.Iterator(nil)
		for typ := it.Next(); typ != chunkenc.ValNone; typ = it.Next() {
			if typ != chunkenc.ValFloat {
				return errors.New("native histogram is not a finite float anchor")
			}
			timestamp, value := it.At()
			if math.IsNaN(value) || math.IsInf(value, 0) {
				continue
			}
			expected := ls.Map()
			for key, v := range meta.Thanos.Labels {
				if old, ok := expected[key]; ok && old != v {
					return errors.New("external labels conflict with source series")
				}
				expected[key] = v
			}
			out = append(out, anchor{labels.FromMap(expected).String(), expected, timestamp, fmt.Sprintf("%016x", math.Float64bits(value))})
			seen[name] = true
			break
		}
		if err = it.Err(); err != nil {
			return err
		}
		if len(out) == 3 {
			break
		}
	}
	if err = set.Err(); err != nil {
		return err
	}
	if len(out) != 3 {
		return errors.New("expected three distinct finite source anchor families")
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{"block": meta.ULID, "anchors": out, "canonicalVerificationReplaced": false, "productionModified": false, "externalContextVerified": !sourceOnly})
}
func main() {
	block := flag.String("block", "", "isolated normalized native block")
	sourceOnly := flag.Bool("source-only", false, "extract ordinary labels only; does not establish missing external context")
	flag.Parse()
	if *block == "" {
		fmt.Fprintln(os.Stderr, "block required")
		os.Exit(1)
	}
	if err := runMode(*block, *sourceOnly); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
