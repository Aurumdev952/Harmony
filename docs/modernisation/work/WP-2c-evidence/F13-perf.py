"""Times the old and new import_data_into_table on a large synthetic catalogue.

Run from the repo root against a scratch Postgres on 127.0.0.1:55432 (password
`scratch`): PYTHONPATH=. ZEN_ENV=harmony_demo uv run python <this file> [fields].
"""

import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import time

import psycopg2
import sqlalchemy as sa

from models.alchemy.base import Base
from models.alchemy.data_upload import model as du
from models.alchemy.query import model as q
from scripts.data_catalog.export_db_tables import DATA_CATALOG_TABLE_NAMES as EXPORTED
from scripts.data_catalog.import_db_tables import DATA_CATALOG_TABLE_NAMES as IMPORTED

URL = "postgresql://postgres:scratch@127.0.0.1:55432/postgres"
FIELDS = int(sys.argv[1]) if len(sys.argv) > 1 else 50_000
DIMS_PER_FIELD = 10

SEED = f"""
INSERT INTO category (id, name, parent_id) VALUES ('root', 'Root', NULL);
INSERT INTO category (id, name, parent_id)
    SELECT 'cat_' || g, 'C' || g, 'root' FROM generate_series(1, 2000) g;
INSERT INTO dimension (id, name) SELECT 'dim_' || g, 'D' || g FROM generate_series(1, 200) g;
INSERT INTO dimension_category (id, name, parent_id) VALUES ('dims', 'Dims', NULL);
INSERT INTO dimension_category_mapping (dimension_id, category_id)
    SELECT 'dim_' || g, 'dims' FROM generate_series(1, 200) g;
INSERT INTO pipeline_datasource (id, name)
    SELECT 'src_' || g, 'S' || g FROM generate_series(1, 100) g;
INSERT INTO field (id, name, short_name, calculation)
    SELECT 'f_' || g, 'Field ' || g, 'F' || g, '{{"type": "SUM"}}'
    FROM generate_series(1, {FIELDS}) g;
INSERT INTO field_category_mapping (field_id, category_id)
    SELECT 'f_' || g, 'cat_' || (g % 2000 + 1) FROM generate_series(1, {FIELDS}) g;
INSERT INTO field_pipeline_datasource_mapping (field_id, pipeline_datasource_id)
    SELECT 'f_' || g, 'src_' || (g % 100 + 1) FROM generate_series(1, {FIELDS}) g;
INSERT INTO field_dimension_mapping (field_id, dimension_id)
    SELECT 'f_' || g, 'dim_' || d
    FROM generate_series(1, {FIELDS}) g, generate_series(1, {DIMS_PER_FIELD}) d;
INSERT INTO dataprep_flow (id, expected_columns, recipe_id, appendable)
    SELECT g, '["date"]', g, false FROM generate_series(1, 100) g;
INSERT INTO dataprep_job (dataprep_flow_id) SELECT g FROM generate_series(1, 100) g;
INSERT INTO self_serve_source (source_id, dataprep_flow_id)
    SELECT 'src_' || g, g FROM generate_series(1, 100) g;
INSERT INTO data_upload_file_summary
    (self_serve_source_id, source_id, file_path, user_file_name, column_mapping)
    SELECT g % 100 + 1, 'src_' || (g % 100 + 1), 'u/' || g, 'a.csv', '[]'
    FROM generate_series(1, 2000) g;
INSERT INTO unpublished_field (id, name)
    SELECT 'uf_' || g, 'U' || g FROM generate_series(1, 10000) g;
INSERT INTO unpublished_field_category_mapping (unpublished_field_id, category_id)
    SELECT 'uf_' || g, 'cat_' || (g % 2000 + 1) FROM generate_series(1, 10000) g;
INSERT INTO unpublished_field_dimension_mapping (unpublished_field_id, dimension_id)
    SELECT 'uf_' || g, 'dim_' || (g % 200 + 1) FROM generate_series(1, 10000) g;
INSERT INTO source_config (config, source_id, is_active)
    SELECT '{{}}', g, true FROM generate_series(1, 100) g;
"""  # noqa: S608 (only integer constants are interpolated)


def load(source, name):
    spec = importlib.util.spec_from_loader(name, loader=None)
    module = importlib.util.module_from_spec(spec)
    # dataclasses and typing resolve names through sys.modules[cls.__module__].
    sys.modules[name] = module
    exec(compile(source, name, "exec"), module.__dict__)  # noqa: S102 (our own source)
    return module


def reset():
    e = sa.create_engine(URL)
    tables = [
        m.__table__
        for mod in (q, du)
        for m in vars(mod).values()
        if isinstance(m, type) and issubclass(m, Base) and m is not Base
    ]
    with e.begin() as c:
        c.execute("DROP TABLE IF EXISTS alembic_version")
    Base.metadata.drop_all(e, tables=tables)
    Base.metadata.create_all(e, tables=tables)
    e.dispose()
    with psycopg2.connect(URL) as conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY);"
            "INSERT INTO alembic_version VALUES ('perf');"
        )
        cur.execute(SEED)
        cur.execute("ANALYZE")
    conn.close()


def counts():
    with psycopg2.connect(URL) as conn, conn.cursor() as cur:
        out = {}
        for t in (
            "field",
            "field_dimension_mapping",
            "unpublished_field_category_mapping",
            "unpublished_field_dimension_mapping",
            "source_config",
        ):
            cur.execute(f"SELECT count(*) FROM {t}")  # noqa: S608 (fixed table names)
            out[t] = cur.fetchone()[0]
    conn.close()
    return out


new = load(pathlib.Path("db/postgres/utils.py").read_text(), "new_utils")
# d23076f is the branch point before the F13 fix.
old = load(
    subprocess.run(
        ["git", "show", "d23076f:db/postgres/utils.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout,
    "old_utils",
)

with tempfile.TemporaryDirectory() as d:
    archive = f"{d}/export.zip"
    reset()
    new.export_tables_to_zip(EXPORTED, archive, URL)
    print("seeded", counts())
    for label, module in (("old", old), ("new", new), ("new again", new)):
        if label != "new again":
            reset()
        start = time.monotonic()
        module.import_data_into_table(URL, archive, IMPORTED)
        print(f"{label}: {time.monotonic() - start:.2f}s", counts())
