import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


LOCK = module("image_lock", "otel-image-lock.py")
BINARIES = module("validation_binaries", "otel-validation-binaries.py")


def digest(body):
    return "sha256:" + hashlib.sha256(body).hexdigest()


def response(body, headers=None):
    result = io.BytesIO(body)
    result.headers = headers or {}
    return result


class ImageLockTests(unittest.TestCase):
    """Pin the linux/amd64 manifest and reject registry mismatches."""

    def resolve(self, entries, bad_digest=False):
        body = json.dumps({"manifests": entries}).encode()
        responses = [
            response(b'{"token":"private-fixture"}'),
            response(body, {"Docker-Content-Digest": "invalid" if bad_digest else digest(body)}),
        ]
        with patch.object(LOCK.urllib.request, "urlopen", side_effect=responses):
            return LOCK.resolve("fixture/image", "1.0")

    def test_digest_pinning(self) -> None:
        """Pin the linux/amd64 digest and keep the registry token out of the result."""
        result = self.resolve(
            [{"digest": "sha256:platform", "platform": {"os": "linux", "architecture": "amd64"}}]
        )
        assert "@sha256:" in result["image"]
        assert result["linuxAMD64Digest"] == "sha256:platform"
        assert "private-fixture" not in str(result)

    def test_registry_hash_mismatch(self) -> None:
        """Reject a registry digest that does not match the body."""
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.resolve([], bad_digest=True)

    def test_no_amd64_platform(self) -> None:
        """Reject an index that has no linux/amd64 manifest."""
        with self.assertRaisesRegex(ValueError, "one linux/amd64"):
            self.resolve([{"platform": {"os": "linux", "architecture": "arm64"}}])

    def test_ambiguous_platform(self) -> None:
        """Reject an index that has two linux/amd64 manifests."""
        with self.assertRaisesRegex(ValueError, "one linux/amd64"):
            self.resolve([{"platform": {"os": "linux", "architecture": "amd64"}}] * 2)


class ValidationBinaryTests(unittest.TestCase):
    """Extract only the expected regular file and fail closed otherwise."""

    def extract(self, output, symlink=False, corrupt=False, absent=False):
        layer = io.BytesIO()
        with tarfile.open(fileobj=layer, mode="w:gz") as archive:
            directory = tarfile.TarInfo("etc/loki")
            directory.type = tarfile.DIRTYPE
            archive.addfile(directory)
            item = tarfile.TarInfo("usr/bin/other" if absent else "usr/bin/loki")
            if symlink:
                item.type = tarfile.SYMTYPE
                item.linkname = "/etc/shadow"
                archive.addfile(item)
            else:
                item.size = 3
                archive.addfile(item, io.BytesIO(b"ELF"))
        body = layer.getvalue()
        manifest = json.dumps({"layers": [{"size": len(body), "digest": digest(body)}]}).encode()
        image = {
            "repository": "docker.io/fixture/image",
            "linuxAMD64Digest": digest(manifest),
            "image": "docker.io/fixture/image@sha256:fixture",
        }
        responses = [
            response(b'{"token":"fixture"}'),
            response(manifest),
            response(body[:-1] + b"x" if corrupt else body),
        ]
        with patch.object(BINARIES.urllib.request, "urlopen", side_effect=responses):
            return BINARIES.extract(image, "loki", output)

    def test_only_expected_regular_binary_is_extracted(self) -> None:
        """Write only the regular loki binary with its reviewed mode and digest."""
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            receipt = self.extract(output)
            assert (output / "loki").read_bytes() == b"ELF"
            assert not (output / "etc").exists()
            assert receipt["sha256"] == hashlib.sha256(b"ELF").hexdigest()
            owner_executable_mode = 0o700
            assert (output / "loki").stat().st_mode & 511 == owner_executable_mode

    def test_binary_symlink_is_rejected(self) -> None:
        """Reject a symlink planted at the expected binary path."""
        with (
            tempfile.TemporaryDirectory() as temporary,
            self.assertRaisesRegex(ValueError, "Unexpected"),
        ):
            self.extract(Path(temporary), symlink=True)

    def test_layer_digest_mismatch_is_rejected(self) -> None:
        """Reject a layer body whose checksum does not match the manifest."""
        with (
            tempfile.TemporaryDirectory() as temporary,
            self.assertRaisesRegex(ValueError, "checksum mismatch"),
        ):
            self.extract(Path(temporary), corrupt=True)

    def test_missing_expected_binary_fails_closed(self) -> None:
        """Reject a layer that does not contain the expected binary."""
        with (
            tempfile.TemporaryDirectory() as temporary,
            self.assertRaisesRegex(ValueError, "not found"),
        ):
            self.extract(Path(temporary), absent=True)
