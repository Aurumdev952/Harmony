from __future__ import annotations

import csv
import re
import shutil
import tempfile
import urllib.parse
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT, quote_ident

from log import LOG
from util.file.compression.lz4 import LZ4Reader, LZ4Writer


class ImportTableDataError(Exception):
    def __init__(self, message):
        super().__init__()
        self.message = message

    def as_dict(self):
        dct = {'$message': self.message}
        return dct

    def __str__(self) -> str:
        return self.message


def url_encode(sql_connection_string: str):
    matches = re.findall(r'\/\/(.*)@', sql_connection_string)
    if matches:
        password_username = matches[0]
        sql_connection_string = sql_connection_string.replace(
            password_username, urllib.parse.quote(password_username, safe=':')
        )
    return sql_connection_string


@contextmanager
def psycopg_connection(*args, **kwargs):
    try:
        conn = psycopg2.connect(*args, **kwargs)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        yield conn
    finally:
        # We must always try to close the connection when the user is finished with it.
        conn.close()


@contextmanager
def make_temp_directory():
    temp_dir = tempfile.mkdtemp()
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir)


def export_tables_to_zip(
    tables: list[str],
    output_filename: str,
    sql_connection_string: str,
    delimiter: str = ';',
):
    '''exports database tables specified into csv files in zipped file.
    Args:
        tables: List of all tables to export
    '''
    with psycopg_connection(sql_connection_string) as conn, zipfile.ZipFile(
        output_filename, 'w', zipfile.ZIP_DEFLATED, compresslevel=3
    ) as zip_file, make_temp_directory() as temp_dir_name:
        cursor = conn.cursor()
        for table in tables:
            LOG.info('Beginning export of table: %s', table)

            # Quote the table name to prevent SQL injection.
            table_ident = quote_ident(table, conn)

            # Since we have to execute the COPY statement as raw SQL, we need to safely
            # escape all untrusted input.
            sql_command = cursor.mogrify(
                f'COPY {table_ident} TO STDOUT WITH CSV DELIMITER %s HEADER',
                (delimiter,),
            )

            file_name = f'{temp_dir_name}/output.csv.lz4'
            with LZ4Writer(file_name) as f:
                cursor.copy_expert(sql_command, f)

            zip_file.write(
                file_name,
                f'{table}.csv.lz4',
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=3,
            )
            LOG.info('Finished export of table: %s', table)


def get_current_db_version(cursor):
    cursor.execute('SELECT version_num FROM alembic_version')
    row = cursor.fetchone()
    if row:
        return row[0]
    return None


def check_db_migration_version(
    version_file: str,
    current_db_version: str,
    delimiter: str = ';',
):

    if not current_db_version:
        LOG.info(
            'Could not determine current migration version of the database,'
            'blindly importing data into the tables.'
        )
        return
    with LZ4Reader(version_file) as reader:
        csv_reader = csv.DictReader(reader, delimiter=delimiter)
        row = next(csv_reader)
        file_db_version = row.get('version_num')

        if not file_db_version:
            LOG.error(
                'Could not determine the db migration version number in the imported archive'
            )

        if not file_db_version or file_db_version.strip() != current_db_version:
            raise ImportTableDataError(
                'Current database migration version differs from version in the '
                'export archives and cannot import data into the tables. '
                'If you are confident that none of the migrations will adversely '
                'affect this transfer, then use the disable_migration_check param '
                'to override this check.'
            )


def _archive_member(table_name: str) -> str:
    return f'{table_name}.csv.lz4'


def _fetch_column(cursor, query: str, *params) -> list:
    cursor.execute(query, params)
    return [row[0] for row in cursor.fetchall()]


