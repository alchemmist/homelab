FROM python:3.13-alpine@sha256:7984cf56ceaddebe4fefeb75d64000b9f45d8b77b11a09b24524da6cdc3af0c8
COPY assets/ /opt/spi-tokenizer/
RUN echo '38337540fbbddff8e999d59970f3c6f35a82de10053206a7562f1ea02d046fa5  /opt/spi-tokenizer/tokenizers-0.22.2-cp39-abi3-musllinux_1_2_x86_64.whl' | sha256sum -c - && python -m pip install --no-index --no-deps /opt/spi-tokenizer/*.whl && rm /opt/spi-tokenizer/*.whl
COPY library_manifest.py /tmp/library_manifest.py
RUN python /tmp/library_manifest.py && rm /tmp/library_manifest.py
COPY app/ /app/
ENV TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1 PYTHONPATH=/app
RUN python -c 'from local_token_counter import LocalCounter; LocalCounter()'
CMD ["python", "-B", "/app/service.py"]
