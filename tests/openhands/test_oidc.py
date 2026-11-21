"""Auth gate invariants; no live credentials or IdP writes in these tests."""
import copy
import base64
import importlib.util
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("openhands_oidc", ROOT/"scripts/provision-openhands-oidc.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class NativeOIDC(unittest.TestCase):
    bindings: "list[dict[str, object]]"

    def setUp(self):
        self.owner = {"pk":"owner"}
        self.settings = copy.deepcopy(m.PROVIDER)
        self.provider = {**self.settings,"pk":1,"client_secret":"fixture-only"}
        self.app = {**m.APP,"pk":"app","provider":1}
        self.journal = {"status":"active","provider_pk":1,"app_pk":"app","client_secret":"fixture-only"}
        self.bindings = [{"group":"owner","user":None,"policy":None,"enabled":True,"negate":False,"failure_result":False}]

    def validate(self):
        class API:
            def rows(_, path) -> "list[dict[str, object]]":return self.bindings
        m.validate(API(),self.owner,self.settings,self.provider,self.app,self.journal)

    def test_cookie_secret_uses_go_raw_url_alphabet(self):
        raw = bytes([251]) * 32
        encoded = m.encode_cookie_secret(raw)
        assert "+" not in encoded
        assert "/" not in encoded
        assert base64.urlsafe_b64decode(encoded) == raw
        with self.assertRaises(RuntimeError): m.encode_cookie_secret(b"too short")

    def test_owner_only_existing_identity(self): self.validate()

    def test_no_adoption_or_rotation(self):
        original = copy.deepcopy(self.journal)
        for value in (None,{**original,"status":"pending"},{**original,"client_secret":"changed"}):
            self.journal = value
            with self.assertRaises(RuntimeError): self.validate()

    def test_binding_cannot_expand_or_disable(self):
        for key,value in [("group","observer"),("user","someone"),("policy","permissive"),("enabled",False),("negate",True),("failure_result",True)]:
            original = copy.deepcopy(self.bindings)
            self.bindings[0][key] = value
            with self.assertRaises(RuntimeError): self.validate()
            self.bindings = original
        self.bindings *= 2
        with self.assertRaises(RuntimeError): self.validate()

    def test_callback_or_grant_drift_blocked(self):
        for key,value in [("client_id","wrong"),("grant_types",["authorization_code","password"]),("redirect_uris",[{"matching_mode":"regex","url":".*"}])]:
            old = copy.deepcopy(self.provider)
            self.provider[key] = value
            with self.assertRaises(RuntimeError): self.validate()
            self.provider = old


class OIDCRender(unittest.TestCase):
    def helm(self,*args):
        return subprocess.run(["helm","template","openhands",str(ROOT/"charts/openhands"),"-n","openhands","-f",str(ROOT/"deploy/openhands/values.yaml"),*args],text=True,capture_output=True)

    def objects(self):
        r = self.helm(); assert r.returncode == 0, r.stderr
        return [v for v in yaml.safe_load_all(r.stdout) if v]

    def test_only_ingress_terminates_at_oidc(self):
        ingresses = [v for v in self.objects() if v["kind"]=="Ingress"]
        assert len(ingresses) == 1
        i = ingresses[0]
        assert i["metadata"]["namespace"] == "identity"
        assert i["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]["name"] == "openhands-oidc"

    def test_tls_is_tracked_not_hidden_by_healthy_proxy(self):
        cert = next(v for v in self.objects() if v["kind"]=="Certificate")
        assert cert["spec"]["secretName"] == "openhands-oidc-tls"
        assert cert["spec"]["dnsNames"] == ["openhands.socrat.alchemmist.xyz"]
        assert cert["spec"]["issuerRef"]["kind"] == "ClusterIssuer"

    def test_backend_only_reachable_from_gateway(self):
        p = next(v for v in self.objects() if v["kind"]=="NetworkPolicy" and v["metadata"]["name"]=="openhands-boundary")
        assert p["spec"]["ingress"][0]["from"] == [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "identity"}}, "podSelector": {"matchLabels": {"app": "openhands-oidc"}}}]

    def test_vps_hostnetwork_source_is_exact_and_proxy_only(self):
        p = next(v for v in self.objects() if v["kind"]=="NetworkPolicy" and v["metadata"]["name"]=="openhands-oidc")
        assert {"ipBlock": {"cidr": "10.42.0.0/32"}} in p["spec"]["ingress"][0]["from"]
        assert p["spec"]["ingress"][0]["ports"] == [{"port": 4180, "protocol": "TCP"}]

    def test_identity_uses_immutable_subject_not_unverified_mail(self):
        d = next(v for v in self.objects() if v["kind"]=="Deployment" and v["metadata"]["name"]=="openhands-oidc")
        args = d["spec"]["template"]["spec"]["containers"][0]["args"]
        assert "--oidc-email-claim=sub" in args
        assert "--scope=openid profile groups offline_access" in args
        assert "--allowed-group=homelab-owner" in args
        assert not any("allow-unverified-email" in a or "skip-issuer-verification" in a for a in args)

    def test_oidc_not_custom_auth_or_bearer_bypass(self):
        d = next(v for v in self.objects() if v["kind"]=="Deployment" and v["metadata"]["name"]=="openhands-oidc")
        pod = d["spec"]["template"]["spec"]; c = pod["containers"][0]
        assert not pod["automountServiceAccountToken"]
        assert "@sha256:" in c["image"]
        for flag in ["--provider=oidc","--allowed-group=homelab-owner","--skip-jwt-bearer-tokens=false","--cookie-secure=true","--code-challenge-method=S256"]:
            assert flag in c["args"]
        assert not any("insecure" in a or "skip-auth-route" in a for a in c["args"])
        canvas = next(v for v in self.objects() if v["kind"]=="StatefulSet")
        assert "openhands-oidc" not in str(canvas["spec"]["template"]["spec"].get("volumes", []))

    def test_refresh_uses_server_side_sessions_without_weakening_expiry(self):
        d=next(v for v in self.objects() if v["kind"]=="Deployment" and v["metadata"]["name"]=="openhands-oidc")
        c=d["spec"]["template"]["spec"]["containers"][0]
        for flag in ["--session-store-type=redis","--cookie-expire=8h","--cookie-refresh=2m"]:
            assert flag in c["args"]
        env=next(x for x in c["env"] if x["name"]=="OAUTH2_PROXY_REDIS_PASSWORD")
        assert env["valueFrom"]["secretKeyRef"] == {"name": "openhands-oidc-sessions", "key": "password"}

    def test_session_cache_is_private_nonpersistent_and_restricted(self):
        d=next(v for v in self.objects() if v["kind"]=="Deployment" and v["metadata"]["name"]=="openhands-oidc-sessions")
        pod=d["spec"]["template"]["spec"];c=pod["containers"][0]
        assert d["spec"]["strategy"]["type"] == "Recreate"
        assert not pod["automountServiceAccountToken"]
        assert c["securityContext"]["readOnlyRootFilesystem"]
        assert "@sha256:" in c["image"]
        assert not any("persistentVolumeClaim" in v for v in pod["volumes"])
        p=next(v for v in self.objects() if v["kind"]=="NetworkPolicy" and v["metadata"]["name"]=="openhands-oidc-sessions")
        assert p["spec"]["ingress"] == [{"from": [{"podSelector": {"matchLabels": {"app": "openhands-oidc"}}}], "ports": [{"port": 6379, "protocol": "TCP"}]}]
        assert p["spec"]["egress"] == []

    def test_no_unprotected_ingress_or_bootstrap(self):
        assert self.helm("--set", "ingress.enabled=true").returncode != 0
        assert self.helm("--set", "oidc.enabled=false").returncode != 0


if __name__ == "__main__": unittest.main()
