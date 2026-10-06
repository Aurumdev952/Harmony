# syntax=docker/dockerfile:1.27.1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
# Export renderer sidecar (WP-1h). Build from the repository root:
#   docker build -f docker/renderer/Dockerfile .
# Dockerfile.dockerignore limits the context to harmony/worker/renderer.

# Ships Chromium, its libraries and the pwuser account, but not the Python package.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble@sha256:72bd171a9ffc2b4b59532aaa6210e21014d07093120dc25528870c0b840da1f0

# playwright must match the base image's driver. It and its dependencies are pinned
# by hash in requirements.txt and installed without the resolver.
RUN --mount=type=bind,source=harmony/worker/renderer/requirements.txt,target=/tmp/requirements.txt \
    pip install --no-cache-dir --no-deps --require-hashes -r /tmp/requirements.txt

WORKDIR /app
# Root-owned, so the renderer cannot change its own code.
COPY --link harmony/worker/renderer /app/harmony/worker/renderer

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RENDERER_PORT=8080

USER pwuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"]
ENTRYPOINT ["python", "-m", "harmony.worker.renderer"]
