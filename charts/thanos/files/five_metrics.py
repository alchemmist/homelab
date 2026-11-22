"""Expose only aggregate usage for the live shared 5m bucket."""
import os
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import shelf


def main():
    """Serve shelf requests and expose fresh cached usage alongside current filesystem headroom."""
    root = os.environ["SHELF_DIRECTORY"]
    token = Path(os.environ["SHELF_TOKEN_FILE"]).read_text().strip()
    if not token:
        raise ValueError("empty shelf token")

    measured = []

    def sample_size():
        while True:
            try:
                total = Path(root).lstat().st_blocks * 512
                for path in Path(root).rglob("*"):
                    total += path.lstat().st_blocks * 512
                measured[:] = [(time.monotonic(), total)]
            except (OSError, RuntimeError):
                pass  # Racing compaction: do not replace a valid sample with zero.
            time.sleep(60)

    threading.Thread(target=sample_size, daemon=True).start()

    class MetricsHandler(shelf.handler(root, token)):
        def do_GET(self):
            if self.path != "/metrics":
                return super().do_GET()
            try:
                fs = os.statvfs(root)
                available = fs.f_bavail * fs.f_frsize
            except OSError:
                self.send_error(503)
                return None
            body = f'socrat_five_bucket_available_bytes{{backing_node="socrat-0"}} {available}\n'
            sample = measured[:]
            if sample and time.monotonic() - sample[0][0] < 180:
                body += f'socrat_metrics_directory_bytes{{node="socrat-0",role="shelf",path="/var/lib/socrat-thanos-5m"}} {sample[0][1]}\n'
            body = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    ThreadingHTTPServer(("0.0.0.0", int(os.environ["SHELF_PORT"])), MetricsHandler).serve_forever()


if __name__ == "__main__":
    main()
