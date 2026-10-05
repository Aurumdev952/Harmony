#!/bin/bash
# Entrypoint of the web image: run the command as the unprivileged zenysis user.
#
# Images before WP-3b ran as root, so on an existing host the bind-mounted static
# files, logs and uploads are owned by root. Started as root, this hands the paths
# the app writes to zenysis, copies the MinIO client config mounted at /root/.mc
# (unreadable to zenysis) into zenysis's home, and then drops root for good.
# Started as any other user (`user:` in Compose), it runs the command unchanged.
set -euo pipefail

APP_USER=zenysis
APP_HOME=/home/zenysis

if (( EUID != 0 )); then
  exec "$@"
fi

# hand_over <dir>: chown everything under <dir> that zenysis does not own yet.
hand_over() {
  if [[ -d $1 ]]; then
    find "$1" -xdev ! -user "$APP_USER" -exec chown -h "$APP_USER:$APP_USER" {} +
  fi
}

if [[ -d /data/output ]]; then
  chown "$APP_USER:$APP_USER" /data/output
  shopt -s nullglob
  logs=(/data/output/*.log*)
  if (( ${#logs[@]} )); then
    chown -h "$APP_USER:$APP_USER" "${logs[@]}"
  fi
fi
hand_over /data/output/zenysis_static
hand_over /zenysis/uploads

if [[ -f /root/.mc/config.json ]]; then
  install -d -o "$APP_USER" -g "$APP_USER" -m 700 "$APP_HOME/.mc"
  install -o "$APP_USER" -g "$APP_USER" -m 600 /root/.mc/config.json "$APP_HOME/.mc/config.json"
fi

export HOME="$APP_HOME" USER="$APP_USER"
exec setpriv --reuid="$APP_USER" --regid="$APP_USER" --init-groups --inh-caps=-all --no-new-privs -- "$@"
