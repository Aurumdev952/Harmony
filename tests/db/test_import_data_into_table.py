"""The self-serve import (`POST /api/import_self_serve`) on a real Postgres.

The route runs scripts/data_catalog/import_db_tables.py, which calls
`import_data_into_table` with the table list asserted here. WP-2c finding F13: the
import emptied every table with a foreign key into the catalogue (Field Setup's
unpublished-field mappings, dimension metadata, source_config), although the export
does not carry them.
"""

from __future__ import annotations

import importlib.util
import os
import secrets
import zipfile
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

import psycopg2
from psycopg2 import sql
import pytest
import sqlalchemy as sa

from db.postgres.utils import (
    ImportTableDataError,
    export_tables_to_zip,
    import_data_into_table,
)
from models.alchemy.base import Base
from scripts.data_catalog.export_db_tables import (
    DATA_CATALOG_TABLE_NAMES as EXPORTED_TABLES,
)
from scripts.data_catalog.import_db_tables import (
    DATA_CATALOG_TABLE_NAMES as IMPORTED_TABLES,
)
from util.file.compression.lz4 import LZ4Reader, LZ4Writer

# Every test also runs on a server whose OIDs are past 2^31, as on a long-lived
# cluster: the counter is cluster-wide, and temporary tables and TOAST values consume
# it. Such an OID read as a signed integer turns negative.
pytestmark = pytest.mark.parametrize(
    "postgres_server",
    [
        pytest.param(None, id="new-cluster"),
        pytest.param(3_000_000_000, id="oids-past-int4"),
    ],
    indirect=True,
)

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

# The catalogue's update_last_modified triggers, which stamp last_modified with now()
# on every UPDATE. The self-serve validator compares last_modified across instances.
LAST_MODIFIED_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "web/server/migrations/versions"
    / "2b730c14f514_add_data_catalog_tables_sql_trigger.py"
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
        _upgrade(LAST_MODIFIED_MIGRATION, cursor)
        cursor.execute(SEED)
    conn.close()
    yield postgres_database


def _upgrade(migration: Path, cursor) -> None:
    """Runs a migration's upgrade() with its op.execute going to `cursor`."""
    spec = importlib.util.spec_from_file_location(migration.stem, migration)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = SimpleNamespace(execute=cursor.execute)
    module.upgrade()


def _rows(url: str, table: str) -> list[tuple]:
    with psycopg2.connect(url) as conn, conn.cursor() as cursor:
        cursor.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(table)))
        rows = cursor.fetchall()
    conn.close()
    return sorted(rows, key=repr)


def _snapshot(url: str, tables: tuple[str, ...] | list[str]) -> dict[str, list[tuple]]:
    return {table: _rows(url, table) for table in tables}


def _row_versions(url: str, table: str) -> dict[str, str]:
    """Each row's xmin by id. An UPDATE writes a new row version, even of equal
    values."""
    with psycopg2.connect(url) as conn, conn.cursor() as cursor:
        cursor.execute(
            sql.SQL("SELECT id, xmin::text FROM {}").format(sql.Identifier(table))
        )
        versions = dict(cursor.fetchall())
    conn.close()
    return versions


def _last_modified_triggers(url: str) -> dict[str, str]:
    """pg_trigger.tgenabled of each update_last_modified trigger, by table."""
    with psycopg2.connect(url) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT tgrelid::regclass::text, tgenabled FROM pg_trigger"
            " WHERE tgname = 'update_last_modified'"
        )
        states = dict(cursor.fetchall())
    conn.close()
    return states


def _execute(url: str, statement: str | sql.Composable) -> None:
    with psycopg2.connect(url) as conn, conn.cursor() as cursor:
        cursor.execute(statement)
    conn.close()


@pytest.fixture(name="role")
def fixture_role(database: str) -> Iterator[tuple[sql.Identifier, str]]:
    """A login role that is no superuser, and a URL to `database` as that role."""
    name = f"importer_{secrets.token_hex(4)}"
    password = secrets.token_hex(16)
    role = sql.Identifier(name)
    _execute(
        database,
        sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER PASSWORD {}").format(
            role, sql.Literal(password)
        ),
    )
    parts = urlsplit(database)
    netloc = f"{name}:{password}@{parts.hostname}:{parts.port}"
    yield role, urlunsplit(parts._replace(netloc=netloc))
    _execute(
        database,
        sql.SQL("REASSIGN OWNED BY {0} TO CURRENT_USER; DROP OWNED BY {0}").format(
            role
        ),
    )
    _execute(database, sql.SQL("DROP ROLE {}").format(role))


