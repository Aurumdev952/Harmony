// `{"$ref": "/api2/query/<endpoint>/<id>"}` is stored data: saved dashboards
// and queries carry it (SPEC INV-4, C-11). The client must keep reading it.
import { afterAll, beforeAll, describe, expect, test } from 'vitest';

import CategoryService from 'services/wip/CategoryService';
import DatasetService from 'services/wip/DatasetService';
import Dimension from 'models/core/wip/Dimension';
import DimensionService from 'services/wip/DimensionService';
import FieldMetadataService from 'services/wip/FieldMetadataService';
import FieldService from 'services/wip/FieldService';
import GranularityService from 'services/wip/GranularityService';
import GroupingItemUtil from 'models/core/wip/GroupingItem/GroupingItemUtil';
import QueryFilterUtil from 'models/core/wip/QueryFilter/QueryFilterUtil';
import { installVendorJQuery, startStubServer } from './helpers';

const SERVICES = [
  ['CategoryService', CategoryService, '/api2/query/categories/'],
  ['DatasetService', DatasetService, '/api2/query/datasets/'],
  ['DimensionService', DimensionService, '/api2/query/dimensions/'],
  ['FieldMetadataService', FieldMetadataService, '/api2/query/field_metadata/'],
  ['FieldService', FieldService, '/api2/query/fields/'],
  ['GranularityService', GranularityService, '/api2/query/granularities/'],
];

const IDS = ['StateName', 'month', 'yellow_fever_cases', 'Région Est', 'a.b-c_d', '42', 'per/1000'];

describe.each(SERVICES)('%s URI conversion', (_, service, prefix) => {
  test.each(IDS)('id %s maps to a URI under the endpoint and back', id => {
    const uri = service.convertIDToURI(id);

    expect(uri).toBe(`${prefix}${id}`);
    expect(service.convertURIToID(uri)).toBe(id);
  });
});

describe('dimension references in stored query specs', () => {
  test('a $ref and a bare id name the same dimension', () => {
    expect(Dimension.deserializeToString({ $ref: '/api2/query/dimensions/StateName' })).toBe(
      'StateName',
    );
    expect(Dimension.deserializeToString('StateName')).toBe('StateName');
  });

  test('a selector filter stored with a $ref dimension serializes with the bare id', async () => {
    const filter = await QueryFilterUtil.deserializeAsync({
      dimension: { $ref: '/api2/query/dimensions/Sex' },
      type: 'SELECTOR',
      value: 'Female',
    });

    expect(filter.serialize()).toStrictEqual({
      dimension: 'Sex',
      type: 'SELECTOR',
      value: 'Female',
    });
  });

  test('a grouping stored with a $ref dimension queries by the bare id', async () => {
    const group = await GroupingItemUtil.deserializeAsync({
      item: {
        dimension: { $ref: '/api2/query/dimensions/StateName' },
        includeAll: false,
        includeNull: true,
        includeTotal: true,
        name: 'State',
      },
      type: 'GROUPING_DIMENSION',
    });

    expect(group.serializeForQuery()).toStrictEqual({
      dimension: 'StateName',
      includeAll: false,
      includeNull: true,
      includeTotal: true,
    });
  });
});

describe('legacy GRANULARITY grouping resolved through the server', () => {
  let stub;

  beforeAll(async () => {
    stub = await startStubServer();
    installVendorJQuery();
  });

  afterAll(() => stub.close());

  test('the $ref is looked up in /api2/query/granularities', async () => {
    stub.reset(request =>
      request.pathname === '/api2/query/granularities'
        ? {
            body: [
              { category: { id: 'date_groups' }, description: '', id: 'month', name: 'Month' },
              { category: { id: 'date_groups' }, description: '', id: 'year', name: 'Year' },
            ],
          }
        : { body: { message: 'unexpected' }, status: 404 },
    );

    const group = await GroupingItemUtil.deserializeAsync({
      item: { $ref: '/api2/query/granularities/month' },
      type: 'GRANULARITY',
    });

    expect(stub.requests.map(r => `${r.method} ${r.pathname}`)).toEqual([
      'GET /api2/query/granularities',
    ]);
    expect(group.serializeForQuery()).toStrictEqual({
      granularity: 'month',
      includeTotal: false,
    });
    expect(group.name()).toBe('Month');
  });
});
