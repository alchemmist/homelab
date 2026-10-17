FROM node:22.16.0-alpine AS frontend
WORKDIR /src
COPY wiki/package.json wiki/package-lock.json ./
RUN npm ci --ignore-scripts
COPY wiki/editor ./editor
RUN npm run build

FROM ghcr.io/gohugoio/hugo:v0.167.0 AS template
USER root
WORKDIR /src
COPY wiki/go.mod wiki/go.sum wiki/hugo.toml ./
RUN hugo mod vendor
COPY wiki/content ./content
COPY wiki/layouts ./layouts
COPY wiki/static ./static
COPY wiki/assets ./assets
COPY --from=frontend /src/assets/wiki-editor.js ./assets/wiki-editor.js
RUN hugo --minify --panicOnWarning --destination /tmp/public

FROM python:3.12-slim
ARG TARGETARCH=amd64
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client ca-certificates curl && curl -fsSL --retry 3 "https://github.com/gohugoio/hugo/releases/download/v0.167.0/hugo_0.167.0_linux-${TARGETARCH}.tar.gz" | tar -xz -C /usr/local/bin hugo && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* && useradd --uid 1000 --create-home editor && mkdir /data && chown editor:editor /data
WORKDIR /app
COPY wiki-editor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY wiki-editor/*.py ./
COPY --from=template /src /opt/wiki
USER 1000:1000
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-proxy-headers"]
