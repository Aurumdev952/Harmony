# Proposed docker/renderer/Dockerfile (WP-1h; infra owns the final file).
# Build from the repository root:
#   docker build -f docker/renderer/Dockerfile -t harmony-renderer .
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble@sha256:72bd171a9ffc2b4b59532aaa6210e21014d07093120dc25528870c0b840da1f0

# The base image has Chromium and its libraries but not the Python package; install
# the one version matching its driver, hash-pinned, with no resolver.
COPY harmony/worker/renderer/requirements.txt /tmp/renderer-requirements.txt
RUN pip install --no-cache-dir --no-deps --require-hashes \
        -r /tmp/renderer-requirements.txt \
    && rm /tmp/renderer-requirements.txt

WORKDIR /app
COPY harmony/worker/renderer /app/harmony/worker/renderer

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RENDERER_PORT=8080

USER pwuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"]
ENTRYPOINT ["python", "-m", "harmony.worker.renderer"]
