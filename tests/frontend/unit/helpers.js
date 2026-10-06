import http from 'http';
import path from 'path';

import { readFileSync } from 'fs';

// Not import.meta.url: in the jsdom environment the bare 'url' import is the
// npm browser polyfill, and Vite rewrites new URL(..., import.meta.url) to a
// served /@fs/ path. vite-node defines __dirname for every module.
export const REPO_ROOT = path.resolve(__dirname, '../../..');

// The smallest page bootstrap the client modules under test read at import.
export const DEFAULT_BACKEND = {
  deploymentName: 'harmony_demo',
  enableEtDateSelection: false,
  locale: 'en',
  ui: { isSessionPersisted: false, sessionTimeout: 1800 },
  user: { isAuthenticated: false },
};

/**
 * Import a fresh copy of a client module under a different page bootstrap.
 * Modules such as dateUtil read it once at import, so the module registry is
 * reset first. Callers pass a dynamic import: () => import('util/dateUtil').
 */
export async function withBackend(overrides, importModule) {
  const { vi } = await import('vitest');
  vi.resetModules();
  window.__JSON_FROM_BACKEND = { ...structuredClone(DEFAULT_BACKEND), ...overrides };
  return importModule();
}

// Pages load jQuery as a global vendor script (layout.html), and APIService
// and ZenClient call the global `$`. Load the same file the same way.
export function installVendorJQuery() {
  if (window.jQuery === undefined) {
    const source = readFileSync(
      path.join(REPO_ROOT, 'web/public/js/vendor/jquery-3.6.0.js'),
      'utf8',
    );
    // eslint-disable-next-line no-new-func
    new Function(source).call(window);
  }
  return window.jQuery;
}

/**
 * A real HTTP server on loopback that records every request and answers with
 * the current responder, `(request) -> {status, body, headers}`. The jsdom
 * document moves to the server's origin, so relative URLs such as `/api2/...`
 * reach it as they reach Flask in the browser, same-origin. Tests assert on
 * what crossed the wire, which stays true when WP-6a swaps jQuery for fetch.
 *
 * Start it once per file, before installVendorJQuery: jQuery captures the
 * page location when it loads.
 */
export async function startStubServer() {
  const requests = [];
  let respond = () => ({ body: {} });
  const server = http.createServer((req, res) => {
    const chunks = [];
    req.on('data', chunk => chunks.push(chunk));
    req.on('end', () => {
      const url = new URL(req.url, 'http://stub');
      const recorded = {
        body: Buffer.concat(chunks).toString('utf8'),
        headers: req.headers,
        method: req.method,
        pathname: url.pathname,
        search: url.search,
      };
      requests.push(recorded);
      const { body = '', headers = {}, status = 200 } = respond(recorded) || {};
      const payload = typeof body === 'string' ? body : JSON.stringify(body);
      res.writeHead(status, { 'Content-Type': 'application/json', ...headers });
      res.end(payload);
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const { jsdom } = globalThis;
  jsdom.reconfigure({ url: `${origin}/` });
  // reconfigure() moves the document but not the origin jsdom's XHR checks
  // against (window._origin), which would make every call cross-origin.
  jsdom.window._origin = origin;
  return {
    origin,
    requests,
    // Node 18 (CI) otherwise waits out the 5 s keep-alive of jQuery's sockets.
    close: () =>
      new Promise(resolve => {
        server.close(resolve);
        server.closeAllConnections();
      }),
    reset(responder) {
      requests.length = 0;
      respond = responder;
    },
  };
}
