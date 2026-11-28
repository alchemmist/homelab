"""Fixed-origin immutable evidence storage; trusted caller injects credentials.

Transport test seam: (method, path, headers, payload, seconds) -> status, headers, bytes.
No job state is retained. Returned verification must be persisted by the caller.
"""

import contextlib
import datetime
import hashlib
import hmac
import http.client
import queue
import re
import socket
import threading
import time
import urllib.parse
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from typing import Any, cast

ORIGIN = "http://rustfs.rustfs.svc.cluster.local:9000"
BUCKET = "spi-evidence"
MAX_BYTES = 2 * 1024 * 1024
# Process-wide admission bound; timed-out callers do not release resolver slots.
MAX_RESOLVERS = 4
_RESOLVER_SLOTS = threading.BoundedSemaphore(MAX_RESOLVERS)
KEY = re.compile(
    r"spi/v1/[0-9a-f]{64}/[0-9a-f]{64}/(?:manifest\.json|E[0-9]{3}-[A-Za-z0-9._-]{1,100})\Z"
)

# Wire-exact server status and bound values; names document each contract use.
_HTTP_OK = 200
_HTTP_NOT_FOUND = 404
_HTTP_SERVER_ERROR_MIN = 500
_HTTP_SERVER_ERROR_MAX = 599
_OPERATION_SECONDS_MAX = 60
_RETRY_AFTER_MAX_CHARS = 128
_RETRY_AFTER_CAP_SECONDS = 86400

# Stable exception messages kept as named constants for reviewer bootstrap.
_UPSTREAM_DEADLINE_MESSAGE = "upstream deadline"
_RESOLUTION_DEADLINE_MESSAGE = "resolution deadline"
_RESOLUTION_CAPACITY_MESSAGE = "resolution capacity deadline"
_RESOLUTION_FAILED_MESSAGE = "resolution failed"
_INVALID_UPSTREAM_MESSAGE = "invalid upstream"

type _Transport = Callable[
    [str, str, dict[str, str], bytes, float], tuple[int, dict[str, str], bytes]
]

type _AddressList = list[tuple[int, int, int, str | None, tuple[Any, ...]]]
type _CreateConnection = Callable[..., socket.socket]


class StoragePermanent(Exception):
    """Permanent, non-retryable storage failure (bucket/config/protocol level)."""

    def __init__(self) -> None:
        """Report the permanent storage failure code."""
        super().__init__("S3_PERMANENT")


class StorageConflict(StoragePermanent):
    """Stored bytes diverge from the requested exact bytes."""

    def __init__(self) -> None:
        """Report the conflict failure code."""
        Exception.__init__(self, "S3_CONFLICT")


class StorageTransient(Exception):
    """Retryable storage failure carrying an optional retry-after hint."""

    def __init__(self, retry_after: object = None, *, reason: str = "UNSPECIFIED") -> None:
        """Report the transient failure with a closed-set diagnostic reason."""
        self.retry_after = retry_after
        self.reason = (
            reason
            if reason
            in {
                "UNSPECIFIED",
                "DNS_RESOLUTION",
                "TIMEOUT",
                "HTTP_TRANSPORT",
                "OPERATION_DEADLINE",
                "HTTP_408",
                "HTTP_429",
                "HTTP_5XX",
                "INCOMPLETE_READ",
                "READBACK_NOT_READY",
            }
            else "UNSPECIFIED"
        )
        super().__init__("S3_TRANSIENT")


def expire(sock: socket.socket) -> None:
    """Shut both directions of a socket so blocked reads/writes fail fast."""
    with contextlib.suppress(OSError):
        sock.shutdown(socket.SHUT_RDWR)


def watchdog(sock: socket.socket, seconds: float) -> threading.Timer:
    """Arm a daemon timer that expires the socket after ``seconds``."""
    timer = threading.Timer(seconds, expire, (sock,))
    timer.daemon = True
    timer.start()
    return timer


