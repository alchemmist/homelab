"""Local-only HTTP/Helm checks; never calls live cluster or inference."""

import http.client
import importlib.util
import json
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "frontend"))
spec = importlib.util.spec_from_file_location("queue_web", ROOT / "frontend/queue_web.py")
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)
RealConnection = http.client.HTTPConnection
RealAuthorization = web.Handler.authorization


class CompletedRequestServer(web.Server):
    """Tests assert final cleanup only after the handler thread really returned."""

    def __init__(self, *args):
        self.completed = threading.Event()
        super().__init__(*args)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.completed.set()


class QueueWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auth_patch = patch.object(web.Handler, "authorization", return_value=200)
        cls.auth_patch.start()
        cls.server = CompletedRequestServer(("127.0.0.1", 0), web.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)
        cls.auth_patch.stop()

    def request(self, method="GET", path="/", body=None, extra=None):
        headers = {"Host": "spi.socrat.alchemmist.xyz", "X-authentik-groups": "homelab-owner"}
        headers.update(extra or {})
        self.server.completed.clear()
        c = RealConnection("127.0.0.1", self.server.server_port, timeout=3)
        c.request(method, path, body=body, headers=headers)
        r = c.getresponse()
        result = (r.status, dict(r.headers), r.read())
        c.close()
        assert self.server.completed.wait(3), "Handler cleanup did not finish"
        return result

    def test_static_csp_and_no_framework(self):
        code, headers, body = self.request()
        assert code == 200
        assert "private, no-store" in headers["Cache-Control"]
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "script-src 'self'" in headers["Content-Security-Policy"]
        assert "'unsafe-inline'" not in headers["Content-Security-Policy"]
        assert b"https://" not in body
        assert b'href="/style.css"' in body
        assert b'src="/app.js"' in body
        assert b"/queue/" not in body
        assert "Location" not in headers
        assert self.request(path="/app.js")[0] == 200
        assert self.request(path="/style.css")[0] == 200
        js = (ROOT / "frontend/app.js").read_text()
        assert "innerHTML" not in js
        assert "textContent" in js
        assert "expected_updated" in js

    def test_host_group_and_arbitrary_path_denied(self):
        assert self.request(extra={"Host": "evil.invalid"})[0] == 400
        assert self.request(path="/queue/../../service.py")[0] == 404
        assert self.request(path="/queue/app.js?x=1")[0] == 404
        assert self.request(path="/queue")[0] == 308
        assert self.request(path="/queue/")[1]["Location"] == "/"
        assert self.request(path="/queue/app.js")[1]["Location"] == "/app.js"

    def test_anonymous_challenge_returns_exact_queue_and_does_not_trust_identity_header(self):
        with patch.object(web.Handler, "authorization", return_value=401):
            code, headers, _ = self.request(extra={"X-authentik-groups": "homelab-owner"})
        assert code == 302
        assert headers["Location"] == "/login"

    def test_csrf_rejected_before_upstream(self):
        for extra in (
            {},
            {"Origin": "https://evil.invalid", "X-SPI-Queue": "1"},
            {"Origin": web.ORIGIN, "X-SPI-Queue": "1", "Sec-Fetch-Site": "cross-site"},
        ):
            with patch.object(web.http.client, "HTTPConnection") as upstream:
                assert self.request("POST", "/api/cancel", "{}", extra)[0] == 403
                upstream.assert_not_called()

    def test_fixed_upstream_and_no_cookie_identity_or_worker_header_forwarding(self):
        response = Mock(status=200)
        response.read.return_value = b'{"items":[],"counts":{}}'
        connection = Mock()
        connection.getresponse.return_value = response
        headers = {
            "Origin": web.ORIGIN,
            "X-SPI-Queue": "1",
            "Content-Type": "application/json",
            "Cookie": "opaque-test",
            "X-Worker-Token": "must-not-forward",
        }
        with (
            patch.object(web, "TOKEN", "local-fixture-token"),
            patch.object(web.http.client, "HTTPConnection", return_value=connection) as factory,
        ):
            code, _, body = self.request("POST", "/api/list", "{}", headers)
        assert code == 200
        factory.assert_called_once_with("spi-triage.automation.svc.cluster.local", 8080, timeout=8)
        args, kwargs = connection.request.call_args
        assert args == ("POST", "/operator/queue/list")
        assert set(kwargs["headers"]) == {"Content-Type", "X-Queue-Token"}
        assert b"local-fixture-token" not in body
        connection.close.assert_called_once()

    def test_bulk_endpoint_uses_one_fixed_request_with_route_scoped_body_limit(self):
        ids = [format(n, "064x") for n in range(400)]
        body = json.dumps({"items": [{"job_id": key, "expected_updated": 1} for key in ids]})
        assert len(body) > 2048
        response = Mock(status=200)
        response.read.return_value = json.dumps(
            {
                "cancelled": ids,
                "already_cancelled": [],
                "skipped": [],
                "counts": {"cancelled": 400},
                "now": 1,
            }
        ).encode()
        connection = Mock()
        connection.getresponse.return_value = response
        headers = {"Origin": web.ORIGIN, "X-SPI-Queue": "1", "Content-Type": "application/json"}
        with patch.object(web.http.client, "HTTPConnection", return_value=connection):
            assert self.request("POST", "/api/cancel-batch", body, headers)[0] == 200
        connection.request.assert_called_once()
        args, kwargs = connection.request.call_args
        assert args == ("POST", "/operator/queue/cancel-batch")
        assert json.loads(kwargs["body"]) == json.loads(body)
        for route, length in [
            ("/api/list", 2049),
            ("/api/cancel", 2049),
            ("/api/cancel-batch", 512001),
        ]:
            with patch.object(web.http.client, "HTTPConnection") as upstream:
                assert (
                    self.request("POST", route, "", {**headers, "Content-Length": str(length)})[0]
                    == 400
                )
                upstream.assert_not_called()
        with (
            patch.object(web.Handler, "authorization", return_value=401),
            patch.object(web.http.client, "HTTPConnection") as upstream,
        ):
            assert self.request("POST", "/api/cancel-batch", body, headers)[0] == 401
            upstream.assert_not_called()
        with patch.object(web.http.client, "HTTPConnection") as upstream:
            assert (
                self.request(
                    "POST", "/api/cancel-batch", body, {"Content-Type": "application/json"}
                )[0]
                == 403
            )
            upstream.assert_not_called()

    def test_old_tab_api_remains_a_fixed_authenticated_alias(self):
        assert web.ROUTES["/queue/api/list"] == web.ROUTES["/api/list"]
        assert web.ROUTES["/queue/api/cancel"] == web.ROUTES["/api/cancel"]

    def test_exhausted_capacity_returns_http_503_not_a_proxy_bad_gateway(self):
        # A dedicated server avoids racing cleanup of the previous test's request.
        server = web.Server(("127.0.0.1", 0), web.Handler)
        for _ in range(8):
            assert server.slots.acquire(False)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertLogs(level="WARNING") as logs:
                conn = RealConnection("127.0.0.1", server.server_port, timeout=3)
                conn.request("GET", "/", headers={"Host": "spi.socrat.alchemmist.xyz"})
                response = conn.getresponse()
                body = response.read()
                assert response.status == 503
                assert json.loads(body) == {"code": "SERVICE_BUSY"}
                assert response.getheader("Retry-After") == "1"
                conn.close()
            assert "queue_frontend_busy" in str(logs.output)
        finally:
            for _ in range(8):
                server.slots.release()
            server.shutdown()
            server.server_close()
            thread.join(2)
        assert self.request()[0] == 200

    def test_upstream_failures_log_only_error_type_not_private_details(self):
        headers = {"Origin": web.ORIGIN, "X-SPI-Queue": "1", "Content-Type": "application/json"}
        with (
            patch.object(
                web.http.client, "HTTPConnection", side_effect=OSError("PRIVATE_SENTINEL")
            ),
            self.assertLogs(level="WARNING") as logs,
        ):
            assert self.request("POST", "/api/list", "{}", headers)[0] == 502
        assert "OSError" in str(logs.output)
        assert "PRIVATE_SENTINEL" not in str(logs.output)

    def test_no_arbitrary_proxy_target_or_cors(self):
        headers = {"Origin": web.ORIGIN, "X-SPI-Queue": "1", "Content-Type": "application/json"}
        with patch.object(web.http.client, "HTTPConnection") as upstream:
            assert self.request("POST", "/api/claim", "{}", headers)[0] == 404
            upstream.assert_not_called()
        code, response_headers, _ = self.request("OPTIONS")
        assert code == 405
        assert "Access-Control-Allow-Origin" not in response_headers


