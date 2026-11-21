"""Offline contract/security checks; no cluster access or temporary identities."""

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "deploy/authentik/quiet-mono"
# Backups must keep owner-only file permissions (0o600).
PRIVATE_FILE_MODE = 0o600


def load(name) -> ModuleType:
    path = ROOT / "ansible/roles/authentik/files" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuthentikBrandingTests(unittest.TestCase):
    """Check the frozen reference theme matches its manifest exactly."""

    def test_approved_reference_is_frozen(self) -> None:
        """Frozen theme reference files match the manifest digests."""
        root = THEME / "reference"
        manifest = json.loads((root / "manifest.json").read_text())
        # The frozen reference snapshot contains fifteen or more assets.
        frozen_files_min = 15
        assert len(manifest["files"]) >= frozen_files_min
        for name, expected in manifest["files"].items():
            content = (root / name).read_bytes()
            assert hashlib.sha256(content).hexdigest() == expected["sha256"], name
            assert len(content) == expected["bytes"], name

    def test_cli_emits_individual_documents_for_strict_v3_validation(self) -> None:
        """The CLI emits individual CRD documents, never List wrappers."""
        output = subprocess.check_output(
            [
                sys.executable,
                str(ROOT / "ansible/roles/authentik/files/branding_static.py"),
                str(THEME),
            ],
            text=True,
        )
        documents = [json.loads(part) for part in output.split("---\n") if part.strip()]
        # The generated Kustomization covers at least four YAML documents.
        documents_min = 4
        assert len(documents) >= documents_min
        assert "List" not in [item["kind"] for item in documents]

    def test_static_asset_checksums(self) -> None:
        """All manifest asset checksums match the files on disk."""
        for item in json.loads((THEME / "assets.json").read_text()).values():
            assert hashlib.sha256((THEME / item["path"]).read_bytes()).hexdigest() == item["sha256"]

    def test_static_bundle_has_no_scripts_or_secrets(self) -> None:
        """The static bundle ships only static assets, without scripts or secrets."""
        items = load("branding_static").render(THEME)["items"]
        assert [item["kind"] for item in items if item["kind"] != "ConfigMap"] == [
            "Deployment",
            "Service",
            "Ingress",
        ]
        config = items[0]
        assert config["immutable"]
        assert "annotations" not in config["metadata"]
        assert all(
            Path(name).suffix in {".webp", ".avif", ".svg", ".woff2", ".css"}
            for item in items
            if item["kind"] == "ConfigMap"
            for name in item.get("binaryData", {})
        )
        assert "Secret" not in [item["kind"] for item in items]

    def test_static_pod_is_sandboxed_and_small(self) -> None:
        """The static pod is sandboxed, digest-pinned, and memory-capped."""
        deployment = next(
            i for i in load("branding_static").render(THEME)["items"] if i["kind"] == "Deployment"
        )
        pod = deployment["spec"]["template"]["spec"]
        assert not pod["automountServiceAccountToken"]
        assert pod["securityContext"]["runAsNonRoot"]
        container = pod["containers"][0]
        assert "@sha256:" in container["image"]
        assert container["securityContext"]["readOnlyRootFilesystem"]
        assert not container["securityContext"]["allowPrivilegeEscalation"]
        assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
        assert container["resources"]["limits"]["memory"] == "64Mi"

    def test_ingress_is_only_public_static_prefix(self) -> None:
        """Only the public static prefix is exposed via ingress and TLS."""
        ingress = next(
            i for i in load("branding_static").render(THEME)["items"] if i["kind"] == "Ingress"
        )
        assert ingress["spec"]["rules"][0]["host"] == "auth.socrat.alchemmist.xyz"
        paths = ingress["spec"]["rules"][0]["http"]["paths"]
        assert len(paths) == 1
        assert paths[0]["path"] == "/-/quiet-mono/v1/"
        assert ingress["spec"]["tls"][0]["secretName"] == "authentik-tls"

    def test_fonts_and_mobile_photos_are_referenced(self) -> None:
        """Fonts, scene photos, and accessibility rules are wired into the CSS."""
        css = (THEME / "theme.css").read_text()
        assert "__ASSET_COURIER__" in css
        assert "__ASSET_SERIF__" in css
        assert "__ASSET_CODE__" in css
        assert "__ASSET_NATURE_SCENE__" in css
        assert "prefers-reduced-motion" in css
        assert "::part(drawer-content)" in css
        assert "https://" not in css

    def test_primary_action_style_also_covers_native_redirect_anchor(self) -> None:
        """Primary action styling also styles native redirect anchors."""
        css = (THEME / "theme.css").read_text()
        assert not re.search(r"(?<![\w-])button\.pf-m-primary", css)
        assert ":is(button,a.pf-c-button).pf-m-primary" in css
        assert ":is(button,a.pf-c-button).pf-m-primary:hover::after" in css
        assert "box-sizing:border-box;text-decoration:none!important" in css

    def test_nested_mfa_child_without_challenge_part_is_covered(self) -> None:
        """Nested MFA children lacking a challenge part stay visible and styled."""
        css = (THEME / "theme.css").read_text()
        assert ":host(:is([part='challenge'],ak-stage-authenticator-validate-code))" in css
        assert ":host(ak-stage-authenticator-validate-code) .pf-c-button:focus-visible" in css
        assert "ak-stage-authenticator-validate-code{display:none" not in css

    def test_server_denial_template_is_scoped_and_centered(self) -> None:
        """Server denial template stays scoped and centered in the drawer."""
        css = (THEME / "theme.css").read_text()
        assert "body:has(.pf-c-page__drawer .pf-c-login)" in css
        assert (
            ".pf-c-page__drawer .pf-c-login__main{display:block!important;align-self:center!important;"
            in css
        )
        assert ".pf-c-page__drawer .pf-c-login .pf-c-button.pf-m-primary" in css
        assert ".pf-c-page__drawer .ak-c-form-static .username{overflow-wrap:anywhere" in css
        assert "ak-back-home{display:none" not in css
        assert "pf-icon-error-circle-o{display:none" not in css

    def test_inspector_toggle_and_history_are_presentation_only(self) -> None:
        """Inspector toggle and history stepper are presentation-only tweaks."""
        css = (THEME / "theme.css").read_text()
        assert "ak-flow-inspector-button{position:fixed!important" in css
        assert "width:39px!important;height:39px!important" in css
        assert "i.fa-search-plus" in css
        assert (
            ".pf-c-progress-stepper{max-block-size:none!important;max-height:none!important;overflow:visible!important}"
            in css
        )
        assert "max-block-size:22rem" not in css
        assert "max-block-size:18rem" not in css
        assert "nth-child" not in css
        assert "column-reverse" not in css

    def test_reconciler_does_not_ship_a_replacement_frontend(self) -> None:
        """The reconciler touches only branding APIs, nothing more."""
        source = (ROOT / "ansible/roles/authentik/files/branding.py").read_text()
        assert "core/users/" not in source
        assert "set_password" not in source
        assert "providers/" not in source
        assert "stages/authenticator/" not in source
        assert "verify=False" not in source
        assert "api/v3/" in source
        assert "2026.8.5" in source
        assert "api('POST', 'admin/file/" not in source
        assert "/-/quiet-mono/v1/" in source

    def test_backups_have_private_permissions(self) -> None:
        """Backup JSON files are written with 0600 permissions."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "backup.json"
            load("branding").protected_json(target, {"test": True})
            assert target.stat().st_mode & 511 == PRIVATE_FILE_MODE

    def test_reference_stays_nonmodal(self) -> None:
        """The reference dialog stays non-modal."""
        source = (THEME / "reference/quiet-mono.js").read_text()
        assert "showModal(" not in source
        assert "dialog.show()" in source
        assert "!dialog.open || inspectorClosing" in source

    def test_playbook_uses_explicit_apply_and_server_side_configmaps(self) -> None:
        """The playbook uses explicit apply and helm-free server-side configmaps."""
        source = (ROOT / "ansible/playbooks/authentik-branding.yml").read_text()
        assert "authentik_branding_action: prepare" in source
        assert "--server-side" in source
        assert "become: false" in source
        assert "helm" not in source


class NatureBackgroundTests(unittest.TestCase):
    """Validate the nature background collection and random endpoint."""

    def test_full_collection_and_css_only_random_endpoint(self) -> None:
        """All 30 photos ship with cookie-seeded, CSS-only random selection."""
        photos = json.loads((THEME / "nature.json").read_text())["photos"]
        # The nature collection ships thirty unique photos, served via CSS only.
        photo_count = 30
        assert len(photos) == photo_count
        assert len({p["id"] for p in photos}) == photo_count
        manifest = json.loads((THEME / "assets.json").read_text())
        for photo in photos:
            for variant in ["desktop", "mobile"]:
                assert manifest[photo[variant]]["path"].startswith("nature/")
        items = load("branding_static").render(THEME)["items"]
        conf = items[0]["data"]["nginx.conf"]
        assert 'split_clients "$nature_seed" $nature_draw' in conf
        cache_directives = 3
        assert conf.count('Cache-Control "no-store"') == cache_directives
        assert "~*image/avif avif" in conf
        absolute_redirect_directives = 2
        set_cookie_headers = 3
        assert conf.count("absolute_redirect off") == absolute_redirect_directives
        assert conf.count("add_header Set-Cookie") == set_cookie_headers
        assert "Max-Age=1800; Secure; HttpOnly; SameSite=Lax" in conf
        assert "Path=/-/quiet-mono/v1/" in conf
        assert "Domain=" not in conf
        assert "authentik_session" not in conf
        assert "$remote_addr" not in conf
        assert "$http_user_agent" not in conf
        assert "javascript" not in conf
        for variant in ["desktop", "mobile"]:
            assert "location = /-/quiet-mono/v1/nature/" + variant in conf
            assert "return 302 /-/quiet-mono/v1/$nature_" + variant in conf

    def test_scene_journey_uses_opaque_same_origin_next_not_new_request_id(self) -> None:
        """The scene chain carries a same-origin next hop, not new identifiers."""
        conf = load("branding_static").render(THEME)["items"][0]["data"]["nginx.conf"]
        assert "map $http_referer $nature_next" in conf
        assert "https://auth[.]socrat[.]alchemmist[.]xyz/if/flow/" in conf
        assert "state%3d" in conf
        assert "map $nature_flow_seed $nature_scene" in conf
        assert "default $nature_draw;" in conf
        assert '"" $nature_fallback;' in conf
        assert "default $nature_previous;" in conf
        assert "map $http_cookie $nature_previous" in conf
        assert 'default "";' in conf
        for photo in json.loads((THEME / "nature.json").read_text())["photos"]:
            assert photo["id"] in conf
        assert "add_header X-Quiet-Mono-Flow" not in conf
        assert 'Set-Cookie "$nature_flow_seed' not in conf
        assert "access_log off;" in conf

    def test_early_single_layer_and_avif_transfer_budget(self) -> None:
        """Early single-layer scenes stay within the AVIF transfer budget."""
        css = (THEME / "theme.css").read_text()
        assert "@import url('__ASSET_NATURE_SCENE__')" in css
        assert "ak-drawer#flow-drawer{min-height:100svh;background:transparent!important}" in css
        for photo in json.loads((THEME / "nature.json").read_text())["photos"]:
            for variant, cap in [("desktop", 220000), ("mobile", 100000)]:
                assert photo[variant + "AvifBytes"] <= cap
                assert photo[variant + "AvifBytes"] < photo[variant + "Bytes"]
            preview_byte_cap = 1000
            scene_css_byte_cap = 6000
            assert photo["previewBytes"] < preview_byte_cap
            assert photo["sceneCssBytes"] < scene_css_byte_cap
            scene = (
                THEME / json.loads((THEME / "assets.json").read_text())[photo["sceneCss"]]["path"]
            )
            assert "data:image/webp;base64," in scene.read_text()
            assert "javascript" not in scene.read_text()

    def test_configmap_shards_and_projected_assets_are_bounded(self) -> None:
        """ConfigMap shards and projected assets stay size-bounded and complete."""
        import base64

        items = load("branding_static").render(THEME)["items"]
        cms = [i for i in items if i["kind"] == "ConfigMap"]
        all_files = {}
        for cm in cms:
            assert cm["immutable"]
            # Each sharded ConfigMap stays under roughly one megabyte.
            shard_byte_cap = 950000
            assert len(json.dumps(cm).encode()) < shard_byte_cap
            all_files.update(cm.get("binaryData", {}))
        assert len(all_files) == len(json.loads((THEME / "assets.json").read_text()))
        # All projected assets together stay under the sixteen megabyte cap.
        total_asset_cap = 16000000
        assert sum(len(base64.b64decode(v)) for v in all_files.values()) < total_asset_cap
        deployment = next(i for i in items if i["kind"] == "Deployment")
        volumes = deployment["spec"]["template"]["spec"]["volumes"]
        sources = next(v for v in volumes if v["name"] == "assets")["projected"]["sources"]
        assert {s["configMap"]["name"] for s in sources} == {
            c["metadata"]["name"] for c in cms if c.get("binaryData")
        }


if __name__ == "__main__":
    unittest.main()
