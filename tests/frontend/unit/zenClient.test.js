import { afterAll, beforeAll, describe, expect, test } from 'vitest';

import ZenClient from 'util/ZenClient';
import ZenError from 'util/ZenError';
import { installVendorJQuery, startStubServer } from './helpers';

let stub;

beforeAll(async () => {
  stub = await startStubServer();
  installVendorJQuery();
});

afterAll(() => stub.close());

describe('ZenClient.post', () => {
  test('posts JSON under /api and resolves with the envelope data', async () => {
    stub.reset(() => ({ body: { data: { timeout: true }, success: true } }));

    const data = await ZenClient.post('timeout', {});

    expect(stub.requests).toHaveLength(1);
    const [request] = stub.requests;
    expect(request.method).toBe('POST');
    expect(request.pathname).toBe('/api/timeout');
    expect(request.headers['content-type']).toBe('application/json; charset=utf-8');
    expect(JSON.parse(request.body)).toEqual({});
    expect(data).toEqual({ timeout: true });
  });

  test('rejects with the envelope message when success is false', async () => {
    stub.reset(() => ({ body: { data: 'Bad input', success: false } }));

    const error = await ZenClient.post('anything', { a: 1 }).catch(e => e);

    expect(error).toBeInstanceOf(ZenError);
    expect(error.message).toBe('Bad input');
  });

  test('rejects with a generic ZenError on an HTTP error', async () => {
    stub.reset(() => ({ body: { message: 'boom' }, status: 500 }));

    const error = await ZenClient.post('anything').catch(e => e);

    expect(error).toBeInstanceOf(ZenError);
    expect(error.message).toBe('An error occurred on the server');
  });
});

describe('ZenClient.request', () => {
  test('gets JSON under /api and resolves with the envelope data', async () => {
    stub.reset(() => ({ body: { data: [1, 2], success: true } }));

    const data = await ZenClient.request('field?x=1');

    expect(stub.requests[0].method).toBe('GET');
    expect(stub.requests[0].pathname).toBe('/api/field');
    expect(stub.requests[0].search).toBe('?x=1');
    expect(data).toEqual([1, 2]);
  });

  // Today $.getJSON has no error callback, so the promise never settles on a
  // 4xx or 5xx. Reported to frontend-platform for WP-6a (see WP-2e Requests).
  test.todo('rejects on an HTTP error');
});
