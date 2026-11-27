FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir pillow==13.0.0 "psycopg[binary]==3.3.9" boto3==1.44.12 \
 && useradd --uid 1000 --create-home app
COPY src /app/src
COPY ui /app/ui
ENV PYTHONPATH=/app/src
USER 1000
EXPOSE 8080
CMD ["python", "-m", "authwall.server"]
