package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"sort"
	"time"

	"github.com/prometheus/prometheus/model/labels"
	"github.com/prometheus/prometheus/model/textparse"
)

type sample struct {
	Name  string
	Value float64
}
type scrape struct {
	Series map[string]sample
	Types  map[string]string
	Help   map[string]string
}

func parse(data []byte) (scrape, error) {
	out := scrape{Series: map[string]sample{}, Types: map[string]string{}, Help: map[string]string{}}
	parser := textparse.NewPromParser(data, labels.NewSymbolTable(), false)
	for {
		entry, err := parser.Next()
		if err == io.EOF {
			return out, nil
		}
		if err != nil {
			return out, err
		}
		switch entry {
		case textparse.EntryType:
			name, kind := parser.Type()
			out.Types[string(name)] = string(kind)
		case textparse.EntryHelp:
			name, help := parser.Help()
			out.Help[string(name)] = string(help)
		case textparse.EntrySeries:
			var ls labels.Labels
			parser.Labels(&ls)
			key := ls.String()
			if _, exists := out.Series[key]; exists {
				return out, errors.New("duplicate complete source label set")
			}
			_, ts, value := parser.Series()
			if ts != nil {
				return out, errors.New("unexpected source timestamp")
			}
			out.Series[key] = sample{Name: ls.Get("__name__"), Value: value}
		default:
			return out, fmt.Errorf("unsupported source exposition entry %d", entry)
		}
	}
}
func fetch(url string) (scrape, error) {
	client := http.Client{Timeout: 4 * time.Second}
	request, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return scrape{}, err
	}
	request.Header.Set("Accept", "text/plain;version=0.0.4")
	response, err := client.Do(request)
	if err != nil {
		return scrape{}, err
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return scrape{}, fmt.Errorf("source HTTP status %d", response.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, 16*1024*1024+1))
	if err != nil {
		return scrape{}, err
	}
	if len(data) > 16*1024*1024 {
		return scrape{}, errors.New("source scrape exceeds bound")
	}
	return parse(data)
}
func sameNumber(a, b float64) bool { return math.Float64bits(a) == math.Float64bits(b) }

var constantMetrics = map[string]bool{"node_exporter_build_info": true, "node_boot_time_seconds": true, "node_uname_info": true, "node_os_info": true, "node_dmi_info": true, "node_cpu_info": true, "node_memory_MemTotal_bytes": true, "node_memory_Hugepagesize_bytes": true, "node_memory_SwapTotal_bytes": true, "node_scrape_collector_success": true, "node_textfile_scrape_error": true, "node_textfile_mtime_seconds": true, "node_filesystem_readonly": true, "node_filesystem_device_error": true, "node_filesystem_size_bytes": true, "node_time_zone_offset_seconds": true}

func compare(before, candidate, after scrape) map[string]any {
	var missing, extra, types, help, values []map[string]string
	stable, volatile := 0, 0
	add := func(dst *[]map[string]string, key, name string) {
		hash := sha256.Sum256([]byte(key))
		*dst = append(*dst, map[string]string{"metric": name, "labelsSHA256": hex.EncodeToString(hash[:])})
	}
	for key, original := range before.Series {
		latest, present := after.Series[key]
		if !present {
			volatile++
			continue
		}
		stable++
		actual, present := candidate.Series[key]
		if !present {
			add(&missing, key, original.Name)
			continue
		}
		if constantMetrics[original.Name] && sameNumber(original.Value, latest.Value) && !sameNumber(original.Value, actual.Value) {
			add(&values, key, original.Name)
		}
	}
	for key, actual := range candidate.Series {
		if _, ok := before.Series[key]; !ok {
			if _, ok = after.Series[key]; !ok {
				add(&extra, key, actual.Name)
			}
		}
	}
	for key := range after.Series {
		if _, ok := before.Series[key]; !ok {
			volatile++
		}
	}
	for name, kind := range before.Types {
		if after.Types[name] != kind {
			continue
		}
		if candidate.Types[name] != kind {
			types = append(types, map[string]string{"metric": name, "expected": kind, "actual": candidate.Types[name]})
		}
	}
	for name, kind := range candidate.Types {
		if _, ok := before.Types[name]; !ok {
			if _, ok = after.Types[name]; !ok {
				types = append(types, map[string]string{"metric": name, "expected": "absent", "actual": kind})
			}
		}
	}
	for name, text := range before.Help {
		if after.Help[name] != text {
			continue
		}
		if candidate.Help[name] != text {
			help = append(help, map[string]string{"metric": name})
		}
	}
	for _, items := range [][]map[string]string{missing, extra, types, help, values} {
		sort.Slice(items, func(i, j int) bool {
			return items[i]["metric"]+items[i]["labelsSHA256"] < items[j]["metric"]+items[j]["labelsSHA256"]
		})
	}
	passed := stable > 0 && len(missing) == 0 && len(extra) == 0 && len(types) == 0 && len(help) == 0 && len(values) == 0
	return map[string]any{"schemaVersion": 1, "sourceCompatibilityPassed": passed, "stableLegacySeries": stable, "volatileLegacySeries": volatile, "candidateSeries": len(candidate.Series), "legacyFamilies": len(before.Types), "candidateFamilies": len(candidate.Types), "missingStableSeries": missing, "unexpectedCandidateSeries": extra, "typeDifferences": types, "helpDifferences": help, "stableConstantValueDifferences": values, "rawMetricBodiesPersisted": false, "ordinaryLabelsAndValuesRewritten": false, "productionIngestionChanged": false}
}
func run() error {
	legacy := flag.String("legacy-url", "", "loopback/private existing source URL")
	candidate := flag.String("candidate-url", "", "loopback candidate source URL")
	output := flag.String("output", "", "new private result")
	flag.Parse()
	if *legacy == "" || *candidate == "" || *output == "" {
		return errors.New("source URLs and output required")
	}
	before, err := fetch(*legacy)
	if err != nil {
		return err
	}
	actual, err := fetch(*candidate)
	if err != nil {
		return err
	}
	after, err := fetch(*legacy)
	if err != nil {
		return err
	}
	result := compare(before, actual, after)
	data, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		return err
	}
	f, err := os.OpenFile(*output, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	_, err = f.Write(append(data, '\n'))
	err = errors.Join(err, f.Close())
	if err != nil {
		return err
	}
	if result["sourceCompatibilityPassed"] != true {
		return errors.New("host source compatibility failed; see private counts/hash-only receipt")
	}
	return nil
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
