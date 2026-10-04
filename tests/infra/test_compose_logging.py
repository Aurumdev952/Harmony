"""Logging settings in the rendered Compose configuration (WP-2g).

Run with: uv run pytest tests/infra/test_compose_logging.py
"""

import json
import re

import pytest
from test_compose import BASE_ENV, config, pytestmark  # noqa: F401

PRODUCTION = ['docker-compose.yaml', 'docker-compose.prod.yaml']
DEV = ['docker-compose.yaml', 'docker-compose.dev.yaml']

# Sample values for the nginx variables, already JSON-escaped as nginx does with
# `escape=json`.
NGINX_SAMPLES = {
    'time_iso8601': '2026-01-15T10:00:00+00:00',
    'request_method': 'GET',
    'host': 'zz.example.org',
    'uri': '/overview',
    'status': '200',
    'body_bytes_sent': '512',
    'request_time': '0.042',
    'upstream_http_x_request_id': '4bf92f3577b34da6a3ce929d0e0e4736',
    'remote_addr': '192.0.2.10',
    'http_user_agent': 'Mozilla/5.0 \\"quoted\\" Chrome/126.0.0.0',
}


def environment(cfg, service):
    return cfg['services'][service]['environment']


@pytest.mark.parametrize('service', ['web', 'worker'])
def test_services_write_json_lines_to_stdout(tmp_path, service):
    env = environment(config(tmp_path, PRODUCTION), service)
    assert env['LOG_FORMAT'] == 'json'
    assert env['LOG_STREAM'] == 'stdout'


def test_pipeline_writes_json_lines_but_keeps_stdout_for_data(tmp_path):
    env = environment(
        config(tmp_path, ['docker-compose.pipeline.yaml']), 'etl-pipeline'
    )
    assert env['LOG_FORMAT'] == 'json'
    # Pipeline steps capture scripts' stdout, so logs stay on stderr (the default).
    assert 'LOG_STREAM' not in env


@pytest.mark.parametrize('service', ['web', 'worker', 'pipeline'])
def test_dev_overlay_writes_text_for_people(tmp_path, service):
    assert environment(config(tmp_path, DEV), service)['LOG_FORMAT'] == 'text'


def nginx_format(tmp_path):
    env = environment(config(tmp_path, PRODUCTION), 'nginx')
    assert env['LOG_FORMAT_ESCAPE'] == 'json'
    # `docker compose config` keeps Compose's `$$` escape; containers see `$`.
    return env['LOG_FORMAT'].replace('$$', '$')


def render_nginx_line(log_format):
    def sample(match):
        return NGINX_SAMPLES[match.group(1)]

    return re.sub(r'\$(\w+)', sample, log_format)


def test_nginx_lines_are_json_with_the_app_keys(tmp_path):
    entry = json.loads(render_nginx_line(nginx_format(tmp_path)))
    assert entry == {
        'timestamp': '2026-01-15T10:00:00+00:00',
        'level': 'INFO',
        'logger': 'nginx.access',
        'message': 'GET /overview 200',
        'deployment': BASE_ENV['ZEN_ENV'],
        'request_id': '4bf92f3577b34da6a3ce929d0e0e4736',
        'http': {
            'method': 'GET',
            'host': 'zz.example.org',
            'path': '/overview',
            'status': 200,
            'bytes': 512,
            'duration_s': 0.042,
        },
        'client_ip': '192.0.2.10',
        'user_agent': 'Mozilla/5.0 "quoted" Chrome/126.0.0.0',
    }


def test_nginx_format_fits_nginx_proxy_template(tmp_path):
    log_format = nginx_format(tmp_path)
    # nginx-proxy writes `log_format vhost escape=json '<LOG_FORMAT>';`.
    assert "'" not in log_format
    assert '\n' not in log_format


def test_nginx_lines_leave_out_query_strings(tmp_path):
    variables = set(re.findall(r'\$(\w+)', nginx_format(tmp_path)))
    assert not variables & {'request', 'request_uri', 'args', 'query_string'}
    assert not any(name.startswith(('arg_', 'cookie_')) for name in variables)
