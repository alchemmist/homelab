package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
)

// These fields describe the physical object, not its source signal identity.
// Reusing their old values after native compaction can mislead Store readers.
var physicalThanosFields = []string{"files", "segment_files", "index_stats", "upload_time"}

func semanticThanos(raw json.RawMessage) (map[string]json.RawMessage, error) {
	if len(raw) == 0 {
		return nil, nil
	}
	var result map[string]json.RawMessage
	if err := json.Unmarshal(raw, &result); err != nil {
		return nil, err
	}
	if result == nil {
		return nil, errors.New("present Thanos metadata must be an object")
	}
	for _, key := range physicalThanosFields {
		delete(result, key)
	}
	return result, nil
}

func nativeInventory(block string) ([]map[string]any, []string, error) {
	entries, err := os.ReadDir(filepath.Join(block, "chunks"))
	if err != nil {
		return nil, nil, err
	}
	var files []map[string]any
	var segments []string
	for _, entry := range entries {
		seq, e := strconv.ParseUint(entry.Name(), 10, 32)
		if e != nil || seq == 0 || entry.Type()&os.ModeSymlink != 0 || entry.IsDir() {
			return nil, nil, errors.New("invalid native chunk segment")
		}
		stat, e := entry.Info()
		if e != nil {
			return nil, nil, e
		}
		if !stat.Mode().IsRegular() {
			return nil, nil, errors.New("nonregular native segment")
		}
		segments = append(segments, entry.Name())
		files = append(files, map[string]any{"rel_path": "chunks/" + entry.Name(), "size_bytes": stat.Size()})
	}
	if len(segments) == 0 {
		return nil, nil, errors.New("native block has no segments")
	}
	stat, err := os.Lstat(filepath.Join(block, "index"))
	if err != nil {
		return nil, nil, err
	}
	if !stat.Mode().IsRegular() {
		return nil, nil, errors.New("nonregular native index")
	}
	files = append(files, map[string]any{"rel_path": "index", "size_bytes": stat.Size()}, map[string]any{"rel_path": "meta.json"})
	return files, segments, nil
}

func decodeExactJSON(data []byte, value any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	if err := decoder.Decode(value); err != nil {
		return err
	}
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		return errors.New("trailing metadata JSON")
	}
	return nil
}

func equalJSON(a, b json.RawMessage) bool {
	var x, y any
	if len(a) > 0 {
		if decodeExactJSON(a, &x) != nil {
			return false
		}
	}
	if len(b) > 0 {
		if decodeExactJSON(b, &y) != nil {
			return false
		}
	}
	return reflect.DeepEqual(x, y)
}

func rewriteRestoredMetadata(manifest Manifest, block string) error {
	target, err := metadata(block)
	if err != nil {
		return err
	}
	for _, key := range []string{"minTime", "maxTime"} {
		if value, ok := manifest.SourceMeta[key]; ok {
			target[key] = value
		}
	}
	// Partial pilots must never claim that they cover all original ancestors.
	if manifest.CompleteSourceBlock {
		if value, ok := manifest.SourceMeta["compaction"]; ok {
			target["compaction"] = value
		}
	}
	if value, ok := manifest.SourceMeta["thanos"]; ok {
		tm, err := semanticThanos(value)
		if err != nil {
			return err
		}
		files, segments, err := nativeInventory(block)
		if err != nil {
			return err
		}
		tm["files"], err = json.Marshal(files)
		if err != nil {
			return err
		}
		tm["segment_files"], err = json.Marshal(segments)
		if err != nil {
			return err
		}
		target["thanos"], err = json.Marshal(tm)
		if err != nil {
			return err
		}
	} else {
		delete(target, "thanos")
	}
	encoded, err := json.Marshal(target)
	if err != nil {
		return err
	}
	tmp := filepath.Join(block, "meta.json.native-metadata.tmp")
	file, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return err
	}
	_, writeErr := file.Write(encoded)
	syncErr := file.Sync()
	closeErr := file.Close()
	if err = errors.Join(writeErr, syncErr, closeErr); err != nil {
		return err
	}
	return os.Rename(tmp, filepath.Join(block, "meta.json"))
}

