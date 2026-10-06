# syntax=docker/dockerfile:1.27.1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
# This Dockerfile used for local development.
# Not to be confused with what we used in production.
# The development environment is very different from production w.r.t. tools
# installed etc.
# This Dockerfile installs dependencies for the web app and the pipeline.
FROM ubuntu:jammy-20260924.1@sha256:5ec03bb3441e8b0bf3b4f9cd4629a1ae763010dc3035bb8da3ae6cf026486401 AS downloader
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get clean \
    && apt-get -y install --no-install-recommends \
    ca-certificates \
    wget \
    unzip \
    xz-utils \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Download minio client. dl.min.io answers 410 Gone since MinIO archived mc, so
# fetch the last GitHub release and verify it.
ARG MC_RELEASE=RELEASE.2025-08-13T08-35-41Z
RUN case $(uname -m) in \
    "x86_64") arch=amd64; sha256=01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891 ;; \
    "aarch64") arch=arm64; sha256=14c8c9616cfce4636add161304353244e8de383b2e2752c0e9dad01d4c27c12c ;; \
    *) echo "unsupported architecture $(uname -m)" >&2; exit 1 ;; \
    esac; \
    wget "https://github.com/minio/mc/releases/download/${MC_RELEASE}/mc.linux-${arch}.${MC_RELEASE}" -O /usr/local/bin/mc \
    && echo "${sha256}  /usr/local/bin/mc" | sha256sum -c -

# Download flow
RUN case $(uname -m) in \
    "x86_64") asset=flow-linux64-v0.200.0.zip; sha256=589e98143c1b24986f389184b1d6471d8bbe0111bcbc4b162d1932e9c7d6448c ;; \
    "aarch64") asset=flow-linux-arm64-v0.200.0.zip; sha256=5aec3c8b8e23be1acd64b46804626feee1f32a420de1979534e3da2774bee046 ;; \
    *) echo "unsupported architecture $(uname -m)" >&2; exit 1 ;; \
    esac; \
    wget "https://github.com/facebook/flow/releases/download/v0.200.0/${asset}" -O /tmp/flow.zip \
    && echo "${sha256}  /tmp/flow.zip" | sha256sum -c - \
    && cd /tmp && unzip flow.zip && mv flow/flow /usr/local/bin/flow && rm -rf flow*;

# Download Node.js, the release the client image (docker/web/Dockerfile_web-client)
# and CI's lint job use. NodeSource's Node 14 repository no longer verifies (its
# signing key was replaced), which broke this image.
ARG NODE_VERSION=v18.17.1
RUN case $(uname -m) in \
    "x86_64") arch=x64; sha256=07e76408ddb0300a6f46fcc9abc61f841acde49b45020ec4e86bb9b25df4dced ;; \
    "aarch64") arch=arm64; sha256=3f933716a468524acb68c2514d819b532131eb50399ee946954d4a511303e1bb ;; \
    *) echo "unsupported architecture $(uname -m)" >&2; exit 1 ;; \
    esac; \
    wget "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-${arch}.tar.xz" -O /tmp/node.tar.xz \
    && echo "${sha256}  /tmp/node.tar.xz" | sha256sum -c - \
    && mkdir /opt/node && tar -xJf /tmp/node.tar.xz -C /opt/node --strip-components=1 \
    && rm /tmp/node.tar.xz

FROM ubuntu:jammy-20260924.1@sha256:5ec03bb3441e8b0bf3b4f9cd4629a1ae763010dc3035bb8da3ae6cf026486401

RUN apt-get update \
    && apt-get -y upgrade \
    && apt-get -y install --no-install-recommends \
    build-essential \
    git \
    cmake \
    curl \
    libtiff-dev \
    sqlite3 \
    wget \
    libsqlite3-dev \
    libcurl4-openssl-dev \
    gcc \
    libpq-dev \
    libnetcdf-dev \
    gfortran \
    libgeos-dev \
    libyaml-dev \
    libffi-dev \
    libbz2-dev \
    apt-transport-https \
    ca-certificates \
    postgresql-client \
    lz4 \
    proj-bin \
    libproj-dev \
    libyaml-dev \
    # dtach: emulates the detach feature of screen, not sure where it's used.
    dtach \
    # jq: command-line JSON processor.
    jq \
    # libssel-dev: TODO: not sure if this is required.
    libssl-dev \
    # liblz4-tool: TODO: not sure if this is required in addition to lz4.
    liblz4-tool \
    # pigz: faster gzip implementation.
    pigz \
    # libopenblas-dev: TODO: not sure if this is required.
    libopenblas-dev \
    # liblapack-dev: TODO: not sure if this is required.
    liblapack-dev \
    # watchman warns not to use Ubuntu supplied version, but the current version
    # doesn't build on arm64, and they don't provide and arm64 .deb package.
    # watchman is used by translations to watch files.
    watchman \
    vim \
    # python3: node-gyp runs on it when `yarn install` builds native modules
    # (node-pty). The app runs on the uv-managed CPython 3.13 in /app/venv.
    python3 \
    && update-ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=downloader /opt/node /opt/node
ENV PATH=/opt/node/bin:$PATH

# uv, and through it CPython 3.13, the interpreter the images and CI run. uv checks
# the downloaded interpreter against the checksum it ships with.
COPY --from=ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 /uv /uvx /usr/local/bin/
ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
RUN uv python install 3.13.16

# Install minio client
COPY --chmod=755 --from=downloader /usr/local/bin/mc /usr/local/bin/mc

WORKDIR /app

# Every dependency group from uv.lock (web, pipeline and dev) in /app/venv, where
# the dev scripts activate it. docker-compose.dev.yaml keeps it in a volume.
ENV UV_PROJECT_ENVIRONMENT=/app/venv
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-install-project --python 3.13.16

# Install flow.
COPY --from=downloader /usr/local/bin/flow /usr/local/bin/flow

# The yarn release the client image ships.
RUN npm install -g yarn@1.22.19

COPY package.json yarn.lock ./
RUN yarn install

ENV ZEN_HOME=/app

EXPOSE 5000

CMD [ "./docker/dev/scripts/start_web.sh" ]