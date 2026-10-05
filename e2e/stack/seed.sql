-- Applied after populate_query_models_from_config.py has loaded harmony_demo's
-- one configured indicator. Stacked bar, overlapping bar and scatterplot need
-- two indicators, so the e2e stack adds a second one in the same category.
-- The offline query client answers any field, so it needs no Druid data.
INSERT INTO field (id, name, short_name, description, calculation, created, last_modified)
VALUES (
  'e2e_yellow_fever_deaths',
  'Yellow Fever Deaths (e2e fixture)',
  'Deaths (e2e)',
  'Second indicator for the e2e suite only.',
  '{"type": "SUM", "filter": {"type": "FIELD", "fieldId": "e2e_yellow_fever_deaths"}, "metric": "sum"}',
  now(),
  now()
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO field_category_mapping (field_id, category_id, visibility_status, created, last_modified)
VALUES ('e2e_yellow_fever_deaths', 'yellow-fever', 'VISIBLE', now(), now())
ON CONFLICT (field_id, category_id) DO NOTHING;

-- The contract stack seeds an unpublished field whose calculation is only
-- {"type": "SUM"}, a shape the pipeline never writes
-- (scripts/field_setup/populate_unused_fields.py always adds the field
-- filter), and Indicator Setup throws on it. Give it the pipeline's shape.
UPDATE unpublished_field
SET calculation = '{"type": "SUM", "filter": {"type": "FIELD", "fieldId": "contract_unpublished_field"}, "metric": "sum"}'
WHERE id = 'contract_unpublished_field';
