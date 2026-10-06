# The production web-server image with bcrypt held below 4.1, as in WP-2c's
# tests/contract/stack/Dockerfile: with bcrypt 5, passlib 1.7.4 fails every
# hash, so a fresh build cannot create users or log in. Once WP-0b pins
# bcrypt==4.0.1 in requirements.txt this layer is a no-op.
ARG BASE_IMAGE=harmony-perf-web-server:built-by-stack-sh
FROM ${BASE_IMAGE}
RUN pip install --no-cache-dir bcrypt==4.0.1
