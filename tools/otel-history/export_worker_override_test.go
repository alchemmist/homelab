package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestWorkerOverrideBoundOwnershipPermissionsAndSchema(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "workers.json")
	for _, data := range []string{`{"schemaVersion":1,"workers":50}`, `{"schemaVersion":1,"workers":16}`} {
		if err := os.WriteFile(path, []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
		workers, err := readWorkerOverride(path, uint32(os.Geteuid()))
		if err != nil || (workers != 16 && workers != 50) {
			t.Fatalf("valid override: %d %v", workers, err)
		}
	}
	for _, data := range []string{`{"schemaVersion":1,"workers":51}`, `{"schemaVersion":1,"workers":0}`, `{"schemaVersion":2,"workers":50}`, `{"schemaVersion":1,"workers":50,"other":1}`, `{"schemaVersion":1,"workers":50} {}`} {
		os.WriteFile(path, []byte(data), 0600)
		if _, err := readWorkerOverride(path, uint32(os.Geteuid())); err == nil {
			t.Fatal("invalid override accepted")
		}
	}
	os.WriteFile(path, []byte(`{"schemaVersion":1,"workers":50}`), 0600)
	os.Chmod(path, 0644)
	if _, err := readWorkerOverride(path, uint32(os.Geteuid())); err == nil {
		t.Fatal("public override accepted")
	}
	os.Chmod(path, 0600)
	if _, err := readWorkerOverride(path, uint32(os.Geteuid())+1); err == nil {
		t.Fatal("wrong owner accepted")
	}
	link := filepath.Join(dir, "link")
	if err := os.Symlink(path, link); err != nil {
		t.Fatal(err)
	}
	if _, err := readWorkerOverride(link, uint32(os.Geteuid())); err == nil {
		t.Fatal("symlink accepted")
	}
}
