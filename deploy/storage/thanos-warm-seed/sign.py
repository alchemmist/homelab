"""Run only in short-lived signer; output capability paths through private exec pipe."""

import datetime, hashlib, hmac, json, os, sys
from urllib.parse import quote, urlencode


def main():
    host = "thanos-warm-api:9000"
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    day = stamp[:8]
    scope = day + "/us-east-1/s3/aws4_request"

    def mac(k, v):
        return hmac.digest(k, v.encode(), "sha256")

    k = ("AWS4" + os.environ["SECRET"]).encode()
    for s in (day, "us-east-1", "s3", "aws4_request"):
        k = mac(k, s)
    args = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": os.environ["ACCESS"] + "/" + scope,
        "X-Amz-Date": stamp,
        "X-Amz-Expires": "14400",
        "X-Amz-SignedHeaders": "host",
    }
    q = urlencode(sorted(args.items()), quote_via=quote)
    out = {}
    for key, n in json.load(sys.stdin):
        path = "/thanos-workshop/" + quote(key, safe="/")
        spec = {"bytes": n}
        for method in ("HEAD", "GET", "PUT"):
            req = "\n".join(
                [method, path, q, "host:" + host + "\n", "host", "UNSIGNED-PAYLOAD"]
            )
            data = "\n".join(
                [
                    "AWS4-HMAC-SHA256",
                    stamp,
                    scope,
                    hashlib.sha256(req.encode()).hexdigest(),
                ]
            )
            spec[method] = path + "?" + q + "&X-Amz-Signature=" + mac(k, data).hex()
        out[key] = spec
    print(json.dumps(out))


if __name__ == "__main__":
    main()
