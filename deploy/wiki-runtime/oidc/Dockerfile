FROM --platform=linux/amd64 ghcr.io/alchemmist/hugo-docs-wiki@sha256:56b24ca70f7ebcb5c3d4844c0e5ec5b779416f74f891be5b24807f65e8878b7e
USER root
RUN pip install --no-cache-dir Authlib==1.6.6 itsdangerous==2.2.0 httpx==0.28.1
COPY auth-edits.json apply-auth-patch.py /tmp/
RUN python /tmp/apply-auth-patch.py && rm /tmp/auth-edits.json /tmp/apply-auth-patch.py
COPY oidc.py /app/runtime/oidc.py
USER 1000:1000
