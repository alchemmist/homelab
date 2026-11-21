FROM python:3.12-slim@sha256:05a994d2344eb364cc186910f4fc8786a38215f39f00d0acc25bff33a08f4177

WORKDIR /opt/worker
COPY worker-requirements.txt /opt/worker/requirements.txt
RUN python -m pip install --no-cache-dir -r /opt/worker/requirements.txt \
    && python -m pip uninstall -y pip \
    && mkdir -p /opt/agent /opt/grader \
    && chmod 755 /opt/agent /opt/grader \
    && rm -rf /root/.cache /tmp/*
USER 65534:65534
WORKDIR /workspace
CMD ["python", "-c", "import fastapi, jsonschema, playwright, uvicorn, pydantic"]
