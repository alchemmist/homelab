"""Tests for the OpenTelemetry Open WebUI source profile."""

import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module() -> ModuleType:
    """Test behavior for module."""
    spec = importlib.util.spec_from_file_location(
        "webui_profile", ROOT / "scripts/otel-open-webui-source-profile.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def fixtures() -> tuple[
    list[str | dict[str, object]],
    SimpleNamespace,
    ModuleType,
    dict[str, ModuleType],
]:
    """Test behavior for fixtures."""
    calls: list[str | dict[str, object]] = []

    class Native:
        def __init__(self, app, db_engine) -> None:
            self.app = app
            self.db_engine = db_engine

    class Http:
        def instrument(self):
            calls.append("http")

        def uninstrument(self):
            calls.append("http-stop")

    class FastApi:
        @staticmethod
        def instrument_app(**kwargs) -> None:
            calls.append(kwargs)

        @staticmethod
        def uninstrument_app(app) -> None:
            calls.append("fastapi-stop")

    native = SimpleNamespace(
        Instrumentor=Native,
        FastAPIInstrumentor=FastApi,
        RequestsInstrumentor=Http,
        HTTPXClientInstrumentor=Http,
        AioHttpClientInstrumentor=Http,
    )
    sdk = ModuleType("opentelemetry.sdk.trace")
    sdk.TracerProvider = type("GuardedProvider", (), {"_homelab_source_privacy": True})
    telemetry = ModuleType("open_webui.utils.telemetry")
    telemetry.instrumentors = native
    modules = {
        "opentelemetry": ModuleType("opentelemetry"),
        "opentelemetry.sdk": ModuleType("opentelemetry.sdk"),
        "opentelemetry.sdk.trace": sdk,
        "open_webui": ModuleType("open_webui"),
        "open_webui.utils": ModuleType("open_webui.utils"),
        "open_webui.utils.telemetry": telemetry,
    }
    return calls, native, sdk, modules


class OpenWebuiProfileTests(unittest.TestCase):
    """Check the Open WebUI instrumentation source profile coverage."""

    def test_only_http_instrumentors_no_body_serializing_or_duplicate_signals(self) -> None:
        """Only http instrumentors no body serializing or duplicate signals."""
        calls, native, sdk, modules = fixtures()
        with patch.dict(sys.modules, modules):
            module().activate()
            profile = native.Instrumentor("app", "never-connected-db")
            profile._instrument()
            assert calls[0] == {
                "app": "app",
                "http_capture_headers_server_request": [],
                "http_capture_headers_server_response": [],
            }
            assert calls[1:] == ["http"] * 3
            profile._uninstrument()
            assert calls[-4:] == ["fastapi-stop"] + ["http-stop"] * 3

    def test_guard_and_before_setup_order_required_no_late_fallback(self) -> None:
        """Guard and before setup order required no late fallback."""
        calls, native, sdk, modules = fixtures()
        with patch.dict(sys.modules, modules):
            sdk.TracerProvider._homelab_source_privacy = False
            with self.assertRaises(ValueError):
                module().activate()
            sdk.TracerProvider._homelab_source_privacy = True
            with patch.dict(sys.modules, {"open_webui.utils.telemetry.setup": ModuleType("setup")}):
                with self.assertRaises(ValueError):
                    module().activate()
            assert calls == []
