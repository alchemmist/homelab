package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestMissingExternalContextIsNeverInvented(t *testing.T) {
	for _, meta := range []string{`{"ulid":"01M61PJFZ9Q86GRQ70N0M81NH3"}`, `{"thanos":{"labels":{}}}`} {
		root := t.TempDir()
		if err := os.WriteFile(filepath.Join(root, "meta.json"), []byte(meta), 0600); err != nil {
			t.Fatal(err)
		}
		if err := run(root); err == nil {
			t.Fatal("snapshot without external-label proof was accepted")
		}
	}
}
func TestMalformedMetadataFailsBeforeOpeningNativeChunks(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "meta.json"), []byte(`{"thanos":{"labels":{"prometheus":123}}}`), 0600); err != nil {
		t.Fatal(err)
	}
	if err := run(root); err == nil {
		t.Fatal("non-string external labels accepted")
	}
}
