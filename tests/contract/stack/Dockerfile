# The contract stack runs the production web-server image with one change:
# bcrypt is held below 4.1. requirements.txt on main leaves it unpinned, and
# with bcrypt 5 passlib 1.7.4 raises "password cannot be longer than 72 bytes"
# on every hash and verify, so a fresh build cannot create users or log in.
# WP-0b pins bcrypt==4.0.1 in requirements.txt; delete this file and build
# docker/web/Dockerfile_web-server directly once WP-0b is on the branch.
ARG BASE_IMAGE=harmony-contract-web-server:built-by-stack-sh
FROM ${BASE_IMAGE}
RUN pip install --no-cache-dir bcrypt==4.0.1
