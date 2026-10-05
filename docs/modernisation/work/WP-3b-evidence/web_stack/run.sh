#!/usr/bin/env bash
# WP-3b unit 3 runtime check: the web image as web and worker, with the prod overlay's
# bind mounts pre-filled the way a root-run image left them on an existing host.
# Usage: [NS=local/wp3b-infra3] TAG=u3|base run.sh up | probe | down   (images $NS/harmony-web:$TAG)
set -uo pipefail
S=$(cd "$(dirname "$0")" && pwd -P)
TREE=$(cd "$S/../../../../.." && pwd -P)
WORK=${WORK:-/tmp/wp3b-stack}

TAG="${TAG:-u3}"
P="wp3b-infra3-stack-$TAG"
D="$WORK/data-$TAG"
mkdir -p "$WORK"
ENV_FILE="$WORK/stack-$TAG.env"
sed -e "s|^STACK_DIR=.*|STACK_DIR=$S|" -e "s|^DOCKER_TAG=.*|DOCKER_TAG=$TAG|" -e "s|^DOCKER_NAMESPACE=.*|DOCKER_NAMESPACE=${NS:-local/wp3b-infra3}|" -e "s|/tmp/wp3b/stack/data|$D|g" -e "s|/tmp/wp3b/stack/nginx_vhost|$WORK/nginx_vhost|" "$S/stack.env" > "$ENV_FILE"
compose() {
  docker compose -p "$P" --project-directory "$TREE" --env-file "$ENV_FILE" \
    -f "$TREE/docker-compose.yaml" -f "$TREE/docker-compose.local.yaml" \
    -f "$TREE/docker-compose.prod.yaml" -f "$S/overlay.yaml" "$@"
}
ADMIN=admin@wp3b.invalid
ADMIN_PASSWORD=wp3b-stack-Admin-Password-1

case "$1" in
up)
  # Rootless Docker: files the host user owns appear as root's inside containers,
  # like the files an old root image wrote on a real host.
  rm -rf "$D"
  mkdir -p "$D/output/zenysis_static/build" "$D/output/logs" "$D/ubuntu/uploads/2024" "$D/ubuntu/.mc"
  echo stale > "$D/output/zenysis_static/build/stale.js"
  echo 'old line' > "$D/output/zenysis.log"
  echo upload > "$D/ubuntu/uploads/2024/report.csv"
  printf '{"version": "10", "aliases": {"wp3b": {"url": "http://minio.invalid", "accessKey": "a", "secretKey": "s", "api": "s3v4", "path": "auto"}}}\n' \
    > "$D/ubuntu/.mc/config.json"
  chmod 600 "$D/ubuntu/.mc/config.json"
  : > "$WORK/nginx_vhost"
  compose up -d --wait --wait-timeout 900 web worker
  echo "up: exit $?"
  compose ps --format 'table {{.Service}}\t{{.Status}}\t{{.Ports}}'
  ;;
probe)
  echo "== processes in web (user pid command)"
  compose exec -T web bash -c 'for p in /proc/[0-9]*; do printf "%s %s %s\n" "$(stat -c %U "$p")" "${p#/proc/}" "$(tr "\0" " " < "$p/cmdline" | cut -c1-100)"; done' | grep -v ' bash -c for p'
  echo "== processes in worker"
  compose exec -T worker bash -c 'for p in /proc/[0-9]*; do printf "%s %s %s\n" "$(stat -c %U "$p")" "${p#/proc/}" "$(tr "\0" " " < "$p/cmdline" | cut -c1-100)"; done' | grep -v ' bash -c for p' | sort | uniq -c -f2 | head -3
  echo "== create an admin with the Makefile's command (compose run through the entrypoint)"
  compose run --rm -T web /bin/bash -c "id -un; ./scripts/create_user.py --username=$ADMIN --password=$ADMIN_PASSWORD --first_name=WP --last_name=3b --site_admin" 2>&1 | grep -v -i 'warning\|warn(' | tail -3
  echo "== HTTP from inside web"
  docker cp "$S/http_probe.py" "$(compose ps -q web)":/tmp/http_probe.py
  compose exec -T web python /tmp/http_probe.py "$ADMIN" "$ADMIN_PASSWORD"
  echo "== ownership in web"
  compose exec -T web bash -c 'ls -ln /data/output /zenysis/uploads/2024 /home/zenysis/.mc 2>&1; test -e /data/output/zenysis_static/build/stale.js && echo "stale.js still there" || echo "stale.js replaced"'
  echo "== worker: beat schedule and mc config"
  compose exec -T worker bash -c 'ls -ln /tmp/celerybeat-schedule /home/zenysis/.mc/config.json /zenysis/celerybeat-schedule 2>&1'
  echo "== errors in the logs"
  compose logs --no-color web worker 2>&1 | grep -E 'ERROR|Traceback|Error:' | grep -v 'getenv' | cut -c1-200 | sort | uniq -c | head
  ;;
down)
  compose --profile donotstart down --remove-orphans
  ;;
esac
