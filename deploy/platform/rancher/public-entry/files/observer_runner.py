"""Observer CronJob diagnostics only. No auth/cache policy, retries or secrets logged."""
import contextlib
import json
import socket
import ssl
import time
import urllib.error
import urllib.parse


class DiagnosticFailure(RuntimeError):
    def __init__(self, event):
        super().__init__('Observer dependency operation failed')
        self.event = event


def classify(error):
    """Never use exception strings, URL, headers, body, subject or request data."""
    if isinstance(error, urllib.error.HTTPError):
        return {'kind': 'http_status', 'http_status': error.code if 100 <= error.code <= 599 else 0}
    if isinstance(error, urllib.error.URLError):
        return classify(error.reason) if isinstance(error.reason, BaseException) else {'kind': 'transport_error'}
    if isinstance(error, ssl.SSLCertVerificationError): return {'kind': 'tls_certificate'}
    if isinstance(error, ssl.SSLError): return {'kind': 'tls_error'}
    if isinstance(error, socket.gaierror): return {'kind': 'dns_error'}
    if isinstance(error, TimeoutError): return {'kind': 'timeout'}
    if isinstance(error, ConnectionRefusedError): return {'kind': 'connection_refused'}
    if isinstance(error, ConnectionError): return {'kind': 'connection_error'}
    if isinstance(error, json.JSONDecodeError): return {'kind': 'invalid_json'}
    if isinstance(error, OSError): return {'kind': 'io_error'}
    return {'kind': 'validation_or_internal'}


def stage(request):
    # Use only fixed labels, never a logged URL or arbitrary path component.
    path = urllib.parse.urlsplit(request.full_url).path
    if path == '/api/v3/core/groups/': return 'idp_groups'
    if path == '/api/v3/core/users/': return 'idp_users'
    prefix = '/apis/management.cattle.io/v3/'
    if path == prefix + 'users': return 'native_users'
    if path == prefix + 'userattributes': return 'native_attributes'
    if path == prefix + 'authconfigs/genericoidc': return 'native_authconfig'
    if path.startswith(prefix + 'userattributes/') and request.get_method() == 'PATCH': return 'native_cache_patch'
    return 'dependency_other'


class ObservedHTTP:
    def __init__(self, inner): self.inner = inner

    @contextlib.contextmanager
    def open(self, request, *args, **kwargs):
        started = time.monotonic(); phase = 'https_open'; response = None
        try:
            response = self.inner.open(request, *args, **kwargs)
            phase = 'response_read'
            yield response
        except Exception as error:
            event = {'event': 'observer_reconciliation_failed', 'stage': stage(request),
                     'phase': phase, 'duration_ms': round((time.monotonic() - started) * 1000),
                     'mutation_may_have_applied': request.get_method() == 'PATCH', **classify(error)}
            raise DiagnosticFailure(event) from None
        finally:
            if response is not None: response.close()


def failure_event(error):
    # Existing controller deliberately suppresses exception text, but retains
    # context. Find only our bounded metadata; never render underlying context.
    current = error; seen = set()
    for _ in range(12):
        if current is None or id(current) in seen: break
        seen.add(id(current))
        if isinstance(current, DiagnosticFailure): return dict(current.event)
        current = current.__cause__ or current.__context__
    return {'event': 'observer_reconciliation_failed', 'stage': 'snapshot_or_plan',
            'phase': 'validation', 'mutation_may_have_applied': None, **classify(error)}


def run(controller):
    original = controller.opener
    def observed(*args, **kwargs): return ObservedHTTP(original(*args, **kwargs))
    controller.opener = observed
    started = time.monotonic()
    try:
        controller.reconcile_rancher()
    except Exception as error:
        print(json.dumps(failure_event(error), sort_keys=True), flush=True)
        return 1
    finally:
        controller.opener = original
    print(json.dumps({'event': 'observer_reconciliation_completed',
                      'duration_ms': round((time.monotonic() - started) * 1000)}), flush=True)
    return 0


if __name__ == '__main__':
    import observer_membership
    raise SystemExit(run(observer_membership))
