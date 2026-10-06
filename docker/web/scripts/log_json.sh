# shellcheck shell=bash
# Sourced by the web container's scripts. The image copies it to /zenysis/log_json.sh.
#
# log_json <message>: print a JSON line like the app's (WP-2g), so
# `docker compose logs web | jq` parses. The logger is the calling script's name.
# Messages are fixed strings without quotes or backslashes.
log_json() {
  printf '{"timestamp":"%s","level":"INFO","logger":"%s","message":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%S.000+00:00)" "${0##*/}" "$1"
}
