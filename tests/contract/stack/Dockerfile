# The contract stack runs the production web-server image with one change:
# bcrypt is held below 4.1. requirements.txt leaves it unpinned, and with
# bcrypt 5 passlib 1.7.4 raises "password cannot be longer than 72 bytes" on
# every hash and verify, so a fresh build cannot create users or log in.
# Remove this file once requirements pin bcrypt (request recorded in WP-2c).
ARG BASE_IMAGE=harmony-wp2c-web-server:base
FROM ${BASE_IMAGE}
RUN pip install --no-cache-dir bcrypt==4.0.1
