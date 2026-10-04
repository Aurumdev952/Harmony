'''Run the renderer service: `python -m harmony.worker.renderer`.'''
import logging
import os

from harmony.worker.renderer.browser import render
from harmony.worker.renderer.server import RendererSettings, build_server


def settings_from_env() -> RendererSettings:
    return RendererSettings(
        allowed_origin=os.environ.get('RENDERER_ALLOWED_ORIGIN', 'http://web:5000'),
        port=int(os.environ.get('RENDERER_PORT', '8080')),
        max_timeout_seconds=float(
            os.environ.get('RENDERER_MAX_TIMEOUT_SECONDS', '120')
        ),
        max_bytes=int(os.environ.get('RENDERER_MAX_BYTES', str(25 * 1024 * 1024))),
        concurrency=int(os.environ.get('RENDERER_CONCURRENCY', '2')),
        max_page_height=int(os.environ.get('RENDERER_MAX_PAGE_HEIGHT', '16384')),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    settings = settings_from_env()
    server = build_server(settings, render)
    logging.getLogger('harmony.worker.renderer').info(
        '{"event": "start", "port": %d, "allowed_origin": "%s"}',
        settings.port,
        settings.allowed_origin,
    )
    server.serve_forever()


if __name__ == '__main__':
    main()
