FROM ubuntu:jammy-20260924.1@sha256:5ec03bb3441e8b0bf3b4f9cd4629a1ae763010dc3035bb8da3ae6cf026486401 AS downloader
ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update \
    && apt-get -y install --no-install-recommends software-properties-common gpg gpg-agent \
    && apt-get -y install --no-install-recommends \
    # build-essential: is needed for building proj.
    build-essential \
    # ca-certificates: is needed for downloading files.
    ca-certificates \
    # wget: is used to download files need to build this image.
    wget \
    # cmake: is needed for building proj.
    cmake \
    # sqlite3: required for building proj.
    sqlite3 \
    # libsqlite3-dev: required for building proj.
    libsqlite3-dev \
    # libtiff-dev: is needed for building proj.
    libtiff-dev \
    # libcurl4-openssl-dev: is needed for building proj.
    libcurl4-openssl-dev \
    # python3: is needed for building proj.
    python3 \
    && update-ca-certificates \
    && apt-get clean \
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

FROM ubuntu:jammy-20260924.1@sha256:5ec03bb3441e8b0bf3b4f9cd4629a1ae763010dc3035bb8da3ae6cf026486401
ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update \
    && apt-get -y upgrade \
    && apt-get -y install --no-install-recommends software-properties-common gpg gpg-agent \
    && add-apt-repository 'ppa:deadsnakes/ppa' \
    && apt-get update \
    && apt-get -y install --no-install-recommends \
    # git: is needed for pip install
    git \
    # build-essential: is needed for building proj and building some other dependencies.
    build-essential \
    # wget: may be used in a pipeline step to download files.
    wget \
    # cmake: is needed for installing proj.    
    cmake \
    # curl: may be used in a pipeline step.
    curl \
    # sqlite: is needed for building proj?
    sqlite3 \    
    # libsqlite3-dev: required for building proj.
    libsqlite3-dev \
    # libtiff-dev: is needed for building proj.
    libtiff-dev \
    # libcurl4-openssl-dev: is needed for building proj.
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
    # ca-certificates: is needed for downloading files.
    ca-certificates \
    postgresql-client \
    # lz4: used extensively in the pipeline for compressing/decompressing data.
    lz4 \
    libyaml-dev \
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
    # libproj-dev: is needed for proj.
    libproj-dev \
    # liblapack-dev: TODO: not sure if this is required.
    liblapack-dev \
    # vim: very useful for debugging when connecting to the container.
    vim \
    # pypy3: is needed for installing the pypy3 venv, used by the pipeline.
    pypy3 \
    # pypy3-dev: is needed for installing some dependencies.
    pypy3-dev \
    # pypy3-venv: is needed for installing venv
    pypy3-venv \
    # python3: is needed for installing the cpython venv, used by the pipeline.
    # python3-dev: is needed for installing some dependencies.
    python3.9-dev \
    # python3-pip: is needed for installing dependencies.
    python3-pip \
    # python3-venv: is needed for installing the cpython venv, used by the pipeline.
    python3.9-venv \
    # proj-bin: is needed for installing proj.
    proj-bin \
    # unzip is used by some integrations to de-compress files.
    unzip \
    && update-ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install minio client.
# Minio is used to copy files to and from S3 compatible object storage.
COPY --chmod=755 --from=downloader /usr/local/bin/mc /usr/local/bin/mc

WORKDIR /zenysis
# Best practice not to use root in Docker containers:
# Create a system user 'zenysis', with home directory '/home/zenysis'
# -r, --system: Create a system account
# -m, --create-home: Create the user's home directory
# -d, --home-dir: Home directory of the new account
RUN groupadd zenysis && useradd -g zenysis -rm -d /home/zenysis zenysis && chown -R zenysis /zenysis
USER zenysis

# CPython
# Update setup and create venv.
# NOTE: We can't easily create a venv in a seperate Docker stage, and then
#       copy it here. Various links will be broken, and the venv will not
#       work.
RUN python3.9 -m venv venv
# Install dependencies.
COPY requirements.txt requirements-pipeline.txt ./
# wheel 0.43.0 HAS to be installed prior to installing requirments. If changing version here, also
# change in requirements.txt.
RUN . venv/bin/activate \
    && python -m pip install wheel==0.43.0 \
    && python -m pip install --no-build-isolation --verbose -r requirements.txt -r requirements-pipeline.txt

# PyPy
# Update setup and create venv.
# NOTE: We can't simply create a venv in a seperate Docker stage, and then
#       copy it here. Various links will be broken, and the venv will not
#       work. It would however be cleaner, and result in a more lean image.
# TODO: Investigate what it would take to have venv happen in a different
#       build stage and copy it here. It would result in a leaner, cleaner
#       image.
RUN pypy3 -m venv venv_pypy3
# Install pypy dependencies.
# wheel 0.43.0 HAS to be installed prior to installing requirments. If changing version here, also
# change in requirements.txt.
RUN . venv_pypy3/bin/activate \
    && python -m pip install wheel==0.43.0 \
    && pypy -m pip install --no-build-isolation --verbose -r requirements.txt -r requirements-pipeline.txt

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

ENV ZEN_HOME /zenysis
ENV R77_SRC_ROOT /zenysis
ENV PYTHONPATH /zenysis
ENV USER zenysis