"""Test-only tap between web and the renderer: records each render request
(including its token, so the end-to-end check can try to reuse it) and forwards
it unchanged."""
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = 'http://renderer:8080/render'


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        with open('/tap/calls.jsonl', 'a') as calls:
            calls.write(body.decode() + '\n')
        request = urllib.request.Request(
            UPSTREAM, data=body, headers={'Content-Type': 'application/json'}
        )
        try:
            response = urllib.request.urlopen(request, timeout=200)
            status, headers, data = response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            status, headers, data = error.code, error.headers, error.read()
        self.send_response(status)
        for name in ('Content-Type', 'Server-Timing'):
            if headers.get(name):
                self.send_header(name, headers[name])
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