def _public_tables(url: str) -> list[str]:
    with psycopg2.connect(url) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = [table for (table,) in cursor.fetchall()]
    conn.close()
    return tables


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


def test_an_import_keeps_the_archives_last_modified_and_skips_unchanged_rows(
    database, tmp_path
):
    archive = _export(database, str(tmp_path / "export.zip"))
    exported = _rows(database, "category")
    _execute(database, "UPDATE category SET name = 'Renamed' WHERE id = 'cat_a'")
    renamed = _rows(database, "category")
    assert len([row for row in renamed if row not in exported]) == 1
    versions = _row_versions(database, "category")

    _import(database, archive)

    assert _rows(database, "category") == exported
    after = _row_versions(database, "category")
    assert after["cat_a"] != versions["cat_a"]
    del after["cat_a"], versions["cat_a"]
    assert after == versions, "rows the archive leaves unchanged are not rewritten"
    assert _last_modified_triggers(database) == dict.fromkeys(IMPORTED_TABLES, "O")


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
    assert _last_modified_triggers(database) == dict.fromkeys(IMPORTED_TABLES, "O")


def test_a_dependent_of_a_row_the_export_carries_survives_its_old_parents_removal(
    database, tmp_path
):
    # The export moves cat_a under cat_new and no longer carries cat_old. Removing
    # cat_old must not cascade through the target's stale cat_a.parent_id into
    # cat_a's unpublished-field mapping.
    _execute(
        database,
        "INSERT INTO category (id, name, parent_id) VALUES"
        " ('cat_new', 'New', 'root'), ('cat_old', 'Old', 'root');"
        "UPDATE category SET parent_id = 'cat_new' WHERE id = 'cat_a';",
    )
    archive = _export(database, str(tmp_path / "export.zip"))
    _rewrite_table(archive, "category", lambda line: ";cat_old;" not in line)
    exported = [row for row in _rows(database, "category") if "cat_old" not in row]
    _execute(database, "UPDATE category SET parent_id = 'cat_old' WHERE id = 'cat_a'")
    dependents = _snapshot(database, DEPENDENT_TABLES)

    _import(database, archive)

    assert _rows(database, "category") == exported
    assert _snapshot(database, DEPENDENT_TABLES) == dependents


def test_a_failed_import_leaves_id_sequences_ahead_of_the_rows(database, tmp_path):
    archive = _export(database, str(tmp_path / "export.zip"))
    _rewrite_table(archive, "category", lambda line: ";cat_b;" not in line)
    # Added after the export, this row holds the id the export's sequence hands out.
    _execute(
        database,
        "INSERT INTO field_dimension_mapping (field_id, dimension_id)"
        " VALUES ('f2', 'Region')",
    )

    with pytest.raises(psycopg2.IntegrityError):
        _import(database, archive)

    _execute(
        database,
        "INSERT INTO field_dimension_mapping (field_id, dimension_id)"
        " VALUES ('f2', 'District')",
    )


def test_an_import_moves_id_sequences_past_the_imported_rows(database, tmp_path):
    archive = _export(database, str(tmp_path / "export.zip"))
    # A fresh instance's sequence, under a name that needs quoting.
    _execute(
        database,
        "ALTER SEQUENCE field_dimension_mapping_id_seq"
        ' RENAME TO "fdm ""id"" seq";'
        "SELECT setval('\"fdm \"\"id\"\" seq\"', 1, false);",
    )

    _import(database, archive)

    _execute(
        database,
        "INSERT INTO field_dimension_mapping (field_id, dimension_id)"
        " VALUES ('f2', 'District')",
    )


