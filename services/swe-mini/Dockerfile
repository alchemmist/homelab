FROM node:22-bookworm-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee AS node
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
RUN set -eux; \
    rm -f /etc/apt/sources.list.d/debian.sources; \
    printf '%s\n' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20260101T000000Z bookworm main' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/20260101T000000Z bookworm-security main' \
      > /etc/apt/sources.list; \
    apt-get -o Acquire::Retries=3 update; \
    DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
      git=1:2.39.5-0+deb12u3 \
      curl=7.88.1-10+deb12u15 \
      make=4.3-4.1 \
      build-essential=12.9 \
      ca-certificates=20250419~deb12u2 \
      procps=2:4.0.2-3; \
    rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
WORKDIR /app
COPY requirements.txt /app/requirements.txt
# Keep large dependency/browser payloads in separate registry blobs. A single
# combined layer is costly to retransmit over the observed slow CI upload path.
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
RUN playwright install-deps chromium && rm -rf /var/lib/apt/lists/*
RUN playwright install --only-shell chromium && chmod -R a+rX /opt/browsers
RUN useradd -u 1000 -m agent
COPY policy.py worker.py controller.py selftest.py /app/
USER 1000:1000
RUN python /app/selftest.py
CMD ["python", "/app/controller.py"]
