# WP-1h unit 5: renderer image and container check

Date: 2026-10-04. The image was built from `infra-request/Dockerfile` with a context of only `harmony/worker/renderer` (tag `harmony-renderer:wp1h`). It ran with the hardening proposed in `infra-request/compose.renderer.yaml`, on a network created with `docker network create --internal`:

```
docker run -d --name wp1h-renderer --network wp1h-render --read-only \
  --tmpfs /tmp --tmpfs /home/pwuser --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --security-opt seccomp=infra-request/seccomp_profile.json \
  --shm-size 1g -e RENDERER_ALLOWED_ORIGIN=http://web:5000 harmony-renderer:wp1h
```

| Check | Result |
|---|---|
| Base image | `mcr.microsoft.com/playwright/python:v1.63.0-noble@sha256:72bd171a9ffc2b4b59532aaa6210e21014d07093120dc25528870c0b840da1f0`. `docker buildx imagetools inspect` of the tag gives the same index digest. |
| Python dependencies | `pip install --no-deps --require-hashes` of `harmony/worker/renderer/requirements.txt` (playwright 1.63.0, greenlet, pyee, typing-extensions) |
| Image HEALTHCHECK | `healthy`. `docker inspect` shows `user=pwuser readonly=true`. |
| Process user | `docker exec wp1h-renderer id` gives `uid=1001(pwuser) gid=1001(pwuser)` |
| `/healthz` from a peer on the network | `200 b'ok'` |
| Off-origin render request (`http://169.254.169.254/latest/`) | `400 {"error": "invalid_request"}`. Log line: `{"event": "render", "reason": "url is not on the allowed origin", "error": "invalid_request", "duration_ms": 0, "status": 400}`. Neither the URL nor the token is logged. |
| Egress by IP (`http://1.1.1.1/`) | `OSError: [Errno 101] Network is unreachable` |
| Egress by name (`https://api.urlbox.io/`) | `socket.gaierror: [Errno -3] Temporary failure in name resolution` |

The container and network were removed afterwards. The in-image test suite for the same image is in `unit-4a-egress-and-sandbox.md` (110 passed).
