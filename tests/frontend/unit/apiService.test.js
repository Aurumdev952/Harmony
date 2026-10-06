import { afterAll, beforeAll, describe, expect, test, vi } from 'vitest';

import APIService, { API_VERSION } from 'services/APIService';
import ZenError from 'util/ZenError';
import ZenHTTPError from 'util/ZenHTTPError';
import { installVendorJQuery, startStubServer } from './helpers';

let stub;

beforeAll(async () => {
  stub = await startStubServer();
  installVendorJQuery();
});

afterAll(() => stub.close());

describe('APIService', () => {
  test.each([
    ['V2', API_VERSION.V2, '/api2/query/dimensions'],
    ['V1', API_VERSION.V1, '/api/query/dimensions'],
    ['NONE', API_VERSION.NONE, '/query/dimensions'],
  ])('%s prefixes the path and strips its outer slashes', async (_, version, expected) => {
    stub.reset(() => ({ body: [{ id: 'StateName' }] }));

    const result = await APIService.get(version, '/query/dimensions/');

    expect(stub.requests).toHaveLength(1);
    expect(stub.requests[0].method).toBe('GET');
    expect(stub.requests[0].pathname).toBe(expected);
    expect(result).toEqual([{ id: 'StateName' }]);
  });

  test.each(['post', 'patch'])('%s sends the payload as a JSON body', async method => {
    stub.reset(() => ({ body: { $uri: '/api2/dashboard/7' } }));
    const payload = { nested: { values: [1, 2.5, null] }, title: 'Malaria — ÉTÉ' };

    const result = await APIService[method](API_VERSION.V2, 'dashboard/7', payload);

    expect(stub.requests).toHaveLength(1);
    const [request] = stub.requests;
    expect(request.method).toBe(method.toUpperCase());
    expect(request.pathname).toBe('/api2/dashboard/7');
    expect(request.headers['content-type']).toBe('application/json; charset=utf-8');
    expect(JSON.parse(request.body)).toEqual(payload);
    expect(result).toEqual({ $uri: '/api2/dashboard/7' });
  });

  test('post with no payload sends an empty JSON object', async () => {
    stub.reset(() => ({ body: {} }));

    await APIService.post(API_VERSION.NONE, 'api/user/3/generate_api_token');

    expect(JSON.parse(stub.requests[0].body)).toEqual({});
  });

  test('delete uses the DELETE method', async () => {
    stub.reset(() => ({ body: {} }));

    await APIService.delete(API_VERSION.V2, 'dashboard/7');

    expect(stub.requests).toHaveLength(1);
    expect(stub.requests[0].method).toBe('DELETE');
    expect(stub.requests[0].pathname).toBe('/api2/dashboard/7');
  });

  test('an HTTP error rejects with ZenHTTPError carrying status, message and errors', async () => {
    stub.reset(() => ({
      body: { errors: [{ field: 'title' }], message: 'Title is required' },
      status: 400,
    }));

    const error = await APIService.post(API_VERSION.V2, 'dashboard', {}).catch(e => e);

    expect(error).toBeInstanceOf(ZenHTTPError);
    expect(error.statusCode).toBe(400);
    expect(error.isBadRequest()).toBe(true);
    expect(error.message).toBe('Title is required');
    expect(error.errors).toEqual([{ field: 'title' }]);
  });

  test('a legacy {success: false} body rejects with ZenError', async () => {
    stub.reset(() => ({ body: { data: 'nope', success: false } }));
    vi.spyOn(console, 'error').mockImplementation(() => {});

    const error = await APIService.get(API_VERSION.V1, 'legacy').catch(e => e);

    expect(error).toBeInstanceOf(ZenError);
    expect(error).not.toBeInstanceOf(ZenHTTPError);
  });
});
