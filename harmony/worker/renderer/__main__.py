'''Run the renderer service: `python -m harmony.worker.renderer`.'''

import json
import logging
import os

from harmony.worker.renderer.egress import parse_origins
from harmony.worker.renderer.server import RendererSettings, build_server

LOG = logging.getLogger('harmony.worker.renderer')


def settings_from_env() -> RendererSettings:
    egress_proxy = os.environ.get('RENDERER_EGRESS_PROXY') or None
    map_origins = parse_origins(
        os.environ.get('RENDERER_MAP_ORIGINS', 'https://api.mapbox.com')
    )
    if map_origins and egress_proxy is None:
        # Nothing could reach them; refusing them up front fails a map render
        # after the grace period instead of after each failed connection.
        LOG.warning(
            json.dumps({'event': 'no_egress_proxy', 'map_origins': list(map_origins)})
        )
        map_origins = ()
    return RendererSettings(
        allowed_origin=os.environ.get('RENDERER_ALLOWED_ORIGIN', 'http://web:5000'),
        port=int(os.environ.get('RENDERER_PORT', '8080')),
        max_timeout_seconds=float(
            os.environ.get('RENDERER_MAX_TIMEOUT_SECONDS', '120')
        ),
        max_bytes=int(os.environ.get('RENDERER_MAX_BYTES', str(25 * 1024 * 1024))),
        concurrency=int(os.environ.get('RENDERER_CONCURRENCY', '2')),
        max_page_height=int(os.environ.get('RENDERER_MAX_PAGE_HEIGHT', '16384')),
        map_origins=map_origins,
        egress_proxy=egress_proxy,
        blocked_grace_seconds=float(
            os.environ.get('RENDERER_BLOCKED_GRACE_SECONDS', '10')
        ),
        ignored_blocked_hosts=tuple(
            host.strip()
            for host in os.environ.get(
                'RENDERER_IGNORED_BLOCKED_HOSTS', 'events.mapbox.com'
            ).split(',')
            if host.strip()
        ),
    )


def main() -> None:
    # Imported here so the settings can be read without Playwright installed.
    from harmony.worker.renderer.browser import render

    logging.basicConfig(level=logging.INFO, format='%(message)s')
    settings = settings_from_env()
    server = build_server(settings, render)
    LOG.info(
        json.dumps(
            {
                'event': 'start',
                'port': settings.port,
                'allowed_origin': settings.allowed_origin,
                'map_origins': list(settings.map_origins),
                'egress_proxy': settings.egress_proxy,
            }
        )
    )
    server.serve_forever()


if __name__ == '__main__':
    main()
