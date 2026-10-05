#!/usr/bin/env bash
# WP-2g unit 5: start the production nginx service against a stub upstream, send
# requests, and check nginx's access lines are JSON carrying the upstream's request
# id, with no query string, and that the browser-share script reads them.
# Uses dummy values only; never the repository .env.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
WT=$(cd "$HERE/../../../.." && pwd)
OUT=${OUT:-/tmp/wp2g}
mkdir -p "$OUT"
ENV_FILE="$OUT/nginx_check.env"
# `extends` interpolates the whole base file, so its required variables need
# placeholders even though only nginx starts.
{
  printf 'ZEN_ENV=zz\nDOCKER_SOCKET=%s\n' "${DOCKER_SOCKET:-/run/user/$(id -u)/docker.sock}"
  printf '%s=placeholder-not-a-secret\n' REDIS_PASSWORD DEFAULT_SECRET_KEY JWT_SECRET_KEY \
    HASURA_ADMIN_SECRET
  printf '%s=\n' EMAIL_HOST EMAIL_HOST_USER EMAIL_HOST_PASSWORD DATABASE_URL DRUID_HOST \
    MAPBOX_ACCESS_TOKEN OBJECT_STORAGE_ALIAS WEB_VIRTUAL_HOST
  printf 'MC_CONFIG_PATH=/tmp/wp2g-mc\n'
} > "$ENV_FILE"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$HERE/unit5_nginx_check.yaml")

"${COMPOSE[@]}" up -d --quiet-pull
for _ in $(seq 60); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: wp2g.check.invalid' http://127.0.0.1:18080/ready)
  [ "$code" = 200 ] && break
  sleep 1
done
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
curl -s -o /dev/null -A "$UA" -H 'Host: wp2g.check.invalid' 'http://127.0.0.1:18080/overview?token=SEKRIT1'
curl -s -o /dev/null -A 'Mozilla/5.0 "quoted" (X11; Linux x86_64; rv:115.0) Gecko/20100101 Firefox/115.0' \
  -H 'Host: wp2g.check.invalid' 'http://127.0.0.1:18080/dashboard?api_key=SEKRIT2'
sleep 1
"${COMPOSE[@]}" logs --no-log-prefix nginx > "$OUT/nginx_check_raw.txt" 2>&1
"${COMPOSE[@]}" exec -T nginx sh -c 'grep -A1 "^log_format vhost" /etc/nginx/conf.d/default.conf' > "$OUT/nginx_check_log_format.txt"
"${COMPOSE[@]}" down
# nginx-proxy's forego prefixes each line with `nginx.1 | ` in ANSI colours.
grep -o '{"timestamp".*' "$OUT/nginx_check_raw.txt" > "$OUT/nginx_check_access.jsonl"

uvx --python 3.13 python - "$OUT/nginx_check_access.jsonl" <<'EOF'
import json
import sys

lines = open(sys.argv[1]).read().splitlines()
entries = [json.loads(line) for line in lines]
by_path = {e['http']['path']: e for e in entries}
problems = []
for path, ua_part in (('/overview', 'Chrome/126'), ('/dashboard', '"quoted"')):
    entry = by_path.get(path)
    if entry is None:
        problems.append(f'no line for {path}')
        continue
    if entry['request_id'] != 'upstream-' + path.strip('/'):
        problems.append(f'{path}: request_id {entry["request_id"]!r}')
    if ua_part not in entry['user_agent']:
        problems.append(f'{path}: user_agent {entry["user_agent"]!r}')
    expected = {'logger': 'nginx.access', 'level': 'INFO', 'deployment': 'zz'}
    if {k: entry[k] for k in expected} != expected:
        problems.append(f'{path}: {entry}')
    if not isinstance(entry['http']['status'], int):
        problems.append(f'{path}: status not a number')
raw = '\n'.join(lines)
print('json access lines', len(entries))
print('query secrets present', 'SEKRIT' in raw)
print('problems', problems)
sys.exit(1 if problems or 'SEKRIT' in raw else 0)
EOF
STATUS=$?
uv run --project "$WT" "$WT/prod/browser_share/browser_share.py" --deployment zz "$OUT/nginx_check_raw.txt"
exit $STATUS
