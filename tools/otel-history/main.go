package main

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"math"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"

	"github.com/prometheus/prometheus/model/labels"
	"github.com/prometheus/prometheus/storage"
	"github.com/prometheus/prometheus/tsdb"
	"github.com/prometheus/prometheus/tsdb/chunkenc"
	collector "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	common "go.opentelemetry.io/proto/otlp/common/v1"
	metrics "go.opentelemetry.io/proto/otlp/metrics/v1"
)

var logger = slog.New(slog.NewTextHandler(io.Discard, nil))

const staleNaN = uint64(0x7ff0000000000002)
const batchSize = 5000

type Manifest struct {
	StaleMarkers        uint64                     `json:"staleMarkers"`
	MetricSelection     string                     `json:"metricSelection,omitempty"`
	CompleteSourceBlock bool                       `json:"completeSourceBlock"`
	Version             int                        `json:"schemaVersion"`
	Encoding            string                     `json:"encoding"`
	SourceMeta          map[string]json.RawMessage `json:"sourceMeta"`
	Files               map[string]string          `json:"files"`
	Samples             uint64                     `json:"samples"`
	CanonicalSHA256     string                     `json:"canonicalSHA256"`
}

func writeJSON(path string, value any) error {
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	defer file.Close()
	_, err = file.Write(append(data, '\n'))
	return err
}

func newOutput(path string) error {
	absolute, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	parent, err := filepath.EvalSymlinks(filepath.Dir(absolute))
	if err != nil {
		return err
	}
	for _, forbidden := range []string{"/var/lib", "/private/var/lib", "/host", "/etc", "/private/etc", "/srv"} {
		if parent == forbidden || strings.HasPrefix(parent, forbidden+"/") {
			return errors.New("production output paths are forbidden")
		}
	}
	return os.Mkdir(absolute, 0700)
}

func metadata(path string) (map[string]json.RawMessage, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if info.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("symlinked source blocks are forbidden")
	}
	data, err := os.ReadFile(filepath.Join(path, "meta.json"))
	if err != nil {
		return nil, err
	}
	var meta map[string]json.RawMessage
	if err = json.Unmarshal(data, &meta); err != nil {
		return nil, err
	}
	var thanos struct {
		Downsample struct {
			Resolution int64 `json:"resolution"`
		} `json:"downsample"`
	}
	if raw, ok := meta["thanos"]; ok {
		if err = json.Unmarshal(raw, &thanos); err != nil {
			return nil, err
		}
	}
	if thanos.Downsample.Resolution != 0 {
		return nil, errors.New("downsampled blocks remain native; OTLP export refused")
	}
	return meta, nil
}

func walk(path string, visit func(labels.Labels, int64, float64) error) (uint64, string, error) {
	return walkSelected(path, visit, "")
}

func walkSelected(path string, visit func(labels.Labels, int64, float64) error, selection string) (uint64, string, error) {
	block, err := tsdb.OpenBlock(logger, path, nil, nil)
	if err != nil {
		return 0, "", err
	}
	defer block.Close()
	querier, err := tsdb.NewBlockQuerier(block, math.MinInt64, math.MaxInt64)
	if err != nil {
		return 0, "", err
	}
	defer querier.Close()
	matcher := labels.MustNewMatcher(labels.MatchRegexp, "__name__", ".+")
	if selection != "" {
		matcher = labels.MustNewMatcher(labels.MatchEqual, "__name__", selection)
	}
	set := querier.Select(context.Background(), true, nil, matcher)
	digest := newCanonicalStream()
	defer digest.close()
	var count uint64
	var iterator chunkenc.Iterator
	var sampleBytes [16]byte
	for set.Next() {
		series := set.At()
		lset := series.Labels()
		text := lset.String()
		prefix := make([]byte, 8+len(text))
		binary.LittleEndian.PutUint64(prefix[:8], uint64(len(text)))
		copy(prefix[8:], text)
		iterator = series.Iterator(iterator)
		for typ := iterator.Next(); typ != chunkenc.ValNone; typ = iterator.Next() {
			if typ != chunkenc.ValFloat {
				return count, "", errors.New("native histogram samples require native preservation")
			}
			timestamp, value := iterator.At()
			if timestamp < 0 || timestamp > math.MaxInt64/1000000 {
				return count, "", errors.New("timestamp cannot be represented by standard OTLP")
			}
			addSampleHash(digest, prefix, sampleBytes[:], timestamp, value)
			if visit != nil {
				if err = visit(lset, timestamp, value); err != nil {
					return count, "", err
				}
			}
			count++
		}
		if err = iterator.Err(); err != nil {
			return count, "", err
		}
	}
	if err = set.Err(); err != nil {
		return count, "", err
	}
	return count, digest.close(), nil
}

