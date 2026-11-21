.DEFAULT_GOAL := help

MANIFEST := .quality-graph/manifest.json
NODES := $(shell jq -er '.nodes[].id' $(MANIFEST))
ifeq ($(strip $(NODES)),)
$(error Cannot list Quality Graph nodes; install jq and check $(MANIFEST))
endif

export PATH := $(CURDIR)/.quality-tools/bin:$(PATH)
export UV_LOCKED := 1
# Imports during local checks must not add bytecode to vendored Helm charts.
export PYTHONDONTWRITEBYTECODE := 1

.PHONY: setup help check $(NODES)
setup:
	uv sync --locked
	uv run python scripts/quality/install_tools.py
	uv run python scripts/quality/install_collections.py

help:
	@echo 'make check runs all checks; make <node> runs one:'
	@jq -r '.nodes[] | "  \(.id)\t\(.title)"' $(MANIFEST)

# Keep going so an early lint failure does not hide the other local results.
check:
	$(MAKE) -k $(NODES)

$(NODES):
	@cmd=$$(jq -er --arg id '$@' '.nodes[] | select(.id == $$id) | .step.run' $(MANIFEST)) && \
		printf '\n[%s]\n%s\n' '$@' "$$cmd" && bash -eo pipefail -c "$$cmd"
