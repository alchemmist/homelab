# Build and pin the resulting digest before activation; never use a mutable image in production.
FROM python:3.13-alpine
WORKDIR /app
COPY gateway.py /app/gateway.py
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "/app/gateway.py"]
