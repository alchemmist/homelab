"""Single durable wake reservation; never hold database locks during HTTP."""

import contextlib
import http.client
import json
import socket
import threading
import time
from collections.abc import Callable
from typing import Protocol, cast

DISPATCH_URL = "http://n8n.automation.svc.cluster.local/webhook/spi-incident-triage-dispatch"

# Fixed internal dispatch endpoints and reviewed bounds; no redirects or
# proxy credential forwarding is ever attempted.
_DISPATCH_HOST = "n8n.automation.svc.cluster.local"
_DISPATCH_PORT = 80
_DISPATCH_PATH = "/webhook/spi-incident-triage-dispatch"
_DISPATCH_TIMEOUT_SECONDS = 10
_DISPATCH_OK_MIN = 200
_DISPATCH_OK_EXCLUSIVE_MAX = 300
_BACKOFF_SECONDS = 30
_MIN_WAIT_SECONDS = 0.05
_JOIN_TIMEOUT_SECONDS = 12

# Reviewed one-line exception messages kept as named constants.
_DISPATCH_DEADLINE_MESSAGE = "Dispatch deadline"
_DISPATCH_REJECTED_MESSAGE = "Dispatch rejected"


class _StoreContract(Protocol):
    """The single store surface the dispatch loop depends on."""

    def reserve_dispatch(self, now: float | None = None) -> tuple[str | None, float | None]:
        """Reserve one wake durably; return (reservation id, next deadline)."""
        ...


_BusyProbe = Callable[[], bool]
_PostAction = Callable[[], object]


class Dispatcher:
    """Single-wake deferred dispatcher that never touches the store under HTTP."""

    store: _StoreContract | None
    token: str
    enabled: bool
    post: _PostAction
    busy: _BusyProbe
    wake: threading.Event
    stopped: threading.Event
    thread: threading.Thread | None

    def __init__(
        self,
        store: _StoreContract | None,
        token: str,
        enabled: bool = False,
        post: _PostAction | None = None,
        busy: _BusyProbe | None = None,
    ) -> None:
        """Bind the store reservation surface and the reviewed dispatch seams."""
        self.store = store
        self.token = token
        self.enabled = enabled
        self.post = post or self._post
        self.busy = busy or (lambda: False)
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self.thread = None

    def _post(self) -> None:
        """Perform one bounded internal POST with an inactivity watchdog."""
        deadline = time.monotonic() + _DISPATCH_TIMEOUT_SECONDS
        connection = http.client.HTTPConnection(
            _DISPATCH_HOST, _DISPATCH_PORT, timeout=_DISPATCH_TIMEOUT_SECONDS
        )
        timer = None
        try:
            connection.connect()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(_DISPATCH_DEADLINE_MESSAGE)
            sock = cast("socket.socket", connection.sock)

            def expire() -> None:
                """Shut both socket directions; trickling reads then fail fast."""
                with contextlib.suppress(OSError):
                    sock.shutdown(socket.SHUT_RDWR)

            # Socket inactivity timeout alone does not stop trickling headers.
            timer = threading.Timer(remaining, expire)
            timer.daemon = True
            timer.start()
            connection.request(
                "POST",
                _DISPATCH_PATH,
                body=b"{}",
                headers={
                    "X-Worker-Token": self.token,
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            if time.monotonic() >= deadline:
                raise TimeoutError(_DISPATCH_DEADLINE_MESSAGE)
            if not _DISPATCH_OK_MIN <= response.status < _DISPATCH_OK_EXCLUSIVE_MAX:
                raise OSError(_DISPATCH_REJECTED_MESSAGE)
        finally:
            if timer:
                timer.cancel()
            connection.close()

    def signal(self) -> None:
        """Wake the deferred dispatch loop."""
        self.wake.set()

    def tick(self) -> float | None:
        """Reserve one durable wake and dispatch it when idle."""
        if not self.enabled or self.busy():
            return None
        reservation, deadline = cast("_StoreContract", self.store).reserve_dispatch()
        if reservation:
            self._dispatch_reserved()
            # Claim can acknowledge while POST is in flight. Never recreate it.
            return 0
        return deadline

    def _dispatch_reserved(self) -> None:
        """Post one reserved wake; any failure still counts as unconfirmed."""
        # A failed response does not prove that n8n did not start, so every
        # non-fatal post failure is deliberately treated as unconfirmed.
        try:
            self.post()
            event = "dispatch_sent"
        except Exception:
            event = "dispatch_unconfirmed"
        print(json.dumps({"component": "spi-triage", "event": event}), flush=True)

    def _run(self) -> None:
        """Serve the deferred loop until stop() is requested."""
        while not self.stopped.is_set():
            self.wake.clear()
            try:
                deadline = self.tick()
            except Exception:
                print(
                    json.dumps({"component": "spi-triage", "event": "dispatch_internal_error"}),
                    flush=True,
                )
                deadline = time.time() + _BACKOFF_SECONDS
            timeout = None if deadline is None else max(_MIN_WAIT_SECONDS, deadline - time.time())
            self.wake.wait(timeout)

    def start(self) -> None:
        """Start the daemon dispatch thread once."""
        if self.enabled and self.thread is None:
            self.thread = threading.Thread(target=self._run, name="spi-dispatch", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        """Request the loop to stop and join the dispatch thread."""
        self.stopped.set()
        self.signal()
        if self.thread:
            self.thread.join(timeout=_JOIN_TIMEOUT_SECONDS)
