# Build and pin the resulting digest before activation; never use a mutable image in production.
FROM python:3.13-alpine@sha256:7984cf56ceaddebe4fefeb75d64000b9f45d8b77b11a09b24524da6cdc3af0c8
WORKDIR /app
COPY gateway.py /app/gateway.py
# Source archives may be mode0600; runtime uid must read code, never write it.
RUN chmod 0444 /app/gateway.py
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "/app/gateway.py"]
