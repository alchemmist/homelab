.DEFAULT_GOAL := help

SHELL := /bin/bash

CI_CHECKS := graph ownership yaml python-scopes scripts-q000 deploy-i001 \
             rustfs-return-types javascript workflow shell docker ansible \
             secrets dependencies tests-fast tests-medium
LOCAL_ONLY := python manifests tests-cluster

export PATH := $(CURDIR)/.quality-tools/bin:$(PATH)
export UV_LOCKED := 1
export PYTHONDONTWRITEBYTECODE := 1

.PHONY: setup help check check-all $(CI_CHECKS) $(LOCAL_ONLY)
setup:
	uv sync --locked
	uv run python scripts/quality/install_tools.py
	uv run python scripts/quality/install_collections.py

help:
	@printf '%s\n' 'make setup: install locked tools' 'make check: run every check' \
	  'CI: $(CI_CHECKS)' 'Local only: $(LOCAL_ONLY)'

check-all: check

ifneq ($(filter check check-all,$(MAKECMDGOALS)),)
MAKEFLAGS += -k
endif
check: $(CI_CHECKS) $(LOCAL_ONLY)

graph:
	uv run qg validate
	uv run python scripts/quality/contracts.py
	uv run python scripts/quality/strict_guard.py
	set -o pipefail; uv run python -m scripts.quality.python_inputs scripts/quality/ | \
	  xargs -0 -r uv run ruff check --config quality/ruff.toml --select SIM300 \
	    --ignore-noqa --output-format concise --
	uv run pytest -q tests/test_quality_python_policy.py

ownership:
	uv run python scripts/check_infrastructure_contracts.py
	uv run python scripts/check_source_pointers.py
	uv run python scripts/check_operational_entrypoints.py
	uv run python scripts/check_vendor_contracts.py
	uv run python scripts/alert_graphs.py --check
	uv run python scripts/n8n/check_failure_alerts.py
	uv run python -m pytest -q \
	  tests/test_alert_graph_inventory.py \
	  tests/test_alert_graph_panel_ids.py \
	  tests/test_alert_graphs_chart.py \
	  tests/test_infrastructure_contracts.py \
	  tests/test_n8n_failure_alert_policy.py \
	  tests/test_n8n_failure_alerts.py \
	  tests/test_operational_entrypoints.py \
	  tests/test_source_pointers.py \
	  tests/test_vendor_contracts.py

yaml:
	uv run python scripts/quality/lint.py yaml

python-scopes:
	uv run --locked python -m scripts.quality.python_scopes

scripts-q000:
	set -o pipefail; uv run python -m scripts.quality.python_inputs scripts/ tests/ | \
	  xargs -0 -r uv run ruff check --config quality/ruff.toml --select Q000,D300 \
	    --ignore-noqa --output-format concise --

deploy-i001:
	set -o pipefail; uv run python -m scripts.quality.python_inputs ansible/ deploy/ scripts/ tests/ | \
	  xargs -0 -r uv run ruff check --config quality/ruff.toml --select I001 \
	    --ignore-noqa --output-format concise --
	set -o pipefail; uv run python -m scripts.quality.python_inputs scripts/ tests/ | \
	  xargs -0 -r uv run ruff check --config quality/ruff.toml --select F401 \
	    --ignore-noqa --output-format concise --

rustfs-return-types:
	uv run ruff check --config quality/ruff.toml --select ANN201 --ignore-noqa services/rustfs_gateway

javascript:
	uv run python scripts/quality/lint.py javascript

workflow:
	uv run python scripts/quality/lint.py workflow

shell:
	uv run python scripts/quality/lint.py shell

docker:
	uv run pytest -q tests/test_quality_experiment_admission.py -k docker
	uv run python scripts/quality/lint.py docker

ansible:
	uv run python scripts/quality/lint.py ansible

secrets:
	uv run python scripts/quality/lint.py secrets

dependencies:
	uv run pytest -q tests/test_quality_dependency_coverage.py \
	  tests/test_quality_p56_56_node_lock.py
	uv run python scripts/quality/lint.py dependencies
	uv run python scripts/quality/npm_smoke.py

tests-fast:
	uv run python scripts/quality/tests.py fast --isolate-network

tests-medium:
	uv run python scripts/quality/tests.py medium --isolate-network

python:
	uv run python scripts/quality/lint.py python

manifests:
	uv run python scripts/quality/charts.py

tests-cluster:
	uv run python scripts/quality/tests.py cluster