func addSampleHash(digest io.Writer, prefix, buffer []byte, timestamp int64, value float64) {
	digest.Write(prefix)
	binary.LittleEndian.PutUint64(buffer[:8], uint64(timestamp))
	binary.LittleEndian.PutUint64(buffer[8:], math.Float64bits(value))
	digest.Write(buffer)
}

func fileHash(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	digest := sha256.New()
	if _, err = io.Copy(digest, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(digest.Sum(nil)), nil
}

func exportBlock(source, output string, maxBytes int64, selections ...string) error {
	selection := ""
	if len(selections) > 0 {
		selection = selections[0]
	}
	return exportWithResume(source, output, maxBytes, selection, false)
}

func exportWithResume(source, output string, maxBytes int64, selection string, resume bool, parallelism ...int) error {
	if maxBytes <= 0 {
		return errors.New("max-bytes must be positive")
	}
	meta, err := metadata(source)
	if err != nil {
		return err
	}
	if err = newOutput(output); err != nil {
		if !resume || !errors.Is(err, os.ErrExist) {
			return err
		}
		info, statErr := os.Lstat(output)
		if statErr != nil {
			return statErr
		}
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || info.Mode().Perm()&0077 != 0 {
			return errors.New("resume requires a private nonsymlinked output directory")
		}
		if _, statErr = os.Stat(filepath.Join(output, "manifest.json")); !errors.Is(statErr, os.ErrNotExist) {
			return errors.New("completed exports cannot be resumed or overwritten")
		}
	}
	manifest := Manifest{MetricSelection: selection, CompleteSourceBlock: selection == "", Version: 1, Encoding: "standard-otlp-untyped-gauge", SourceMeta: meta, Files: map[string]string{}}
	request := &collector.ExportMetricsServiceRequest{ResourceMetrics: []*metrics.ResourceMetrics{{ScopeMetrics: []*metrics.ScopeMetrics{{}}}}}
	scope := request.ResourceMetrics[0].ScopeMetrics[0]
	gauges := map[string]*metrics.Gauge{}
	points := 0
	workers := 1
	if len(parallelism) > 0 {
		workers = parallelism[0]
	}
	writer, err := newParallelExport(output, maxBytes, resume, workers)
	if err != nil {
		return err
	}
	defer writer.close()
	flush := func() error {
		if points == 0 {
			return nil
		}
		if err := writer.submit(request); err != nil {
			return err
		}
		// Ownership of this immutable batch passes to exactly one worker.
		request = &collector.ExportMetricsServiceRequest{ResourceMetrics: []*metrics.ResourceMetrics{{ScopeMetrics: []*metrics.ScopeMetrics{{}}}}}
		scope = request.ResourceMetrics[0].ScopeMetrics[0]
		gauges = map[string]*metrics.Gauge{}
		points = 0
		return nil
	}
	var cachedLabels labels.Labels
	var attrs []*common.KeyValue
	var name string
	count, digest, err := walkSelected(source, func(lset labels.Labels, timestamp int64, value float64) error {
		if !labels.Equal(cachedLabels, lset) {
			cachedLabels = lset.Copy()
			name = cachedLabels.Get("__name__")
			if name == "" {
				return errors.New("metric name is missing")
			}
			attrs = nil
			cachedLabels.Range(func(label labels.Label) {
				if label.Name != "__name__" {
					attrs = append(attrs, &common.KeyValue{Key: label.Name, Value: &common.AnyValue{Value: &common.AnyValue_StringValue{StringValue: label.Value}}})
				}
			})
		}
		point := &metrics.NumberDataPoint{Attributes: attrs, TimeUnixNano: uint64(timestamp) * 1000000, Value: &metrics.NumberDataPoint_AsDouble{AsDouble: value}}
		if math.Float64bits(value) == staleNaN {
			manifest.StaleMarkers++
			point.Flags = uint32(metrics.DataPointFlags_DATA_POINT_FLAGS_NO_RECORDED_VALUE_MASK)
			point.Value = &metrics.NumberDataPoint_AsDouble{AsDouble: 0}
		}
		gauge := gauges[name]
		if gauge == nil {
			gauge = &metrics.Gauge{}
			gauges[name] = gauge
			scope.Metrics = append(scope.Metrics, &metrics.Metric{Name: name, Data: &metrics.Metric_Gauge{Gauge: gauge}})
		}
		gauge.DataPoints = append(gauge.DataPoints, point)
		points++
		if points >= batchSize {
			return flush()
		}
		return nil
	}, selection)
	if err != nil {
		return err
	}
	if err = flush(); err != nil {
		return err
	}
	if err = writer.close(); err != nil {
		return err
	}
	manifest.Files = writer.files
	entries, err := os.ReadDir(output)
	if err != nil {
		return err
	}
	for _, entry := range entries {
		if strings.HasSuffix(entry.Name(), ".otlp.pb.gz") {
			if _, exists := manifest.Files[entry.Name()]; !exists {
				return errors.New("unreferenced batch in output; preserve and inspect partial output")
			}
		}
	}
	manifest.Samples, manifest.CanonicalSHA256 = count, digest
	return writeJSON(filepath.Join(output, "manifest.json"), manifest)
}

func loadManifest(source string) (Manifest, error) {
	return loadManifestWithWorkers(source, min(runtime.GOMAXPROCS(0), 16))
}

func loadManifestWithWorkers(source string, workers int) (Manifest, error) {
	var manifest Manifest
	data, err := os.ReadFile(filepath.Join(source, "manifest.json"))
	if err != nil {
		return manifest, err
	}
	if err = json.Unmarshal(data, &manifest); err != nil {
		return manifest, err
	}
	if manifest.Version != 1 || manifest.Encoding != "standard-otlp-untyped-gauge" || manifest.Samples == 0 || len(manifest.Files) == 0 {
		return manifest, errors.New("unsupported or empty export manifest")
	}
	if manifest.CompleteSourceBlock != (manifest.MetricSelection == "") {
		return manifest, errors.New("inconsistent metric selection manifest")
	}
	if err = verifyManifestFiles(source, manifest.Files, workers); err != nil {
		return manifest, err
	}
	return manifest, nil
}

func orderedFiles(files map[string]string) ([]string, error) {
	type indexed struct {
		name  string
		index uint64
	}
	entries := make([]indexed, 0, len(files))
	seen := map[uint64]bool{}
	for name := range files {
		stem := strings.TrimSuffix(name, ".otlp.pb.gz")
		index, err := strconv.ParseUint(stem, 10, 64)
		if err != nil || stem == name || seen[index] {
			return nil, errors.New("invalid or duplicate numeric batch sequence")
		}
		seen[index] = true
		entries = append(entries, indexed{name, index})
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].index < entries[j].index })
	result := make([]string, 0, len(entries))
	for _, entry := range entries {
		result = append(result, entry.name)
	}
	return result, nil
}