class QueueAuthorizationTests(unittest.TestCase):
    def test_caller_identity_headers_never_authorize_without_native_session(self):
        from email.message import Message

        from queue_oidc import OIDC

        handler = Mock()
        handler.headers = Message()
        handler.headers["X-authentik-groups"] = "homelab-owner"
        handler.headers["Authorization"] = "Bearer forged"
        handler.headers["Cookie"] = "authentik_proxy=forged"
        oidc = OIDC("fixture", "s" * 48)
        with patch.object(web, "OIDC_CLIENT", oidc):
            assert RealAuthorization(handler) == 401
        with patch.object(web, "OIDC_CLIENT", None):
            assert RealAuthorization(handler) == 503

    def test_only_opaque_server_side_session_authorizes(self):
        import time
        from email.message import Message

        from queue_oidc import OIDC, SESSION_COOKIE

        handler = Mock()
        handler.headers = Message()
        oidc = OIDC("fixture", "s" * 48)
        identity = "x" * 43
        oidc.sessions[identity] = {"sub": "native-fixture", "until": time.time() + 30}
        handler.headers["Cookie"] = SESSION_COOKIE + "=" + identity
        with patch.object(web, "OIDC_CLIENT", oidc):
            assert RealAuthorization(handler) == 200
            oidc.logout(handler.headers)
            assert RealAuthorization(handler) == 401


class LogoutBrowserTests(unittest.TestCase):
    def test_safe_logout_failure_messages_and_redirects(self):
        program = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const logout=source.slice(source.indexOf("$('logout').onclick"));
(async()=>{
 for(const scenario of [200,401,403,503,'TimeoutError','TypeError']){
  const status={},button={},redirects=[];
  const context={busy:false,stopLoading:()=>{},$:id=>id==='logout'?button:status,
    window:{location:{assign:path=>redirects.push(path)}},
    AbortSignal:{timeout:()=>({})},fetch:async()=>{
     if(typeof scenario==='string')throw Object.assign(new Error('PRIVATE_DIAGNOSTIC'),{name:scenario});
     return {ok:scenario===200,status:scenario};
    }};
  vm.runInNewContext(logout,context);await button.onclick();
  if(scenario===200||scenario===401)assert.deepStrictEqual(redirects,['/signed-out']);
  else {
   assert.deepStrictEqual(redirects,[]);
   assert(!status.textContent.includes('PRIVATE_DIAGNOSTIC'));
   if(typeof scenario==='number')assert(status.textContent.includes('HTTP '+scenario));
   else assert(status.textContent.includes(scenario==='TimeoutError'?'timed out':'connection'));
  }
 }
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        subprocess.run(
            ["node", "-e", program, str(ROOT / "frontend/app.js")], check=True, timeout=10
        )


if __name__ == "__main__":
    unittest.main()
