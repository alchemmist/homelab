package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

const workerOverridePath = "/var/lib/homelab-otel-history/tail-roundtrip-20261101/export-worker-override.json"

// The optional protected operator override permits tuning later subprocesses
// without interrupting the active importer/controller. CPU/heap cgroups remain
// independent. Explicitly confined to the approved root-owned socrat-0 workspace.
func effectiveExportWorkers(requested int, source string) (int, error) {
	if requested < 1 || requested > 50 {
		return 0, errors.New("export-workers must be 1..50")
	}
	host, _ := os.Hostname()
	if host != "socrat-0" || os.Geteuid() != 0 {
		return requested, nil
	}
	absolute, err := filepath.Abs(source)
	if err != nil {
		return 0, err
	}
	rel, err := filepath.Rel("/home/alchemmist/otel-tail-roundtrip-work-20261101", absolute)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
		return requested, nil
	}
	workers, err := readWorkerOverride(workerOverridePath, 0)
	if errors.Is(err, os.ErrNotExist) {
		return requested, nil
	}
	if err != nil {
		return 0, err
	}
	fmt.Fprintf(os.Stderr, "export operator worker override: requested=%d effective=%d (CPU cgroup unchanged)\n", requested, workers)
	return workers, nil
}

func readWorkerOverride(path string, owner uint32) (int, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return 0, err
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || stat.Uid != owner || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > 1024 {
		return 0, errors.New("worker override must be private root-owned regular file <=1KiB")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return 0, err
	}
	var cfg struct {
		SchemaVersion int `json:"schemaVersion"`
		Workers       int `json:"workers"`
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err = decoder.Decode(&cfg); err != nil {
		return 0, err
	}
	var trailing any
	if err = decoder.Decode(&trailing); err != io.EOF {
		return 0, errors.New("trailing worker override data")
	}
	if cfg.SchemaVersion != 1 || cfg.Workers < 1 || cfg.Workers > 50 {
		return 0, errors.New("invalid worker override schema/bound")
	}
	return cfg.Workers, nil
}