class DeadlineResponse(http.client.HTTPResponse):
    """Response that keeps the connection watchdog alive until it is closed."""

    deadline_timer: threading.Timer | None = None

    def close(self) -> None:
        """Release the body and the deadline timer it owns."""
        try:
            super().close()
        finally:
            timer = self.deadline_timer
            if timer is not None:
                timer.cancel()


class DeadlineConnection(http.client.HTTPConnection):
    """Connection whose whole lifetime is bounded by one owner-set budget."""

    response_class = DeadlineResponse
    budget: float
    deadline_timer: threading.Timer
    deadline_expired: bool
    response_owns_deadline: bool
    transferring_response: bool
    _create_connection: _CreateConnection

    def connect(self) -> None:
        """Connect within the budget and expire the socket past the deadline."""
        start = time.monotonic()
        self.deadline_expired = False
        self.response_owns_deadline = False
        connected_socket: list[socket.socket | None] = []

        def abort() -> None:
            self.deadline_expired = True
            sock = (
                self.sock
                if self.sock is not None
                else (connected_socket[0] if connected_socket else None)
            )
            if sock is not None:
                expire(sock)

        self.deadline_timer = threading.Timer(self.budget, abort)
        self.deadline_timer.daemon = True
        self.deadline_timer.start()
        try:
            super().connect()
            connected_socket.append(self.sock)
            self._expire_if_deadline_passed(start)
        except BaseException:
            self.close()
            raise

    def _expire_if_deadline_passed(self, start: float) -> None:
        """Expire the socket if the budget ran out during connect."""
        if self.deadline_expired or time.monotonic() - start >= self.budget:
            expire(cast("socket.socket", self.sock))
            raise TimeoutError(_UPSTREAM_DEADLINE_MESSAGE)

    def getresponse(self) -> DeadlineResponse:
        """Return the bounded response and hand its deadline to the body."""
        # HTTPConnection closes/detaches its socket before returning a response
        # with Connection: close. The response's file still owns the descriptor:
        # keep its watchdog alive until that response is explicitly closed.
        self.transferring_response = True
        try:
            response = cast("DeadlineResponse", super().getresponse())
        except BaseException:
            self.deadline_timer.cancel()
            raise
        else:
            response.deadline_timer = self.deadline_timer
            self.response_owns_deadline = True
            return response
        finally:
            self.transferring_response = False

    def close(self) -> None:
        """Close the connection unless a response still owns the deadline."""
        timer = getattr(self, "deadline_timer", None)
        if timer and not (
            getattr(self, "transferring_response", False)
            or getattr(self, "response_owns_deadline", False)
        ):
            timer.cancel()
        super().close()


class HTTPConnection(DeadlineConnection):
    """HTTPConnection with shared admission and DNS resolution deadline."""

    def connect(self) -> None:
        """Admit through the shared resolver bound and connect locally."""
        # Admission and resolution share one deadline. Only the resolver releases
        # capacity: a timed-out caller cannot admit more stuck native DNS calls.
        started = time.monotonic()
        deadline = started + min(cast("float", self.timeout), self.budget)
        slots = _RESOLVER_SLOTS
        if not slots.acquire(timeout=max(0, deadline - time.monotonic())):
            raise TimeoutError(_RESOLUTION_CAPACITY_MESSAGE)
        addresses = self._resolve_address(deadline, slots)
        self.budget -= time.monotonic() - started
        if self.budget <= 0:
            raise TimeoutError(_RESOLUTION_DEADLINE_MESSAGE)

        def create(
            _address: object, timeout: float, source_address: tuple[str, int]
        ) -> socket.socket:
            # Conservative first-address only; caller retries transient failures.
            family, kind, proto, _host, target = addresses[0]
            sock = socket.socket(family, kind, proto)
            try:
                sock.settimeout(min(timeout, self.budget))
                if source_address:
                    sock.bind(source_address)
                sock.connect(target)
            except BaseException:
                sock.close()
                raise
            else:
                return sock

        self._create_connection = create
        super().connect()

    def _resolve_address(self, deadline: float, slots: threading.BoundedSemaphore) -> _AddressList:
        """Resolve one host on a release-only worker under the shared deadline."""
        results: queue.Queue[object] = queue.Queue(maxsize=1)

        def resolve() -> None:
            try:
                try:
                    results.put(socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM))
                except OSError:
                    results.put(None)
            finally:
                slots.release()

        try:
            threading.Thread(target=resolve, daemon=True).start()
        except BaseException:
            slots.release()
            raise
        try:
            raw = results.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            raise TimeoutError(_RESOLUTION_DEADLINE_MESSAGE) from None
        if time.monotonic() >= deadline:
            raise TimeoutError(_RESOLUTION_DEADLINE_MESSAGE)
        if not raw:
            raise socket.gaierror(socket.EAI_AGAIN, _RESOLUTION_FAILED_MESSAGE)
        return cast("_AddressList", raw)


