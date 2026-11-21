"""Tests for the OpenTelemetry application registry script."""

import importlib.util
import json
from pathlib import Path
import unittest
from typing import TypedDict

spec = importlib.util.spec_from_file_location(
    "application_registry",
    Path(__file__).resolve().parents[1] / "scripts/otel-application-registry.py",
)
registry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry)


class EnvVar(TypedDict):
    """Container environment entry the registry reports by name only."""

    name: str
    value: str


class Container(TypedDict):
    """Container of the workload template with non-secret fixtures."""

    name: str
    image: str
    env: list[EnvVar]
    args: list[str]


class Template(TypedDict):
    """Pod template of a workload."""

    metadata: dict[str, dict[str, str]]
    spec: dict[str, list[Container]]


class JobMetadata(TypedDict, total=False):
    """Job metadata with optional controller links."""

    namespace: str
    name: str
    ownerReferences: list[dict[str, str]]


class Job(TypedDict):
    """Standalone Job fixture describing template sharing."""

    kind: str
    metadata: JobMetadata
    spec: dict[str, object]


class Deployment(TypedDict):
    """Workload fixture with a single container and trace plumbing."""

    kind: str
    metadata: dict[str, str]
    spec: dict[str, Template]


class ApplicationRegistryTests(unittest.TestCase):
    """Validate the registered OpenTelemetry application deployments."""
    def deployment(self) -> Deployment:
        return {
            "kind": "Deployment",
            "metadata": {"name": "app", "namespace": "apps"},
            "spec": {
                "template": {
                    "metadata": {"annotations": {}},
                    "spec": {
                        "containers": [
                            {
                                "name": "app",
                                "image": "upstream:v1",
                                "env": [
                                    {
                                        "name": "OTEL_EXPORTER_OTLP_HEADERS",
                                        "value": "never-save-credential",
                                    },
                                    {
                                        "name": "PASSWORD",
                                        "value": "never-save-password",
                                    },
                                ],
                                "args": ["--tracing.endpoint=never-save-endpoint"],
                            }
                        ]
                    },
                }
            },
        }

    def test_no_environment_or_argument_values_saved(self) -> None:
        report = registry.summarize([self.deployment()])
        text = json.dumps(report)
        assert "never-save-" not in text
        source = report["sources"][0]
        assert source["configurationHintPresent"]
        assert not source["internalSdkTraceDeliveryVerified"]
        assert not report["internalSdkCoverageComplete"]

    def test_enable_otel_switch_is_only_a_hint_even_when_value_false(self) -> None:
        obj = self.deployment()
        obj["spec"]["template"]["spec"]["containers"][0]["env"] = [
            {"name": "ENABLE_OTEL_TRACES", "value": "False"}
        ]
        report = registry.summarize([obj])
        assert "ENABLE_OTEL_TRACES" in report["sources"][0]["tracingEnvironmentNames"]
        assert not report["sources"][0]["internalSdkTraceDeliveryVerified"]

    def test_owned_job_not_double_counted_but_standalone_job_included(self) -> None:
        obj = self.deployment()
        job: Job = {
            "kind": "Job",
            "metadata": {"namespace": "apps", "name": "once"},
            "spec": {"template": obj["spec"]["template"]},
        }
        assert registry.summarize([job])["sourceCount"] == 1
        job["metadata"]["ownerReferences"] = [{"kind": "CronJob", "name": "timer"}]
        assert registry.summarize([job])["sourceCount"] == 0

    def test_managed_pod_image_digest_retained_without_template_double_count(
        self,
    ) -> None:
        pod = {
            "kind": "Pod",
            "metadata": {
                "namespace": "apps",
                "name": "app-123",
                "ownerReferences": [{"kind": "ReplicaSet"}],
            },
            "spec": {},
            "status": {
                "phase": "Running",
                "containerStatuses": [
                    {"name": "app", "imageID": "upstream@sha256:abc", "ready": True}
                ],
            },
        }
        report = registry.summarize([self.deployment(), pod])
        assert report["sourceCount"] == 1
        assert report["podIncarnations"][0]["imageID"] == "upstream@sha256:abc"
        assert not report["podIncarnations"][0]["deliveryVerified"]