func verifyRestoredMetadata(manifest Manifest, block string) error {
	target, err := metadata(block)
	if err != nil {
		return err
	}
	keys := []string{"minTime", "maxTime"}
	if manifest.CompleteSourceBlock {
		keys = append(keys, "compaction")
	}
	for _, key := range keys {
		if !equalJSON(manifest.SourceMeta[key], target[key]) {
			return fmt.Errorf("restored source %s differs", key)
		}
	}
	originalThanos, err := semanticThanos(manifest.SourceMeta["thanos"])
	if err != nil {
		return err
	}
	targetThanos, err := semanticThanos(target["thanos"])
	if err != nil {
		return err
	}
	a, _ := json.Marshal(originalThanos)
	b, _ := json.Marshal(targetThanos)
	if !equalJSON(a, b) {
		return errors.New("restored semantic Thanos metadata differs from source")
	}
	if len(manifest.SourceMeta["thanos"]) > 0 {
		var actual map[string]json.RawMessage
		if err = json.Unmarshal(target["thanos"], &actual); err != nil {
			return err
		}
		files, segments, err := nativeInventory(block)
		if err != nil {
			return err
		}
		f, _ := json.Marshal(files)
		s, _ := json.Marshal(segments)
		if !equalJSON(f, actual["files"]) || !equalJSON(s, actual["segment_files"]) {
			return errors.New("restored physical Thanos file inventory differs from actual native files")
		}
		for _, key := range []string{"index_stats", "upload_time"} {
			if _, exists := actual[key]; exists {
				return errors.New("stale physical Thanos metadata must not be inherited")
			}
		}
	}
	var stats struct {
		Samples uint64 `json:"numSamples"`
	}
	if err = json.Unmarshal(target["stats"], &stats); err != nil {
		return err
	}
	if stats.Samples != manifest.Samples {
		return errors.New("native block sample stats differ from source canonical sample count")
	}
	return nil
}

// Normalize already completed legacy-worker output only by making a separate
// private copy. Never mutate a coordinator-owned directory or a served block.
func normalizeNativeMetadata(source, block, output string) error {
	sourcePath, err := filepath.EvalSymlinks(block)
	if err != nil {
		return err
	}
	parent, err := filepath.EvalSymlinks(filepath.Dir(output))
	if err != nil {
		return err
	}
	outputPath := filepath.Join(parent, filepath.Base(output))
	if outputPath == sourcePath || strings.HasPrefix(outputPath, sourcePath+string(os.PathSeparator)) {
		return errors.New("normalized output must be separate from preserved legacy block")
	}
	manifest, err := loadManifest(source)
	if err != nil {
		return err
	}
	before, err := metadata(block)
	if err != nil {
		return err
	}
	for _, key := range []string{"minTime", "maxTime"} {
		if !equalJSON(manifest.SourceMeta[key], before[key]) {
			return errors.New("legacy block source bounds changed")
		}
	}
	original, err := semanticThanos(manifest.SourceMeta["thanos"])
	if err != nil {
		return err
	}
	existing, err := semanticThanos(before["thanos"])
	if err != nil {
		return err
	}
	a, _ := json.Marshal(original)
	b, _ := json.Marshal(existing)
	if !equalJSON(a, b) {
		return errors.New("legacy block semantic labels/context changed")
	}
	count, digest, err := walkSelected(block, nil, manifest.MetricSelection)
	if err != nil {
		return err
	}
	if count != manifest.Samples || digest != manifest.CanonicalSHA256 {
		return errors.New("legacy block no longer matches canonical source")
	}
	var id string
	if err = json.Unmarshal(before["ulid"], &id); err != nil {
		return err
	}
	if len(id) != 26 || filepath.Base(id) != id {
		return errors.New("invalid restored block identity")
	}
	var bytes uint64
	err = filepath.WalkDir(block, func(path string, e os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if e.Type()&os.ModeSymlink != 0 {
			return errors.New("symlink in legacy block")
		}
		if e.IsDir() {
			return nil
		}
		stat, e2 := e.Info()
		if e2 != nil {
			return e2
		}
		if !stat.Mode().IsRegular() {
			return errors.New("nonregular legacy block file")
		}
		bytes += uint64(stat.Size())
		return nil
	})
	if err != nil {
		return err
	}
	if err = newOutput(output); err != nil {
		return err
	}
	if err = requireImportSpace(output, bytes); err != nil {
		return err
	}
	destination := filepath.Join(output, id)
	if err = os.Mkdir(destination, 0700); err != nil {
		return err
	}
	err = filepath.WalkDir(block, func(path string, e os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		rel, e2 := filepath.Rel(block, path)
		if e2 != nil {
			return e2
		}
		if rel == "." {
			return nil
		}
		target := filepath.Join(destination, rel)
		if e.IsDir() {
			return os.Mkdir(target, 0700)
		}
		if !e.Type().IsRegular() {
			return errors.New("legacy block changed type during copy")
		}
		in, e2 := os.Open(path)
		if e2 != nil {
			return e2
		}
		out, e2 := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if e2 != nil {
			in.Close()
			return e2
		}
		_, e2 = io.Copy(out, in)
		return errors.Join(e2, out.Close(), in.Close())
	})
	if err != nil {
		return err
	}
	if err = rewriteRestoredMetadata(manifest, destination); err != nil {
		return err
	}
	if err = verifyBlock(source, destination); err != nil {
		return err
	}
	return writeJSON(filepath.Join(output, "verification.json"), map[string]any{"verified": true, "block": id, "samples": count, "canonicalSHA256": digest, "nativePhysicalMetadataVerified": true, "sourceTimeBoundsAndThanosSemanticsVerified": true, "sourceAncestryPreserved": manifest.CompleteSourceBlock, "completeSourceBlock": manifest.CompleteSourceBlock, "originalOutputModified": false, "productionModified": false})
}
