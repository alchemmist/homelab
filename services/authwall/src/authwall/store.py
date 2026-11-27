"""Object storage for source, optimized, and blurred wallpaper bytes."""

import io
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


class Store:
    """Read and write wallpaper objects."""

    def put(self, key: str, body: bytes, content_type: str) -> None:
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    def open_media(self, key):
        data = self.get(key)
        return io.BytesIO(data), len(data)

    def delete(self, key: str) -> None:
        raise NotImplementedError


class DirStore(Store):
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, key: str, body: bytes, content_type: str) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def delete(self, key: str) -> None:
        path = self.root / key
        if path.exists():
            path.unlink()


class S3Store(Store):
    """RustFS via the S3 API. The cluster image installs boto3."""

    def __init__(self) -> None:
        import boto3
        from botocore.client import Config

        self.bucket = os.environ["WALLPAPER_BUCKET"]
        self.client = boto3.client(
            "s3",
            endpoint_url=os.environ["RUSTFS_ENDPOINT"],
            aws_access_key_id=os.environ["RUSTFS_ACCESS_KEY"],
            aws_secret_access_key=os.environ["RUSTFS_SECRET_KEY"],
            region_name=os.environ.get("RUSTFS_REGION", "us-east-1"),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def job_urls(self, source, full, thumb):
        return {name: self.client.generate_presigned_url(method, Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=300)
                for name, method, key in (("sourceUrl", "get_object", source), ("fullPutUrl", "put_object", full), ("previewPutUrl", "put_object", thumb))}

    def open_media(self, key):
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"], response["ContentLength"]

    def has_webp(self, key):
        from botocore.exceptions import ClientError
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
                return False
            raise
        return head["ContentLength"] > 0 and head["ContentType"].split(";")[0] == "image/webp"

    def put(self, key: str, body: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=content_type)

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


def open_store() -> Store:
    if os.environ.get("RUSTFS_ENDPOINT"):
        return S3Store()
    root = Path(os.environ.get("WALLPAPER_DIR", "/tmp/authwall"))
    return DirStore(root)


def notify_n8n(wallpaper_id: str, urls: dict) -> dict:
    """Ask n8n to optimize one upload. An empty URL means the app optimizes itself."""
    url = os.environ.get("N8N_WEBHOOK_URL", "")
    if not url:
        return {}
    token = os.environ.get("WALLPAPER_JOB_TOKEN", "")
    req = urllib.request.Request(
        url,
        data=json.dumps({"id": wallpaper_id, **urls}).encode(),
        headers={"Content-Type": "application/json", "X-Wallpaper-Token": token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            raw = response.read().decode() or "{}"
    except urllib.error.URLError as exc:
        raise RuntimeError("n8n webhook failed") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
