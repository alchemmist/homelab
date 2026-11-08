import contextlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import ssl
import types
import urllib.error
import urllib.request
from unittest.mock import Mock
import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('runner', ROOT/'deploy/platform/rancher/public-entry/files/observer_runner.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


@pytest.mark.parametrize('error,kind', [(socket.gaierror('SECRET'), 'dns_error'),(TimeoutError('SECRET'), 'timeout'),(ssl.SSLCertVerificationError('SECRET'), 'tls_certificate'),(ConnectionRefusedError('SECRET'), 'connection_refused'),(RuntimeError('SECRET'), 'validation_or_internal'),(urllib.error.URLError(TimeoutError('SECRET')), 'timeout')])
def test_classify_without_exception_strings(error, kind):
    result=m.classify(error); assert result['kind']==kind; assert 'SECRET' not in json.dumps(result)


def test_http_status_never_leaks_url_headers_body():
    error=urllib.error.HTTPError('https://SECRET/',403,'SECRET',{'Authorization':'SECRET'},io.BytesIO(b'SECRET'))
    assert m.classify(error)=={'kind':'http_status','http_status':403}


def test_patch_failure_is_uncertain_and_not_repeated():
    inner=Mock(); inner.open.side_effect=TimeoutError('SECRET')
    req=urllib.request.Request('https://internal/apis/management.cattle.io/v3/userattributes/SECRET',method='PATCH',data=b'SECRET',headers={'Authorization':'SECRET'})
    with pytest.raises(m.DiagnosticFailure) as caught:
        with m.ObservedHTTP(inner).open(req,timeout=5): pass
    assert inner.open.call_count==1
    assert caught.value.event['mutation_may_have_applied'] is True
    assert caught.value.event['stage']=='native_cache_patch'
    assert 'SECRET' not in json.dumps(caught.value.event)


def test_body_read_failure_and_context_survives_safe_controller_wrap():
    response=Mock(); response.read.side_effect=TimeoutError('SECRET'); inner=Mock(); inner.open.return_value=response
    req=urllib.request.Request('https://auth/api/v3/core/groups/?sensitive=SECRET')
    try:
        try:
            with m.ObservedHTTP(inner).open(req) as result:result.read()
        except Exception:raise RuntimeError('SECRET') from None
    except Exception as error: event=m.failure_event(error)
    assert event['stage']=='idp_groups' and event['phase']=='response_read'
    assert event['kind']=='timeout' and 'SECRET' not in json.dumps(event)
    response.close.assert_called_once()


def test_runner_preserves_one_execution_and_restores_opener():
    original=Mock(); ctrl=types.SimpleNamespace(opener=original,reconcile_rancher=Mock(side_effect=RuntimeError('SECRET')))
    output=io.StringIO()
    with contextlib.redirect_stdout(output):assert m.run(ctrl)==1
    ctrl.reconcile_rancher.assert_called_once(); assert ctrl.opener is original
    assert 'SECRET' not in output.getvalue()


def test_success_no_policy_change_and_shared_wiki_module_untouched():
    ctrl=types.SimpleNamespace(opener=Mock(),reconcile_rancher=Mock())
    with contextlib.redirect_stdout(io.StringIO()):assert m.run(ctrl)==0
    ctrl.reconcile_rancher.assert_called_once()
    assert (ROOT/'deploy/platform/rancher/public-entry/files/observer_membership.py').read_bytes()==(ROOT/'deploy/wiki-runtime/chart/files/observer_membership.py').read_bytes()
    template=(ROOT/'deploy/platform/rancher/public-entry/templates/observer-membership.yaml').read_text()
    assert 'command: [python, -B, /code/observer_runner.py]' in template
