'''Run web/gunicorn_server.py for real (or the file given as the second argument,
for the baseline), with create_app stubbed by a tiny Flask app, so gunicorn's own
config, including logconfig_dict, is what the module sets.'''
import runpy
import sys
import types


def create_app():
    import logging

    from flask import Flask

    from log.flask_request import install_request_logging

    app = Flask('wp2g_backend_live', root_path='/tmp', instance_path='/tmp')
    install_request_logging(app)

    @app.route('/ping')
    def ping():
        logging.getLogger('wp2g.view').info('handled ping')
        return 'ok'

    return app


argv = list(sys.argv)
sys.modules['web.server.app'] = types.SimpleNamespace(create_app=create_app)
sys.argv = ['gunicorn_server.py', '-l', '127.0.0.1', '-p', argv[1], '-w', '1']
if len(argv) > 2:
    runpy.run_path(argv[2], run_name='__main__')
else:
    runpy.run_module('web.gunicorn_server', run_name='__main__')
