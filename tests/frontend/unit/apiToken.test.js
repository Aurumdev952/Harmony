import { afterAll, beforeAll, describe, expect, test } from 'vitest';

import APIToken from 'services/models/APIToken';
import DirectoryService from 'services/DirectoryService';
import User from 'services/models/User';
import { installVendorJQuery, startStubServer } from './helpers';

// Shaped like APITokenResource (web/server/api/api_token_models.py). The token
// value is a placeholder, never a real credential.
const GENERATED = {
  $uri: '/api2/api_token/9',
  created: '2026-10-04',
  id: '9',
  isRevoked: false,
  revoked: '2026-10-04',
  token: 'placeholder-token-value',
};

const USER = {
  $uri: '/api2/user/3',
  acls: [],
  apiTokens: [],
  firstName: 'Fixture',
  lastName: 'User',
  roles: [],
  status: 'active',
  username: 'fixture-user@harmony.invalid',
};

let stub;

beforeAll(async () => {
  stub = await startStubServer();
  installVendorJQuery();
});

afterAll(() => stub.close());

describe('DirectoryService.generateUserAPIToken', () => {
  test('posts to the user item route and returns the new token', async () => {
    stub.reset(() => ({ body: GENERATED }));

    const token = await DirectoryService.generateUserAPIToken(User.deserialize(USER));

    expect(stub.requests).toHaveLength(1);
    expect(stub.requests[0].method).toBe('POST');
    expect(stub.requests[0].pathname).toBe('/api2/user/3/generate_api_token');
    expect(token).toBeInstanceOf(APIToken);
    expect(token.token()).toBe('placeholder-token-value');
    expect(token.id()).toBe('9');
    expect(token.isRevoked()).toBe(false);
    expect(token.uri()).toBe('/api2/api_token/9');
  });
});

describe('APIToken serialization', () => {
  test('serialize never sends the secret token value back', () => {
    const serialized = APIToken.deserialize(GENERATED).serialize();

    expect(serialized).not.toHaveProperty('token');
  });

  test('deserialize then serialize keeps the id, uri, flags and calendar dates', () => {
    const { token, ...withoutSecret } = GENERATED;

    expect(APIToken.deserialize(GENERATED).serialize()).toStrictEqual(withoutSecret);
  });

  test('a user round-trips its tokens without their secret values', () => {
    const user = User.deserialize({ ...USER, apiTokens: [GENERATED] });

    expect(user.serialize().apiTokens).toStrictEqual([
      {
        $uri: '/api2/api_token/9',
        created: '2026-10-04',
        id: '9',
        isRevoked: false,
        revoked: '2026-10-04',
      },
    ]);
  });
});
