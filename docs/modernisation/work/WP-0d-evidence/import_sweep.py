"""Import every module under the given roots; print one line per module."""

import importlib
import os
import signal
import sys

REMOVED = {
    'flask_admin',
    'graphene',
    'graphene_sqlalchemy',
    'flask_graphql',
    'graphql',
    'dask',
    'google',
    'analytics',
    'paramiko',
    'nacl',
    'pyasn1',
    'cryptography',
    'fuzzywuzzy',
    'jellyfish',
    'editdistance',
}
SKIP_DIRS = {'node_modules', '__pycache__', 'client', 'public'}


def _timeout(*_):
    raise TimeoutError('import exceeded 20s')


def modules(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith('.py'):
                parts = os.path.join(dirpath, name)[:-3].split(os.sep)
                if parts[-1] == '__init__':
                    parts = parts[:-1]
                yield '.'.join(parts)


signal.signal(signal.SIGALRM, _timeout)
roots = sys.argv[1:] or ['config', 'data', 'db', 'log', 'models', 'util', 'web']
for root in roots:
    for mod in modules(root):
        signal.alarm(20)
        try:
            importlib.import_module(mod)
            status = 'OK'
        # SystemExit from import-time flag parsing counts too
        except BaseException as exc:
            missing = getattr(exc, 'name', None) or ''
            flag = (
                ' REMOVED-PKG'
                if isinstance(exc, ImportError) and missing.split('.')[0] in REMOVED
                else ''
            )
            first = str(exc).splitlines()[0][:160] if str(exc) else ''
            status = f'ERR {type(exc).__name__}: {first}{flag}'
        finally:
            signal.alarm(0)
        print(f'{mod}\t{status}', flush=True)
