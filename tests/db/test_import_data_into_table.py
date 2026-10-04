"""The self-serve import (`POST /api/import_self_serve`) on a real Postgres.

The route runs scripts/data_catalog/import_db_tables.py, which calls
`import_data_into_table` with the table list asserted here. WP-2c finding F13: the
import emptied every table with a foreign key into the catalogue (Field Setup's
unpublished-field mappings, dimension metadata, source_config), although the export
does not carry them.
"""

from __future__ import annotations

import os
import zipfile
from collections.abc import Iterator

import psycopg2
import pytest
import sqlalchemy as sa

from db.postgres.utils import export_tables_to_zip, import_data_into_table
from models.alchemy.base import Base
from scripts.data_catalog.export_db_tables import (
    DATA_CATALOG_TABLE_NAMES as EXPORTED_TABLES,
)
from scripts.data_catalog.import_db_tables import (
    DATA_CATALOG_TABLE_NAMES as IMPORTED_TABLES,
)
from util.file.compression.lz4 import LZ4Reader, LZ4Writer

# Tables the export does not carry whose rows reference catalogue rows.
DEPENDENT_TABLES = (
    "unpublished_field_category_mapping",
    "unpublished_field_pipeline_datasource_mapping",
    "unpublished_field_dimension_mapping",
    "geo_dimension_metadata",
    "hierarchical_dimension_metadata",
    "non_hierarchical_dimension",
    "source_config",
)

SEED = """
INSERT INTO category (id, name, parent_id) VALUES
    ('root', 'Root', NULL), ('cat_a', 'A', 'root'), ('cat_b', 'B', 'root');
INSERT INTO dimension (id, name) VALUES
    ('Region', 'Region'), ('District', 'District'), ('Lat', 'Lat'), ('Lon', 'Lon');
INSERT INTO dimension_category (id, name, parent_id) VALUES
    ('dims', 'Dimensions', NULL), ('geo', 'Geography', 'dims');
INSERT INTO field (id, name, short_name, calculation) VALUES
    ('f1', 'F1', 'F1', '{"type": "SUM"}'), ('f2', 'F2', 'F2', '{"type": "SUM"}');
INSERT INTO pipeline_datasource (id, name) VALUES ('src', 'Source');
INSERT INTO field_dimension_mapping (field_id, dimension_id) VALUES ('f1', 'Region');
INSERT INTO field_pipeline_datasource_mapping (field_id, pipeline_datasource_id)
    VALUES ('f1', 'src');
INSERT INTO field_category_mapping (field_id, category_id) VALUES
    ('f1', 'cat_a'), ('f2', 'cat_b');
INSERT INTO dimension_category_mapping (dimension_id, category_id) VALUES
    ('Region', 'dims'), ('District', 'geo');
INSERT INTO dataprep_flow (id, expected_columns, recipe_id, appendable)
    VALUES (1, '["date"]', 100, false);
INSERT INTO dataprep_job (dataprep_flow_id) VALUES (1);
INSERT INTO self_serve_source (source_id, dataprep_flow_id) VALUES ('src', 1);
INSERT INTO data_upload_file_summary
    (self_serve_source_id, source_id, file_path, user_file_name, column_mapping)
    VALUES (1, 'src', 'uploads/a.csv', 'a.csv', '[]');

INSERT INTO unpublished_field (id, name) VALUES ('uf1', 'Unpublished');
INSERT INTO unpublished_field_category_mapping (unpublished_field_id, category_id)
    VALUES ('uf1', 'cat_a');
INSERT INTO unpublished_field_pipeline_datasource_mapping
    (unpublished_field_id, pipeline_datasource_id) VALUES ('uf1', 'src');
INSERT INTO unpublished_field_dimension_mapping (unpublished_field_id, dimension_id)
    VALUES ('uf1', 'Region');
INSERT INTO geo_dimension_metadata (id, lat_id, lon_id) VALUES ('Region', 'Lat', 'Lon');
INSERT INTO hierarchical_dimension_metadata
    (dimension_id, unique_identifier_dimension_id) VALUES ('District', 'District');
INSERT INTO non_hierarchical_dimension (id) VALUES ('Lon');
INSERT INTO source_config (config, source_id, is_active) VALUES ('{}', 1, true);
"""


@pytest.fixture(name="database")
def fixture_database(postgres_database: str) -> Iterator[str]:
    engine = sa.create_engine(postgres_database)
    names = (*IMPORTED_TABLES, *DEPENDENT_TABLES, "unpublished_field")
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[n] for n in names])
    engine.dispose()
    with psycopg2.connect(postgres_database) as conn, conn.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY);"
            "INSERT INTO alembic_version VALUES ('test');"
        )
        cursor.execute(SEED)
    conn.close()
    yield postgres_database


