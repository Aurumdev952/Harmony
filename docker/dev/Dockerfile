# syntax=docker/dockerfile:1.27.1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
# This Dockerfile used for local development.
# Not to be confused with what we used in production.
# The development environment is very different from production w.r.t. tools
# installed etc.
# This Dockerfile installs dependencies for the web app and the pipeline.
FROM ubuntu:jammy-20260924.1@sha256:5ec03bb3441e8b0bf3b4f9cd4629a1ae763010dc3035bb8da3ae6cf026486401 AS downloader
ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update \
    && apt-get clean \
    && apt-get -y install --no-install-recommends \
    ca-certificates \
    wget \
    unzip \
    bzip2 \
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

# Download pypy
RUN case $(uname -m) in \
    "x86_64") dist=pypy3.9-v7.3.11-linux64; sha256=d506172ca11071274175d74e9c581c3166432d0179b036470e3b9e8d20eae581 ;; \
    "aarch64") dist=pypy3.9-v7.3.11-aarch64; sha256=09175dc652ed895d98e9ad63d216812bf3ee7e398d900a9bf9eb2906ba8302b9 ;; \
    *) echo "unsupported architecture $(uname -m)" >&2; exit 1 ;; \
    esac; \
    wget "https://downloads.python.org/pypy/${dist}.tar.bz2" -O /tmp/pypy.tar.bz2 \
    && echo "${sha256}  /tmp/pypy.tar.bz2" | sha256sum -c - \
    && cd /tmp && tar -xf pypy.tar.bz2 \
    && mv "/tmp/${dist}" /opt/pypy3.9-v7.3.11 \
    && rm /tmp/pypy.tar.bz2;

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
    && update-ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Bring in the exact version of node we currently use:
RUN curl -sL https://deb.nodesource.com/setup_14.x | bash - \
    && apt-get install -y nodejs

# Bring in the exact version of CPython we currently use:
ADD --checksum=sha256:1ad539e9dbd2b42df714b69726e0693bc6b9d2d2c8e91c2e43204026605140c5 https://www.python.org/ftp/python/3.9.16/Python-3.9.16.tgz /tmp/Python-3.9.16.tgz
RUN cd /tmp && tar -xvf Python-3.9.16.tgz && cd Python-3.9.16 \
    && ./configure --prefix=/opt/python/3.9.16/ --enable-optimizations --with-lto --with-computed-gotos --with-system-ffi \
    && make -j "$(nproc)" \
    && make altinstall \
    && rm -rf /tmp/Python-3.9.16*

# Install minio client
COPY --chmod=755 --from=downloader /usr/local/bin/mc /usr/local/bin/mc

WORKDIR /app

# CPython
# Create venv
RUN /opt/python/3.9.16/bin/python3.9 -m venv venv
# Install dependencies
COPY requirements.txt requirements-web.txt requirements-dev.txt requirements-pipeline.txt ./
RUN . venv/bin/activate \
    && python -m pip install wheel==0.43.0 \
    && python -m pip install --no-build-isolation -r requirements.txt -r requirements-web.txt -r requirements-dev.txt -r requirements-pipeline.txt

# PyPy
# Install pypy
COPY --from=downloader /opt/pypy3.9-v7.3.11 /opt/pypy3.9-v7.3.11
# Update setup and create venv
RUN /opt/pypy3.9-v7.3.11/bin/pypy3 -m ensurepip \
    && /opt/pypy3.9-v7.3.11/bin/pypy3 -m venv venv_pypy3
# Install pypy dependencies
RUN . venv_pypy3/bin/activate \
    && pypy3 -m pip install wheel==0.43.0 \
    && pypy3 -m pip install --no-build-isolation -r requirements.txt -r requirements-pipeline.txt

# Install flow.
COPY --from=downloader /usr/local/bin/flow /usr/local/bin/flow

RUN npm install -g yarn

COPY package.json yarn.lock ./
RUN yarn install

ENV ZEN_HOME /app

EXPOSE 5000

CMD [ "./docker/dev/scripts/start_web.sh" ]