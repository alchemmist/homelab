export PATH := $(CURDIR)/.quality-tools/bin:$(PATH)
export UV_LOCKED := 1
export PYTHONDONTWRITEBYTECODE := 1

check: graph ownership yaml python-scopes scripts-q000 deploy-i001 rustfs-return-types \
       javascript workflow shell docker ansible secrets dependencies tests-fast tests-medium \
       python manifests tests-cluster image-cves

setup:
	uv sync --locked
	uv run python -m ci.quality.install_tools
	uv run python -m ci.quality.install_collections

.PHONY: graph-generate graph-validate
graph-generate:
	uv run python -m ci.quality.graph generate

graph-validate:
	uv run python -m ci.quality.graph validate

graph:
	$(MAKE) graph-validate
	uv run python -m ci.quality.contracts
	uv run python -m ci.quality.strict_guard
	uv run python -m ci.quality.check_sim300
	uv run pytest -q tests/test_quality_python_policy.py

ownership:
	uv run python -m ci.check_infrastructure_contracts
	uv run python -m ci.check_source_pointers
	uv run python -m ci.check_operational_entrypoints
	uv run python -m ci.check_vendor_contracts
	uv run python -m ci.check_alert_graphs
	uv run python -m ci.check_failure_alerts
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
	uv run python -m ci.quality.check_yaml

python-scopes:
	uv run --locked python -m ci.quality.python_scopes

scripts-q000:
	uv run python -m ci.quality.check_q000_d300

deploy-i001:
	uv run python -m ci.quality.check_i001
	uv run python -m ci.quality.check_f401

rustfs-return-types:
	uv run python -m ci.quality.check_ann201

javascript:
	uv run python -m ci.quality.check_javascript

workflow:
	uv run python -m ci.quality.check_workflow

shell:
	uv run python -m ci.quality.check_shell

docker:
	uv run pytest -q tests/test_quality_source_admission.py -k docker
	uv run python -m ci.quality.check_docker

ansible:
	uv run python -m ci.quality.check_ansible

secrets:
	uv run python -m ci.quality.check_secrets

dependencies:
	uv run pytest -q tests/test_quality_dependency_coverage.py \
	  tests/test_quality_p56_56_node_lock.py
	uv run python -m ci.quality.check_dependencies
	uv run python -m ci.quality.npm_smoke

tests-fast:
	uv run python -m ci.quality.tests fast --isolate-network

tests-medium:
	uv run python -m ci.quality.tests medium --isolate-network

python:
	uv run python -m ci.quality.check_python

manifests:
	uv run python -m ci.quality.charts

tests-cluster:
	uv run python -m ci.quality.tests cluster

.PHONY: check setup graph ownership yaml python-scopes scripts-q000 deploy-i001 \
        rustfs-return-types javascript workflow shell docker ansible secrets dependencies \
        tests-fast tests-medium python manifests tests-cluster image-cves

image-cves:
	uv run python -m ci.quality.image_cves
