FROM ghcr.io/gohugoio/hugo:v0.167.0 AS build
USER root
WORKDIR /src
COPY go.mod go.sum hugo.toml ./
RUN hugo mod graph
COPY . .
ARG SOURCE_SHA=local
RUN hugo --minify --cleanDestinationDir --panicOnWarning --destination /tmp/public \
    && printf '{"source_sha":"%s"}\n' "$SOURCE_SHA" > /tmp/public/version.json \
    && test -f /tmp/public/search-index.json

FROM nginx:1.28.0-alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /tmp/public /usr/share/nginx/html
USER 101:101
EXPOSE 8080
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
