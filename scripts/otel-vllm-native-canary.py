"""CPU-only installed vLLM native request-span/HTTP-mTLS canary.

Never starts an engine or loads a model. Calls the installed OutputProcessor
request tracing method with synthetic CPU state. Not production vLLM coverage;
loading/decorator error-path privacy and renewable credentials remain gates.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import logging
import os
import ssl
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol

MARKERS = [
    "OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED",
    "OTEL_CANARY_PRIVATE_RESPONSE_MUST_NOT_BE_CAPTURED",
]


class RequestEmitter(Protocol):
    """Callable shape of the synthetic canary trace emitter."""

    def __call__(self) -> dict[str, str]:
        """Emit one canary trace against the installed OutputProcessor."""
        ...


class EndedSpan(Protocol):
    """Span shape the native-audit processor requires from the SDK."""

    name: str

    def to_json(self) -> str:
        """Render the span record the audit scan inspects for markers."""
        ...


class Flushable(Protocol):
    """Provider shape the canary requires for forced flushes."""

    def force_flush(self, timeout_millis: int = 0) -> bool:
        """Flush pending spans and report whether every exporter drained them."""
        ...


def audit_on_end(span: EndedSpan, audit: dict[str, int]) -> None:
    """Record ended span count, request-span presence and marker leakage."""
    audit["endedSpans"] += 1
    audit["nativeLlmRequestSpanSeen"] |= span.name == "llm_request"
    if any(marker in span.to_json() for marker in MARKERS):
        audit["sensitiveSyntheticContentFoundAtSource"] = True


def require_flush(provider: Flushable) -> None:
    """Fail unless the first synthetic batch flushes through the native SDK."""
    if not provider.force_flush(timeout_millis=10000):
        raise ValueError("Initial native SDK flush failed")


def require_http_protocol() -> None:
    """Fail unless the installed exporter selected the pinned HTTP protocol."""
    if os.environ.get("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL") != "http/protobuf":
        raise ValueError(
            "vLLM ignores generic protocol for this selector; insecure gRPC path forbidden"
        )


def require_fresh_handshakes(*, renewal: bool) -> None:
    """Fail when certificate renewal is requested without fresh HTTP handshakes."""
    if renewal and os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "").lower() != "connection=close":
        raise ValueError("Fresh native HTTP handshakes required")


def certificate_hash() -> str:
    """Return the current SHA-256 fingerprint of the mounted leaf certificate."""
    return hashlib.sha256(Path("/etc/otel-client/tls.crt").read_bytes()).hexdigest()


def progress(value: dict[str, object]) -> None:
    """Publish the current canary phase to the progress sidecar file."""
    path = Path("/run/otel-test/renewal-progress.json")
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


def await_leaf_renewal(
    *,
    before_hash: str,
    loaded: list[str],
    first: dict[str, str],
    emit_request: RequestEmitter,
) -> tuple[str, dict[str, str]]:
    """Wait for the rotated leaf certificate and capture a second trace through it."""
    if before_hash not in loaded:
        raise ValueError("Initial leaf was not loaded by native HTTP client")
    progress(
        {
            "phase": "await-renewal",
            "beforeCertificateSHA256": before_hash,
            "beforeTrace": first,
        }
    )
    deadline = time.monotonic() + 600
    while certificate_hash() == before_hash:
        if time.monotonic() >= deadline:
            raise ValueError("Projected leaf renewal deadline exceeded")
        time.sleep(2)
    return certificate_hash(), emit_request()


def leaf_reload_verified(
    *, renewal: bool, before_hash: str, after_hash: str, loaded: list[str]
) -> bool:
    """Report whether the rotating SDK leaf picked up the refreshed certificate."""
    return bool(
        renewal and before_hash != after_hash and before_hash in loaded and after_hash in loaded
    )


def evaluate(
    *,
    audit: dict[str, int],
    renewal: bool,
    flushed: object,
    hashes: tuple[str, str],
    loaded: list[str],
) -> bool:
    """Combine flush, span, source-privacy and leaf-reload checks into one verdict."""
    valid = (
        flushed is True
        and audit["endedSpans"] == (4 if renewal else 2)
        and bool(audit["nativeLlmRequestSpanSeen"])
        and not bool(audit["sensitiveSyntheticContentFoundAtSource"])
    )
    return bool(
        valid
        and (
            not renewal
            or leaf_reload_verified(
                renewal=renewal,
                before_hash=hashes[0],
                after_hash=hashes[1],
                loaded=loaded,
            )
        )
    )


def make_request_emitter(sdk: SimpleNamespace) -> RequestEmitter:
    """Build the synthetic vLLM request-tracing emitter for the canary."""

    def emit_request() -> dict[str, str]:
        """Trace one synthetic request through the installed OutputProcessor."""
        with sdk.tracer.start_as_current_span("homelab.synthetic.vllm-validation") as parent:
            parent.set_attribute("homelab.synthetic", True)
            parent.set_status(
                sdk.status(sdk.status_code.ERROR, "synthetic mandatory sampling root")
            )
            trace_id = format(parent.get_span_context().trace_id, "032x")
            parent_id = format(parent.get_span_context().span_id, "016x")
            arrival = time.time() - 3
            statistics = SimpleNamespace(
                arrival_time=arrival,
                scheduled_ts=arrival + 0.1,
                queued_ts=arrival,
                first_token_ts=arrival + 0.2,
                last_token_ts=arrival + 2.9,
                first_token_latency=0.2,
                num_generation_tokens=1,
            )
            request = SimpleNamespace(
                stats=statistics,
                prompt_token_ids=[1, 2],
                prompt_embeds=None,
                external_req_id="homelab-synthetic-vllm",
                top_p=1.0,
                max_tokens_param=1,
                temperature=0.0,
                n=1,
                prompt=MARKERS[0],
                output_text=MARKERS[1],
            )
            output = SimpleNamespace(
                trace_headers={"traceparent": "00-" + trace_id + "-" + parent_id + "-01"}
            )
            # Unmodified installed method; self is not used by this implementation.
            sdk.output.do_tracing(
                None, output, request, SimpleNamespace(iteration_timestamp=time.time())
            )
        return {"traceId": trace_id, "parentSpanId": parent_id}

    return emit_request


def publish_result(*, result: dict[str, object], renewal: bool, valid: bool) -> None:
    """Publish the canary result and its final progress marker."""
    if renewal:
        progress(dict(result, phase="completed"))
    print(json.dumps(result))
    if not valid:
        raise SystemExit(1)


def run():
    logging.disable(logging.CRITICAL)
    require_http_protocol()
    renewal = os.environ.get("HOMELAB_AWAIT_LEAF_RENEWAL") == "1"
    loaded: list[str] = []
    original_loader = ssl.SSLContext.load_cert_chain

    def observe_loader(context, certfile, keyfile=None, password=None) -> None:
        public_hash = hashlib.sha256(Path(certfile).read_bytes()).hexdigest()
        result = original_loader(context, certfile, keyfile, password)
        loaded.append(public_hash)
        return result

    if renewal:
        require_fresh_handshakes(renewal=renewal)
        ssl.SSLContext.load_cert_chain = observe_loader
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        import importlib.metadata

        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import SpanProcessor
        from opentelemetry.trace import Status, StatusCode
        from vllm.tracing import init_tracer
        from vllm.tracing.otel import get_span_exporter
        from vllm.v1.engine.output_processor import OutputProcessor

        endpoint = "https://10.250.0.3:44318/v1/traces"
        probe_exporter = get_span_exporter(endpoint)
        if not isinstance(probe_exporter, OTLPSpanExporter):
            raise ValueError("Installed vLLM selected a non-HTTP exporter")
        probe_exporter.shutdown()
        tracer = init_tracer("homelab.synthetic.vllm-request-validation", endpoint)
        provider = trace.get_tracer_provider()
        audit = {
            "endedSpans": 0,
            "sensitiveSyntheticContentFoundAtSource": False,
            "nativeLlmRequestSpanSeen": False,
        }

        class Audit(SpanProcessor):
            def on_start(self, span, parent_context=None) -> None:
                pass

            def on_end(self, span):
                audit_on_end(span, audit)

            def shutdown(self) -> None:
                pass

            def force_flush(self, timeout_millis=30000) -> bool:
                return True

        provider.add_span_processor(Audit())

        emit_request = make_request_emitter(
            SimpleNamespace(
                tracer=tracer, output=OutputProcessor, status=Status, status_code=StatusCode
            )
        )
        before_hash = certificate_hash()
        first = emit_request()
        require_flush(provider)
        traces = [first]
        if renewal:
            after_hash, trace = await_leaf_renewal(
                before_hash=before_hash,
                loaded=loaded,
                first=first,
                emit_request=emit_request,
            )
            traces.append(trace)
        else:
            after_hash = before_hash
        trace_id, parent_id = first["traceId"], first["parentSpanId"]
        flushed = provider.force_flush(timeout_millis=10000)
        provider.shutdown()
    if renewal:
        ssl.SSLContext.load_cert_chain = original_loader
    valid = evaluate(
        audit=audit,
        renewal=renewal,
        flushed=flushed,
        hashes=(before_hash, after_hash),
        loaded=loaded,
    )
    reload_verified = leaf_reload_verified(
        renewal=renewal,
        before_hash=before_hash,
        after_hash=after_hash,
        loaded=loaded,
    )
    result = {
        "success": valid,
        "traceId": trace_id,
        "parentSpanId": parent_id,
        "sourcePrivacyAudit": audit,
        "vllmVersion": importlib.metadata.version("vllm"),
        "sdkHttpVersion": importlib.metadata.version("opentelemetry-exporter-otlp-proto-http"),
        "specificTraceProtocolSelected": "http/protobuf",
        "insecureGrpcExporterUsed": False,
        "installedOutputProcessorRequestTracingMethodCalled": True,
        "sourceGuardFactoryActive": getattr(type(provider), "_homelab_source_privacy", False),
        "sourceGuardInvariants": json.loads(
            os.environ.get("HOMELAB_SOURCE_GUARD_INVARIANTS", "{}")
        ),
        "sameNativeProviderAndExporterInstance": renewal,
        "sdkLeafReloadVerified": bool(reload_verified),
        "traces": traces,
        "nativeHttpLoadedPublicCertificateHashes": sorted(set(loaded)),
        "beforeCertificateSHA256": before_hash,
        "afterCertificateSHA256": after_hash,
        "mountedCertificateSHA256": hashlib.sha256(
            Path("/etc/otel-client/tls.crt").read_bytes()
        ).hexdigest(),
        "gpuEngineStarted": False,
        "modelLoaded": False,
        "realInferenceRequests": 0,
        "productionVllmSdkCoverageVerified": False,
        "decoratorExceptionPrivacyAndRenewalStillRequired": True,
        "backendNativeChildSpanVerificationStillRequired": True,
    }
    publish_result(result=result, renewal=renewal, valid=valid)


if __name__ == "__main__":
    try:
        run()
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "success": False,
                    "errorType": type(error).__name__,
                    "privateKeysOrApiTokensLogged": False,
                    "productionVllmSdkCoverageVerified": False,
                }
            )
        )
        raise SystemExit(1) from error
