'''Live check for WP-2g unit 4: gunicorn gevent workers, the log config as
logconfig_dict, and the request-id middleware on a Flask app.'''

import gevent.monkey

gevent.monkey.patch_all()

import logging  # noqa: E402
import sys  # noqa: E402

import gevent  # noqa: E402
from flask import Flask  # noqa: E402
from gunicorn.app.base import BaseApplication  # noqa: E402

import log  # noqa: E402,F401  configures logging at import, as the app does
from log.config import logging_config  # noqa: E402
from log.flask_request import install_request_logging  # noqa: E402

app = Flask('wp2g_live')
install_request_logging(app)


@app.route('/work/<int:n>')
def work(n):
    # Yield to other greenlets mid-request so concurrent requests interleave.
    gevent.sleep(0.05 * (n % 4))
    logging.getLogger('wp2g.view').info('handled work %s', n)
    return f'ok {n}'


class App(BaseApplication):
    def load_config(self):
        self.cfg.set('bind', sys.argv[1])
        self.cfg.set('workers', 2)
        self.cfg.set('worker_class', 'gevent')
        self.cfg.set('logconfig_dict', logging_config())

    def load(self):
        return app


if __name__ == '__main__':
    App().run()