@dataclass(frozen=True)
class _StagedTable:
    '''One table of an archive, COPYed into a temporary table of the same shape.'''

    name: str
    table: sql.Identifier
    staging: sql.Identifier
    # The quoted name, for catalogue lookups through `::regclass`.
    regclass: str
    columns: list[str]
    primary_key: list[str]
    # Whether any foreign key, from any table, references this table.
    referenced: bool

    @classmethod
    def stage(cls, cursor, name: str, csv_file: str, delimiter: str):
        table = sql.Identifier(name)
        staging = sql.Identifier(f'import_{name}')
        regclass = table.as_string(cursor)
        cursor.execute(
            sql.SQL('CREATE TEMPORARY TABLE {} (LIKE {}) ON COMMIT DROP').format(
                staging, table
            )
        )
        with LZ4Reader(csv_file) as reader:
            cursor.copy_expert(
                sql.SQL('COPY {} FROM STDIN WITH CSV DELIMITER {} HEADER').format(
                    staging, sql.Literal(delimiter)
                ),
                reader,
            )
        cursor.execute(sql.SQL('ANALYZE {}').format(staging))
        primary_key = _fetch_column(
            cursor,
            'SELECT a.attname FROM pg_index i JOIN pg_attribute a'
            ' ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)'
            ' WHERE i.indrelid = %s::regclass AND i.indisprimary ORDER BY a.attnum',
            regclass,
        )
        if not primary_key:
            raise ImportTableDataError(f'Table {name} has no primary key.')
        return cls(
            name=name,
            table=table,
            staging=staging,
            regclass=regclass,
            columns=_fetch_column(
                cursor,
                'SELECT attname FROM pg_attribute WHERE attrelid = %s::regclass'
                ' AND attnum > 0 AND NOT attisdropped ORDER BY attnum',
                regclass,
            ),
            primary_key=primary_key,
            referenced=bool(
                _fetch_column(
                    cursor,
                    'SELECT 1 FROM pg_constraint'
                    " WHERE contype = 'f' AND confrelid = %s::regclass LIMIT 1",
                    regclass,
                )
            ),
        )

    def empty(self, cursor):
        cursor.execute(sql.SQL('DELETE FROM {}').format(self.table))

    def insert(self, cursor):
        '''Inserts the staged rows. A staged row whose primary key the table already
        holds updates that row in place, so rows referencing it are untouched.'''
        updates = [column for column in self.columns if column not in self.primary_key]
        on_conflict = (
            sql.SQL('DO UPDATE SET {}').format(
                sql.SQL(', ').join(
                    sql.SQL('{0} = EXCLUDED.{0}').format(sql.Identifier(column))
                    for column in updates
                )
            )
            if updates
            else sql.SQL('DO NOTHING')
        )
        columns = sql.SQL(', ').join(map(sql.Identifier, self.columns))
        cursor.execute(
            sql.SQL(
                'INSERT INTO {table} ({columns}) SELECT {columns} FROM {staging}'
                ' ON CONFLICT ({key}) {on_conflict}'
            ).format(
                table=self.table,
                columns=columns,
                staging=self.staging,
                key=sql.SQL(', ').join(map(sql.Identifier, self.primary_key)),
                on_conflict=on_conflict,
            )
        )

    def delete_rows_not_staged(self, cursor):
        '''Deletes the rows whose primary key the archive does not carry. Their
        foreign keys' ON DELETE rules apply to the rows referencing them.'''
        cursor.execute(
            sql.SQL(
                'DELETE FROM {table} AS t WHERE NOT EXISTS'
                ' (SELECT 1 FROM {staging} AS s WHERE {match})'
            ).format(
                table=self.table,
                staging=self.staging,
                match=sql.SQL(' AND ').join(
                    sql.SQL('s.{0} = t.{0}').format(sql.Identifier(column))
                    for column in self.primary_key
                ),
            )
        )

    def check_matches_staging(self, cursor):
        '''The table holds every staged row and nothing else, unless a cascade
        deleted a staged row because the archive dropped the row it references.'''
        cursor.execute(
            sql.SQL(
                'SELECT (SELECT count(*) FROM {}), (SELECT count(*) FROM {})'
            ).format(self.table, self.staging)
        )
        imported, staged = cursor.fetchone()
        if imported != staged:
            raise ImportTableDataError(
                f'Table {self.name} holds {imported} rows after the import, but the '
                f'archive carries {staged}. The archive is inconsistent: it drops a '
                'row that other rows it carries reference.'
            )

    def advance_id_sequence(self, cursor):
        '''Moves the id sequence past every id in the table. It never moves the
        sequence back, because setval is not undone when the transaction rolls
        back.'''
        if 'id' not in self.columns:
            return
        cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", (self.regclass,))
        (sequence,) = cursor.fetchone()
        if sequence is None:
            return
        # pg_get_serial_sequence returns the sequence's quoted, qualified name.
        cursor.execute(
            sql.SQL(
                'SELECT setval(%s::regclass, GREATEST('
                '(SELECT CASE WHEN is_called THEN last_value ELSE last_value - 1 END'
                ' FROM {sequence}),'
                ' (SELECT coalesce(max(id), 0) FROM {table})) + 1, false)'
            ).format(sequence=sql.SQL(sequence), table=self.table),
            (sequence,),
        )


