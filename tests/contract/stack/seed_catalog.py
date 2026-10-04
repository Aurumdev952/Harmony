"""Seeds the data-catalog rows that only the pipeline writes.

No client operation creates dimensions, pipeline datasources, unpublished
fields, Dataprep flows or self-serve sources, so without these rows the
Relay queries that read them record empty connections and their item shapes
go unpinned. Runs once per stack, from init.sh; idempotent.
"""

import os

import psycopg2

ROWS = [
    (
        "INSERT INTO dimension_category (id, name, parent_id) VALUES (%s, %s, NULL)",
        ("contract_dimension_category", "Contract dimensions"),
    ),
    (
        (
            "INSERT INTO dimension (id, name, description, authorizable, filterable)"
            " VALUES (%s, %s, %s, false, true)"
        ),
        ("ContractDimension", "Contract dimension", "Seeded by the contract stack"),
    ),
    (
        "INSERT INTO dimension_category_mapping (dimension_id, category_id) VALUES (%s, %s)",
        ("ContractDimension", "contract_dimension_category"),
    ),
    (
        "INSERT INTO pipeline_datasource (id, name) VALUES (%s, %s)",
        ("contract_source", "Contract source"),
    ),
    (
        "INSERT INTO pipeline_datasource (id, name) VALUES (%s, %s)",
        ("contract_upload_source", "Contract upload source"),
    ),
    (
        (
            "INSERT INTO unpublished_field (id, name, short_name, description, calculation)"
            " VALUES (%s, %s, %s, %s, %s)"
        ),
        (
            "contract_unpublished_field",
            "Contract unpublished field",
            "Contract unpublished",
            "Seeded by the contract stack",
            '{"type": "SUM"}',
        ),
    ),
    (
        (
            "INSERT INTO unpublished_field_category_mapping (unpublished_field_id, category_id)"
            " VALUES (%s, %s)"
        ),
        ("contract_unpublished_field", "root"),
    ),
    (
        (
            "INSERT INTO unpublished_field_pipeline_datasource_mapping"
            " (unpublished_field_id, pipeline_datasource_id) VALUES (%s, %s)"
        ),
        ("contract_unpublished_field", "contract_source"),
    ),
    (
        (
            "INSERT INTO dataprep_flow (id, expected_columns, recipe_id, appendable)"
            " VALUES (%s, %s, %s, false)"
        ),
        (9001, '["date", "value"]', 9001),
    ),
    (
        "INSERT INTO self_serve_source (source_id, dataprep_flow_id) VALUES (%s, %s)",
        ("contract_source", 9001),
    ),
]


def main() -> None:
    with psycopg2.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM dimension WHERE id = 'ContractDimension'")
        if cur.fetchone():
            print("contract-init: catalog already seeded")
            return
        for sql, args in ROWS:
            cur.execute(sql, args)
    print("contract-init: seeded catalog rows")


if __name__ == "__main__":
    main()
