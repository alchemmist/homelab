.DEFAULT_GOAL := help

MANIFEST := .quality-graph/manifest.json
NODES := $(shell jq -er '.nodes[].id' $(MANIFEST))
LOCAL_CHECKS := quality/local-checks.json
LOCAL_NODES := $(shell jq -er 'keys[]' $(LOCAL_CHECKS))
ifeq ($(strip $(NODES)),)
$(error Cannot list Quality Graph nodes; install jq and check $(MANIFEST))
endif
ifeq ($(strip $(LOCAL_NODES)),)
$(error Cannot list local checks; install jq and check $(LOCAL_CHECKS))
endif

export PATH := $(CURDIR)/.quality-tools/bin:$(PATH)
export UV_LOCKED := 1
# Imports during local checks must not add bytecode to vendored Helm charts.
export PYTHONDONTWRITEBYTECODE := 1

.PHONY: setup help check check-all $(NODES) $(LOCAL_NODES)
setup:
	uv sync --locked
	uv run python scripts/quality/install_tools.py
	uv run python scripts/quality/install_collections.py

help:
	@echo 'make check runs all local and CI checks; make <node> runs one. Active CI checks:'
	@jq -r '.nodes[] | "  \(.id)\t\(.title)"' $(MANIFEST)

	@echo 'Local only (included in make check): $(LOCAL_NODES)'

$(LOCAL_NODES):
	@cmd=$$(jq -er --arg id '$@' '.[$$id].run' $(LOCAL_CHECKS)) && printf '\n[%s]\n' '$@' && bash -eo pipefail -c "$$cmd"

check-all: check

# Keep going so an early lint failure does not hide the other local results.
check:
	$(MAKE) -k $(NODES) $(LOCAL_NODES)

$(NODES):
	@cmd=$$(jq -er --arg id '$@' '.nodes[] | select(.id == $$id) | .step.run' $(MANIFEST)) && \
		printf '\n[%s]\n%s\n' '$@' "$$cmd" && bash -eo pipefail -c "$$cmd"