func importBlock(source, output string) error {
	return importBlockWithShardSize(source, output, importShardSamples)
}

func importBlockWithShardSize(source, output string, shardSamples uint64, cacheOption ...bool) error {
	cacheSeries := len(cacheOption) == 0 || cacheOption[0]
	if shardSamples == 0 {
		return errors.New("import shard sample limit must be positive")
	}
	return importBlockWithOptions(source, output, shardSamples, cacheSeries, 1)
}

func importBlockWithOptions(source, output string, shardSamples uint64, cacheSeries bool, workers int, resumePath ...string) error {
	if shardSamples == 0 {
		return errors.New("import shard sample limit must be positive")
	}
	manifest, err := loadManifestWithWorkers(source, workers)
	if err != nil {
		return err
	}
	if err = newOutput(output); err != nil {
		return err
	}
	var sourceMin, sourceMax int64
	if err = json.Unmarshal(manifest.SourceMeta["minTime"], &sourceMin); err != nil {
		return err
	}
	if err = json.Unmarshal(manifest.SourceMeta["maxTime"], &sourceMax); err != nil {
		return err
	}
	if sourceMin < 0 || sourceMax <= sourceMin || sourceMax-sourceMin >= math.MaxInt64/2-1 {
		return errors.New("invalid source time bounds")
	}
	writer, err := newBoundedBlockWriter(output, 2*(sourceMax-sourceMin+1), shardSamples)
	if err != nil {
		return err
	}
	defer writer.Close()
	writer.compactWorkers = min(workers, 4)
	files, err := orderedFiles(manifest.Files)
	if err != nil {
		return err
	}
	var count uint64
	var staleCount uint64
	startFile := 0
	if len(resumePath) > 0 && resumePath[0] != "" {
		proof, err := loadImportPrefix(resumePath[0], source)
		if err != nil {
			return err
		}
		if proof.Samples > manifest.Samples || proof.Files > len(files) {
			return errors.New("resume prefix exceeds manifest")
		}
		count, staleCount, startFile = proof.Samples, proof.StaleMarkers, proof.Files
		writer.total = count
		for _, shard := range proof.Shards {
			writer.blocks = append(writer.blocks, shard.Directory)
		}
		fmt.Fprintf(os.Stderr, "verified native prefix adopted: shards=%d samples=%d remainingBatches=%d\n", len(proof.Shards), count, len(files)-startFile)
	}
	files = files[startFile:]
	prefetch, err := newImportPrefetch(source, files, workers)
	if err != nil {
		return err
	}
	defer prefetch.close()
	for index := range files {
		batch, err := prefetch.next(index)
		if err != nil {
			return err
		}
		request := batch.request
		pointsInBatch := 0
		for _, resource := range request.ResourceMetrics {
			for _, scope := range resource.ScopeMetrics {
				for _, metric := range scope.Metrics {
					pointsInBatch += len(metric.GetGauge().GetDataPoints())
					if pointsInBatch > batchSize {
						return errors.New("OTLP batch exceeds the exported point limit")
					}
				}
			}
		}
		if pointsInBatch == 0 {
			return errors.New("empty OTLP data batch")
		}
		appender, err := writer.Appender(context.Background())
		if err != nil {
			return err
		}
		beforeBatch := count
		var cachedAttrs []*common.KeyValue
		var cachedMetric string
		var cachedSet labels.Labels
		var cachedRef storage.SeriesRef
		for _, resource := range request.ResourceMetrics {
			if resource.Resource != nil && len(resource.Resource.Attributes) != 0 {
				appender.Rollback()
				return errors.New("unexpected resource attributes")
			}
			for _, scope := range resource.ScopeMetrics {
				for _, metric := range scope.Metrics {
					if metric.GetGauge() == nil || metric.Name == "" {
						appender.Rollback()
						return errors.New("unexpected OTLP metric type")
					}
					for _, point := range metric.GetGauge().DataPoints {
						if point.TimeUnixNano%1000000 != 0 || point.TimeUnixNano/1000000 > math.MaxInt64 || point.Flags & ^uint32(metrics.DataPointFlags_DATA_POINT_FLAGS_NO_RECORDED_VALUE_MASK) != 0 || point.StartTimeUnixNano != 0 {
							appender.Rollback()
							return errors.New("unexpected OTLP point semantics")
						}
						timestamp := int64(point.TimeUnixNano / 1000000)
						if timestamp < sourceMin || timestamp >= sourceMax {
							appender.Rollback()
							return errors.New("point is outside source time bounds")
						}
						value, ok := point.Value.(*metrics.NumberDataPoint_AsDouble)
						if !ok {
							appender.Rollback()
							return errors.New("expected a double data point")
						}
						if !cacheSeries || cachedMetric != metric.Name || !sameStringAttributes(cachedAttrs, point.Attributes) {
							attrs := map[string]string{"__name__": metric.Name}
							for _, attr := range point.Attributes {
								if attr == nil || attr.Value == nil {
									appender.Rollback()
									return errors.New("nil OTLP label")
								}
								if _, exists := attrs[attr.Key]; exists {
									appender.Rollback()
									return errors.New("duplicate attribute")
								}
								str, ok := attr.Value.Value.(*common.AnyValue_StringValue)
								if !ok {
									appender.Rollback()
									return errors.New("expected string labels")
								}
								attrs[attr.Key] = str.StringValue
							}
							cachedSet = labels.FromMap(attrs)
							cachedMetric, cachedAttrs, cachedRef = metric.Name, point.Attributes, 0
						}
						sample := value.AsDouble
						if point.Flags&uint32(metrics.DataPointFlags_DATA_POINT_FLAGS_NO_RECORDED_VALUE_MASK) != 0 {
							staleCount++
							sample = math.Float64frombits(staleNaN)
						}
						cachedRef, err = appender.Append(cachedRef, cachedSet, timestamp, sample)
						if err != nil {
							appender.Rollback()
							return err
						}
						count++
					}
				}
			}
		}
		if err = appender.Commit(); err != nil {
			return err
		}
		if err = writer.CommitBatch(count-beforeBatch, uint64(batch.bytes)); err != nil {
			return err
		}
	}
	if count != manifest.Samples || staleCount != manifest.StaleMarkers {
		return errors.New("sample count differs from manifest")
	}
	blockPath, err := writer.Finish()
	if err != nil {
		return err
	}
	if err = rewriteRestoredMetadata(manifest, blockPath); err != nil {
		return err
	}
	if err = verifyBlock(source, blockPath); err != nil {
		return err
	}
	return writeJSON(filepath.Join(output, "verification.json"), map[string]any{"verified": true, "samples": count, "canonicalSHA256": manifest.CanonicalSHA256, "block": filepath.Base(blockPath), "productionModified": false, "staleMarkers": staleCount, "metricSelection": manifest.MetricSelection, "completeSourceBlock": manifest.CompleteSourceBlock})
}