def import_data_into_table(
    sql_connection_string,
    input_file,
    tables: list[str],
    delimiter: str = ';',
    disable_migration_check: bool | None = False,
):
    '''Replaces the rows of `tables` with the rows of an `export_tables_to_zip`
    archive, in one transaction, so a failed import changes nothing.

    Tables the archive does not carry (unpublished-field mappings, dimension metadata,
    source_config) hold rows that reference the imported tables, with ON DELETE
    CASCADE. So the import never empties a table that a foreign key references: it
    upserts the archive's rows on the primary key, and only then deletes the rows the
    archive does not carry. A cascade therefore reaches only the rows that referenced
    a row the archive removed. A table that nothing references is emptied and
    reloaded, because rows with the same id may hold different values on the two
    instances and collide with the table's other unique constraints.

    Args:
        sql_connection_string: Postgres database connection string.
        input_file: Path to the archive.
        tables: The tables to import, each listed after the tables it references.
        delimiter: CSV data delimiter.
        disable_migration_check: Import even when the archive's Alembic version
            differs from the database's.
    '''
    with psycopg_connection(sql_connection_string) as conn, zipfile.ZipFile(
        input_file
    ) as zip_file, make_temp_directory() as temp_dir_name:
        members = set(zip_file.namelist())
        missing = [
            name
            for name in ['alembic_version', *tables]
            if _archive_member(name) not in members
        ]
        if missing:
            raise ImportTableDataError(
                f'The archive has no data for the tables: {", ".join(missing)}.'
            )
        version_file = zip_file.extract(
            _archive_member('alembic_version'), path=temp_dir_name
        )
        conn.autocommit = False
        with conn, conn.cursor() as cursor:
            if not disable_migration_check:
                current_db_version = get_current_db_version(cursor)
                check_db_migration_version(version_file, current_db_version, delimiter)
            staged = []
            for name in tables:
                LOG.info('Staging the archive of table: %s', name)
                csv_file = zip_file.extract(_archive_member(name), path=temp_dir_name)
                staged.append(_StagedTable.stage(cursor, name, csv_file, delimiter))
            referenced = [table for table in staged if table.referenced]
            leaves = [table for table in staged if not table.referenced]

            for table in leaves:
                table.empty(cursor)
            for table in referenced:
                LOG.info('Importing table: %s', table.name)
                table.insert(cursor)
            for table in reversed(referenced):
                table.delete_rows_not_staged(cursor)
            for table in leaves:
                LOG.info('Importing table: %s', table.name)
                table.insert(cursor)
            for table in staged:
                table.check_matches_staging(cursor)
            for table in staged:
                table.advance_id_sequence(cursor)
        LOG.info('Finished importing tables: %s', ', '.join(tables))