def sign(
    method: str,
    url: str,
    access: str,
    secret: str,
    now: datetime.datetime | None = None,
    region: str = "us-east-1",
    payload: bytes = b"",
) -> dict[str, str]:
    """Sign one request with AWS SigV4; canonical URI encoded exactly once."""
    u = urllib.parse.urlsplit(url)
    if u.query or u.fragment or u.username or u.password:
        raise ValueError(_INVALID_UPSTREAM_MESSAGE)
    now = now or datetime.datetime.now(datetime.UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    day = stamp[:8]
    digest = hashlib.sha256(payload).hexdigest()
    headers = {"host": u.netloc, "x-amz-content-sha256": digest, "x-amz-date": stamp}
    names = ";".join(sorted(headers))
    canonical = "\n".join(
        [
            method,
            urllib.parse.quote(u.path, safe="/~"),
            "",
            "".join(k + ":" + headers[k] + "\n" for k in sorted(headers)),
            names,
            digest,
        ]
    )
    scope = day + "/" + region + "/s3/aws4_request"
    message = (
        "AWS4-HMAC-SHA256\n"
        + stamp
        + "\n"
        + scope
        + "\n"
        + hashlib.sha256(canonical.encode()).hexdigest()
    )
    key = ("AWS4" + secret).encode()
    for part in (day, region, "s3", "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
    headers["Authorization"] = (
        "AWS4-HMAC-SHA256 Credential="
        + access
        + "/"
        + scope
        + ", SignedHeaders="
        + names
        + ", Signature="
        + signature
    )
    return headers


def retry_after(value: object) -> float | None:
    """Bound an HTTP Retry-After header (seconds or date) to a safe hint."""
    try:
        if not isinstance(value, str) or len(value) > _RETRY_AFTER_MAX_CHARS:
            return None
        if value.isascii() and value.isdigit():
            seconds: float = int(value)
        else:
            parsed = parsedate_to_datetime(value)
            seconds = (parsed - datetime.datetime.now(datetime.UTC)).total_seconds()
        return min(_RETRY_AFTER_CAP_SECONDS, max(0, seconds))
    except (ValueError, TypeError, OverflowError):
        return None


class S3Evidence:
    """SigV4 client for the one fixed evidence origin, verify after every write."""

    def __init__(
        self,
        access: str,
        secret: str,
        *,
        origin: str = ORIGIN,
        operation_seconds: float = 30,
        transport: _Transport | None = None,
    ) -> None:
        """Validate fixed origin, credentials and modest operation budget."""
        if origin != ORIGIN or not (
            type(operation_seconds) in (int, float)
            and 0 < operation_seconds <= _OPERATION_SECONDS_MAX
        ):
            raise StoragePermanent
        if any(
            not isinstance(x, str) or not re.fullmatch(r"[A-Za-z0-9/+=_.-]{1,256}", x)
            for x in (access, secret)
        ):
            raise StoragePermanent
        self._access, self._secret = access, secret
        self._seconds, self._transport = operation_seconds, transport

    def _wire(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        payload: bytes,
        remaining: float,
    ) -> tuple[int, dict[str, str], bytes]:
        """Perform one request/response round trip on the in-cluster socket."""
        conn = HTTPConnection("rustfs.rustfs.svc.cluster.local", 9000, timeout=min(5, remaining))
        conn.budget = remaining
        response = None
        try:
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            body = b""
            if response.status == _HTTP_OK and method == "GET":
                if response.getheader("Content-Encoding", "identity") != "identity":
                    raise StoragePermanent
                length = response.getheader("Content-Length")
                if length is not None and (
                    not length.isascii() or not length.isdigit() or int(length) > MAX_BYTES
                ):
                    raise StoragePermanent
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise StoragePermanent
                if length is not None and len(body) != int(length):
                    raise StorageTransient
            return response.status, dict(response.getheaders()), body
        finally:
            if response is not None:
                response.close()
            conn.close()

    def _request(self, method: str, key: str, payload: bytes, deadline: float) -> tuple[int, bytes]:
        """Issue one signed request against the fixed origin and bucket."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise StorageTransient(reason="OPERATION_DEADLINE")
        path = "/" + BUCKET + "/" + key
        headers = sign(method, ORIGIN + path, self._access, self._secret, payload=payload)
        if method == "PUT":
            headers["If-None-Match"] = "*"
        headers["Connection"] = "close"
        try:
            result = (self._transport or self._wire)(method, path, headers, payload, remaining)
        except (OSError, http.client.HTTPException) as exc:
            reason = (
                "DNS_RESOLUTION"
                if isinstance(exc, socket.gaierror)
                else "TIMEOUT"
                if isinstance(exc, TimeoutError)
                else "HTTP_TRANSPORT"
            )
            raise StorageTransient(reason=reason) from None
        if time.monotonic() >= deadline:
            raise StorageTransient(reason="OPERATION_DEADLINE")
        status, response_headers, body = result
        if not isinstance(body, bytes) or len(body) > MAX_BYTES:
            raise StoragePermanent
        if status in (408, 429) or _HTTP_SERVER_ERROR_MIN <= status <= _HTTP_SERVER_ERROR_MAX:
            raise StorageTransient(
                retry_after(
                    next(
                        (v for k, v in response_headers.items() if k.lower() == "retry-after"),
                        None,
                    )
                ),
                reason="HTTP_5XX" if status >= _HTTP_SERVER_ERROR_MIN else "HTTP_" + str(status),
            )
        if status not in (200, 201, 204, 404, 409, 412):
            raise StoragePermanent
        return status, body

    def ensure_object(self, key: object, exact_bytes: object) -> dict[str, object]:
        """Store or fetch one object and return its verified receipt."""
        if (
            not isinstance(key, str)
            or not KEY.fullmatch(key)
            or ".." in key
            or type(exact_bytes) is not bytes
            or len(exact_bytes) > MAX_BYTES
        ):
            raise StoragePermanent
        deadline = time.monotonic() + self._seconds
        digest = hashlib.sha256(exact_bytes).hexdigest()

        def verify(status: int, body: bytes) -> dict[str, object]:
            if status != _HTTP_OK:
                raise StorageTransient(reason="READBACK_NOT_READY")
            if len(body) != len(exact_bytes) or hashlib.sha256(body).hexdigest() != digest:
                raise StorageConflict
            return {
                "bucket": BUCKET,
                "key": key,
                "sha256": digest,
                "size": len(body),
                "verified": True,
            }

        status, body = self._request("GET", key, b"", deadline)
        if status == _HTTP_OK:
            return verify(status, body)
        if status != _HTTP_NOT_FOUND:
            raise StoragePermanent
        try:
            status, _ = self._request("PUT", key, exact_bytes, deadline)
            if status not in (200, 201, 204, 409, 412):
                raise StoragePermanent
        except StorageTransient:
            return verify(*self._request("GET", key, b"", deadline))
        return verify(*self._request("GET", key, b"", deadline))