func verifyBlock(source, block string) error {
	manifest, err := loadManifest(source)
	if err != nil {
		return err
	}
	if err = verifyRestoredMetadata(manifest, block); err != nil {
		return err
	}
	count, digest, err := walkSelected(block, nil, manifest.MetricSelection)
	if err != nil {
		return err
	}
	if count != manifest.Samples || digest != manifest.CanonicalSHA256 {
		return errors.New("canonical sample verification failed")
	}
	return nil
}

func run(args []string) error {
	if len(args) == 0 {
		return errors.New("expected inventory, export, import or verify")
	}
	flags := flag.NewFlagSet(args[0], flag.ContinueOnError)
	source := flags.String("source", "", "read-only source block or completed OTLP export")
	output := flags.String("output", "", "new isolated output directory")
	block := flags.String("block", "", "restored block for verification")
	selection := flags.String("metric", "", "optional isolated pilot metric; does not export the complete source block")
	resume := flags.Bool("resume", false, "verify and reuse every matching incomplete export batch")
	resumeImport := flags.String("resume-import-proof", "", "exact verified immutable native prefix proof; never trust unverified shard counts")
	showWorkers := flags.Bool("show-export-workers", false, "report effective export workers without reading or exporting samples")
	workers := flags.Int("export-workers", 1, "bounded parallel OTLP encode/compress workers (1..50)")
	maxBytes := flags.Int64("max-bytes", 4*1024*1024*1024, "compressed export byte budget")
	approvalPath := flags.String("loss-approval", "", "explicit approval for one identified corrupt chunk; recovery only")
	if err := flags.Parse(args[1:]); err != nil {
		return err
	}
	if *source == "" {
		return errors.New("source is required")
	}
	switch args[0] {
	case "recover-chunk":
		if *output == "" || *approvalPath == "" {
			return errors.New("output and loss-approval are required")
		}
		data, err := os.ReadFile(*approvalPath)
		if err != nil {
			return err
		}
		var approval LossApproval
		if err = json.Unmarshal(data, &approval); err != nil {
			return err
		}
		return recoverApprovedChunk(*source, *output, approval)
	case "normalize-native-metadata":
		if *block == "" || *output == "" {
			return errors.New("block and new output are required")
		}
		return normalizeNativeMetadata(*source, *block, *output)
	case "capabilities":
		report, err := capabilities(*source)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(report)
	case "inventory":
		meta, err := metadata(*source)
		if err != nil {
			return err
		}
		count, digest, err := walkSelected(*source, nil, *selection)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(map[string]any{"samples": count, "canonicalSHA256": digest, "sourceMeta": meta})
	case "export":
		if *output == "" && !*showWorkers {
			return errors.New("output is required")
		}
		effective, err := effectiveExportWorkers(*workers, *source)
		if err != nil {
			return err
		}
		if target := min(effective, 16); target > runtime.GOMAXPROCS(0) {
			runtime.GOMAXPROCS(target)
		}
		if *showWorkers {
			return json.NewEncoder(os.Stdout).Encode(map[string]any{"effectiveExportWorkers": effective, "gomaxprocs": runtime.GOMAXPROCS(0), "samplesRead": false, "exportStarted": false})
		}
		return exportWithResume(*source, *output, *maxBytes, *selection, *resume, effective)
	case "verify-import-prefix":
		if *block == "" || *output == "" {
			return errors.New("previous import and exclusive proof output required")
		}
		proof, err := proveImportPrefix(*source, *block, 8)
		if err != nil {
			return err
		}
		data, err := json.MarshalIndent(proof, "", "  ")
		if err != nil {
			return err
		}
		file, err := os.OpenFile(*output, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if err != nil {
			return err
		}
		_, err = file.Write(data)
		if err == nil {
			err = file.Sync()
		}
		return errors.Join(err, file.Close())
	case "import":
		if *output == "" {
			return errors.New("output is required")
		}
		return importBlockWithOptions(*source, *output, importShardSamples, true, min(runtime.GOMAXPROCS(0), 16), *resumeImport)
	case "verify":
		if *block == "" {
			return errors.New("block is required")
		}
		return verifyBlock(*source, *block)
	default:
		return errors.New("unknown command")
	}
}

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