def _rows(url: str, table: str) -> list[tuple]:
    with psycopg2.connect(url) as conn, conn.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {table}")
        rows = cursor.fetchall()
    conn.close()
    return sorted(rows, key=repr)


def _snapshot(url: str, tables: tuple[str, ...] | list[str]) -> dict[str, list[tuple]]:
    return {table: _rows(url, table) for table in tables}


def _execute(url: str, statement: str) -> None:
    with psycopg2.connect(url) as conn, conn.cursor() as cursor:
        cursor.execute(statement)
    conn.close()


def _export(url: str, path: str) -> str:
    export_tables_to_zip(EXPORTED_TABLES, path, url)
    return path


def _import(url: str, path: str) -> None:
    import_data_into_table(url, path, IMPORTED_TABLES)


def _rewrite_table(archive: str, table: str, keep) -> None:
    """Rewrites one table's CSV in an export, keeping the lines `keep` accepts."""
    member = f"{table}.csv.lz4"
    directory = os.path.dirname(archive)
    with zipfile.ZipFile(archive) as source:
        members = {name: source.read(name) for name in source.namelist()}
    extracted = os.path.join(directory, member)
    with open(extracted, "wb") as handle:
        handle.write(members[member])
    with LZ4Reader(extracted) as reader:
        lines = reader.read().splitlines(keepends=True)
    with LZ4Writer(extracted) as writer:
        writer.write("".join(lines[:1] + [line for line in lines[1:] if keep(line)]))
    with open(extracted, "rb") as handle:
        members[member] = handle.read()
    with zipfile.ZipFile(archive, "w") as target:
        for name, data in members.items():
            target.writestr(name, data)


def test_reimporting_an_unchanged_export_keeps_rows_in_tables_it_does_not_carry(
    database, tmp_path
):
    before = _snapshot(database, DEPENDENT_TABLES)
    assert all(before.values()), "every dependent table is seeded"
    catalogue = _snapshot(database, IMPORTED_TABLES)

    _import(database, _export(database, str(tmp_path / "export.zip")))

    assert _snapshot(database, DEPENDENT_TABLES) == before
    assert _snapshot(database, IMPORTED_TABLES) == catalogue


def test_an_import_makes_the_catalogue_tables_match_the_export(database, tmp_path):
    archive = _export(database, str(tmp_path / "export.zip"))
    exported = _snapshot(database, IMPORTED_TABLES)
    _execute(
        database,
        "UPDATE category SET name = 'Renamed' WHERE id = 'cat_a';"
        "INSERT INTO category (id, name, parent_id) VALUES ('cat_new', 'New', 'root');"
        "INSERT INTO unpublished_field_category_mapping"
        " (unpublished_field_id, category_id) VALUES ('uf1', 'cat_new');"
        "DELETE FROM field_category_mapping WHERE field_id = 'f2';",
    )

    _import(database, archive)

    assert _snapshot(database, IMPORTED_TABLES) == exported
    # A dependent row survives while the export carries its parent and goes with a
    # parent the export does not carry, as ON DELETE CASCADE has it.
    assert _rows(database, "unpublished_field_category_mapping") == [
        (1, "uf1", "cat_a")
    ]


def test_mapping_rows_whose_ids_differ_from_the_export_are_replaced(database, tmp_path):
    archive = _export(database, str(tmp_path / "export.zip"))
    exported = _rows(database, "dimension_category_mapping")
    # Another instance created the same two mappings in the opposite order, so each
    # id holds the other's (dimension_id, category_id) pair.
    _execute(
        database,
        "DELETE FROM dimension_category_mapping;"
        "INSERT INTO dimension_category_mapping (id, dimension_id, category_id)"
        " VALUES (1, 'District', 'geo'), (2, 'Region', 'dims');",
    )

    _import(database, archive)

    assert _rows(database, "dimension_category_mapping") == exported


def test_a_failed_import_changes_nothing(database, tmp_path):
    archive = _export(database, str(tmp_path / "export.zip"))
    # field_category_mapping still references cat_b, so the import must fail.
    _rewrite_table(archive, "category", lambda line: ";cat_b;" not in line)
    _execute(database, "UPDATE category SET name = 'Changed' WHERE id = 'cat_a'")
    before = _snapshot(database, [*IMPORTED_TABLES, *DEPENDENT_TABLES])

    with pytest.raises(psycopg2.IntegrityError):
        _import(database, archive)

    assert _snapshot(database, [*IMPORTED_TABLES, *DEPENDENT_TABLES]) == before
