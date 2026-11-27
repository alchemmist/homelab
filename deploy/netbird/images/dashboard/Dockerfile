# Security rebuild of the deployed dashboard. Keep the upstream entrypoint and user.
FROM docker.io/netbirdio/dashboard:v2.98.0@sha256:3e8a714e2966f96201b817657cf5b6e4304b947b88341fe99639214fb440ea9c
RUN apk upgrade --no-cache libxml2 && apk info --installed 'libxml2>=2.13.9-r3'
