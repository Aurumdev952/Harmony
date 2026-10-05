# syntax=docker/dockerfile:1.27.1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e

# Download the MinIO client. dl.min.io answers 410 Gone since MinIO archived mc, so
# fetch the last GitHub release and verify it.
FROM python:3.13.16-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed AS downloader
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt,sharing=locked \
  rm -f /etc/apt/apt.conf.d/docker-clean && \
  apt-get update && \
  apt-get install --no-install-recommends -y ca-certificates wget
ARG MC_RELEASE=RELEASE.2025-08-13T08-35-41Z
RUN case $(uname -m) in \
    "x86_64") arch=amd64; sha256=01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891 ;; \
    "aarch64") arch=arm64; sha256=14c8c9616cfce4636add161304353244e8de383b2e2752c0e9dad01d4c27c12c ;; \
    *) echo "unsupported architecture $(uname -m)" >&2; exit 1 ;; \
    esac; \
    wget "https://github.com/minio/mc/releases/download/${MC_RELEASE}/mc.linux-${arch}.${MC_RELEASE}" -O /usr/local/bin/mc \
    && echo "${sha256}  /usr/local/bin/mc" | sha256sum -c -


# Python dependencies, built from uv.lock: the shared dependencies plus the
# `pipeline` group. Pipeline steps run on this CPython; there is no PyPy.
FROM python:3.13.16-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed AS build

COPY --from=ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 /uv /bin/uv

# git fetches the two git dependencies (Flask-Potion, pylib); gcc builds the C
# speedups of the sdists that have them (MarkupSafe, SQLAlchemy).
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt,sharing=locked \
  rm -f /etc/apt/apt.conf.d/docker-clean && \
  apt-get update && \
  apt-get install --no-install-recommends -y git gcc libc6-dev

# The venv keeps the old image's path, /zenysis/venv: docker/entrypoint_pipeline.sh,
# `make bash-pipeline` and deployments' pipeline scripts source venv/bin/activate.
ENV UV_COMPILE_BYTECODE=1 \
  UV_LINK_MODE=copy \
  UV_PYTHON_DOWNLOADS=0 \
  UV_PROJECT_ENVIRONMENT=/zenysis/venv

WORKDIR /zenysis
RUN --mount=type=cache,target=/root/.cache/uv \
  --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
  --mount=type=bind,source=uv.lock,target=uv.lock \
  uv sync --locked --no-install-project --no-default-groups --group pipeline


FROM python:3.13.16-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed

# Command-line tools the previous image carried. Steps in this repository call
# lz4, lz4cat, pigz, psql, mc, curl and jq; the rest stay for deployments' own
# pipeline directories. Compilers, -dev headers and PyPy are gone: every Python
# dependency is installed from uv.lock in the build stage.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt,sharing=locked \
  rm -f /etc/apt/apt.conf.d/docker-clean && \
  apt-get update && \
  apt-get install --no-install-recommends -y \
    # ca-certificates: HTTPS downloads.
    ca-certificates \
    # curl, wget: may be used in a pipeline step to download files.
    curl \
    wget \
    git \
    # jq: command-line JSON processor.
    jq \
    # lz4 (with lz4cat), pigz: the pipeline's compression tools.
    lz4 \
    pigz \
    # postgresql-client: psql in pipeline steps.
    postgresql-client \
    proj-bin \
    sqlite3 \
    # unzip: used by some integrations to decompress files.
    unzip \
    # vim: very useful for debugging when connecting to the container.
    vim

COPY --chmod=755 --from=downloader /usr/local/bin/mc /usr/local/bin/mc

WORKDIR /zenysis
# Best practice not to use root in Docker containers:
# Create a system user 'zenysis', with home directory '/home/zenysis'
# -r, --system: Create a system account
# -m, --create-home: Create the user's home directory
# -d, --home-dir: Home directory of the new account
RUN groupadd zenysis && useradd -g zenysis -rm -d /home/zenysis zenysis && chown -R zenysis /zenysis
USER zenysis

COPY --link --from=build /zenysis/venv venv
ENV PATH=/zenysis/venv/bin:$PATH

# Copy only what the pipeline needs.
COPY pipeline ./pipeline
COPY util ./util
COPY data ./data
COPY docker/entrypoint_pipeline.sh ./docker/entrypoint_pipeline.sh
COPY config ./config
COPY models ./models
COPY log ./log
# TODO: Why does pipeline need web?
COPY web ./web
COPY db ./db
COPY scripts ./scripts

ENV ZEN_HOME=/zenysis \
  R77_SRC_ROOT=/zenysis \
  PYTHONPATH=/zenysis \
  USER=zenysis