def test_an_import_that_fails_at_commit_leaves_id_sequences_ahead_of_the_rows(
    database, tmp_path
):
    archive = _export(database, str(tmp_path / "export.zip"))
    _execute(
        database,
        "INSERT INTO field_dimension_mapping (field_id, dimension_id)"
        " VALUES ('f2', 'Region');"
        # setval is not transactional. A deferred trigger fails the import at COMMIT,
        # after the import has set its sequences.
        "CREATE FUNCTION fail_at_commit() RETURNS trigger LANGUAGE plpgsql AS"
        " $$ BEGIN RAISE EXCEPTION 'fail at commit'; END $$;"
        "CREATE CONSTRAINT TRIGGER fail_at_commit AFTER INSERT"
        " ON field_dimension_mapping DEFERRABLE INITIALLY DEFERRED"
        " FOR EACH ROW EXECUTE FUNCTION fail_at_commit();",
    )

    with pytest.raises(psycopg2.Error, match="fail at commit"):
        _import(database, archive)

    _execute(
        database,
        "DROP TRIGGER fail_at_commit ON field_dimension_mapping;"
        "INSERT INTO field_dimension_mapping (field_id, dimension_id)"
        " VALUES ('f2', 'District')",
    )


def test_an_export_that_drops_the_parent_of_a_row_it_carries_changes_nothing(
    database, tmp_path
):
    _execute(
        database,
        "INSERT INTO category (id, name, parent_id) VALUES"
        " ('orphan_parent', 'P', 'root'), ('orphan_child', 'C', 'orphan_parent');",
    )
    archive = _export(database, str(tmp_path / "export.zip"))
    _rewrite_table(archive, "category", lambda line: ";orphan_parent;P;" not in line)
    before = _snapshot(database, [*IMPORTED_TABLES, *DEPENDENT_TABLES])

    with pytest.raises(ImportTableDataError, match="category"):
        _import(database, archive)

    assert _snapshot(database, [*IMPORTED_TABLES, *DEPENDENT_TABLES]) == before


def test_an_archive_missing_a_table_changes_nothing(database, tmp_path):
    archive = _export(database, str(tmp_path / "export.zip"))
    with zipfile.ZipFile(archive) as source:
        members = {
            name: source.read(name)
            for name in source.namelist()
            if name != "field_category_mapping.csv.lz4"
        }
    with zipfile.ZipFile(archive, "w") as target:
        for name, data in members.items():
            target.writestr(name, data)
    before = _snapshot(database, [*IMPORTED_TABLES, *DEPENDENT_TABLES])

    with pytest.raises(ImportTableDataError, match="field_category_mapping"):
        _import(database, archive)

    assert _snapshot(database, [*IMPORTED_TABLES, *DEPENDENT_TABLES]) == before


# Disabling the update_last_modified trigger needs ownership of each referenced
# catalogue table, where TRUNCATE needed only the TRUNCATE privilege. Deployments run
# migrations and the app as one role, which owns the tables and is no superuser.
def test_a_role_that_owns_the_tables_imports_without_being_superuser(
    database, role, tmp_path
):
    owner, url = role
    for table in _public_tables(database):
        _execute(
            database,
            sql.SQL("ALTER TABLE {} OWNER TO {}").format(sql.Identifier(table), owner),
        )
    archive = _export(database, str(tmp_path / "export.zip"))
    exported = _snapshot(database, IMPORTED_TABLES)
    dependents = _snapshot(database, DEPENDENT_TABLES)
    _execute(database, "UPDATE category SET name = 'Renamed' WHERE id = 'cat_a'")

    _import(url, archive)

    assert _snapshot(database, IMPORTED_TABLES) == exported
    assert _snapshot(database, DEPENDENT_TABLES) == dependents
    assert _last_modified_triggers(database) == dict.fromkeys(IMPORTED_TABLES, "O")


def test_a_role_with_every_privilege_but_not_ownership_cannot_import(
    database, role, tmp_path
):
    grantee, url = role
    _execute(
        database,
        sql.SQL(
            "GRANT ALL ON ALL TABLES IN SCHEMA public TO {0};"
            "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {0}"
        ).format(grantee),
    )
    archive = _export(database, str(tmp_path / "export.zip"))
    _execute(database, "UPDATE category SET name = 'Renamed' WHERE id = 'cat_a'")
    before = _snapshot(database, [*IMPORTED_TABLES, *DEPENDENT_TABLES])

    with pytest.raises(psycopg2.errors.InsufficientPrivilege, match="must be owner"):
        _import(url, archive)

    assert _snapshot(database, [*IMPORTED_TABLES, *DEPENDENT_TABLES]) == before
    assert _last_modified_triggers(database) == dict.fromkeys(IMPORTED_TABLES, "O")
