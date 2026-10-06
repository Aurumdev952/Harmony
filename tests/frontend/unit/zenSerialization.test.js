import { describe, expect, test } from 'vitest';

import * as Zen from 'lib/Zen';
import FieldFilter from 'models/core/wip/QueryFilter/FieldFilter';

const SERIALIZED = [
  { fieldId: 'yellow_fever_cases', type: 'FIELD' },
  { fieldId: 'malaria_cases', type: 'FIELD' },
];

describe('Zen collection serializers', () => {
  test('arrays and Zen.Arrays serialize element by element, in order', () => {
    const models = Zen.deserializeArray(FieldFilter, SERIALIZED);

    expect(Zen.serializeArray(models)).toStrictEqual(SERIALIZED);
    expect(Zen.serializeArray(Zen.Array.create(models))).toStrictEqual(SERIALIZED);
    expect(Zen.serializeArray(Zen.deserializeToZenArray(FieldFilter, SERIALIZED))).toStrictEqual(
      SERIALIZED,
    );
  });

  test('maps and Zen.Maps serialize value by value, keeping keys', () => {
    const serializedMap = { a: SERIALIZED[0], b: SERIALIZED[1] };
    const models = Zen.deserializeMap(FieldFilter, serializedMap);

    expect(Zen.serializeMap(models)).toStrictEqual(serializedMap);
    expect(Zen.serializeMap(Zen.deserializeToZenMap(FieldFilter, serializedMap))).toStrictEqual(
      serializedMap,
    );
  });

  test('async array deserialization resolves to the same models', async () => {
    const models = await Zen.deserializeAsyncArray(FieldFilter, SERIALIZED);

    expect(Zen.serializeArray(models)).toStrictEqual(SERIALIZED);
  });
});

describe('Zen models are immutable values', () => {
  test('a setter returns a new model and leaves the original unchanged', () => {
    const original = FieldFilter.deserialize(SERIALIZED[0]);
    const changed = original.fieldId('malaria_cases');

    expect(changed).not.toBe(original);
    expect(original.serialize()).toStrictEqual(SERIALIZED[0]);
    expect(changed.serialize()).toStrictEqual(SERIALIZED[1]);
  });
});
