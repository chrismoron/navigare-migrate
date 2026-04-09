import logging
import os
import sqlite3
import tempfile

from .base_adapter import BaseFormatAdapter
from .adapter_registry import register_adapter

_logger = logging.getLogger(__name__)


def _write_temp_db(file_data):
    """Write file_data to a temporary file and return the path.

    The caller is responsible for deleting the file after use.
    """
    fd, path = tempfile.mkstemp(suffix='.sqlite3')
    try:
        os.write(fd, file_data)
    finally:
        os.close(fd)
    return path


@register_adapter
class SqliteAdapter(BaseFormatAdapter):

    FORMAT_KEY = 'sqlite'
    DISPLAY_NAME = 'SQLite Database'
    FILE_EXTENSIONS = ['.db', '.sqlite', '.sqlite3']
    MIME_TYPES = ['application/x-sqlite3', 'application/vnd.sqlite3']
    PYTHON_DEPENDENCIES = []

    def parse(self, file_data, options):
        table_name = options.get('table_name')
        if not table_name:
            raise ValueError("SQLite adapter requires 'table_name' in options")

        tmp_path = _write_temp_db(file_data)
        try:
            conn = sqlite3.connect(tmp_path)
            conn.row_factory = sqlite3.Row
            try:
                # Validate table name to prevent SQL injection
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,),
                )
                if cursor.fetchone() is None:
                    raise ValueError(
                        f"Table '{table_name}' not found in the SQLite database"
                    )

                cursor = conn.execute(
                    f'SELECT * FROM "{table_name}"'  # noqa: S608
                )
                columns = [desc[0] for desc in cursor.description]
                for row in cursor:
                    yield dict(zip(columns, row))
            finally:
                conn.close()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                _logger.warning("Failed to remove temp file: %s", tmp_path)

    def write(self, records, fields, options):
        table_name = options.get('table_name', 'data')

        fd, tmp_path = tempfile.mkstemp(suffix='.sqlite3')
        os.close(fd)
        try:
            conn = sqlite3.connect(tmp_path)
            try:
                # Create table with all TEXT columns
                col_defs = ', '.join(f'"{f}" TEXT' for f in fields)
                conn.execute(
                    f'CREATE TABLE "{table_name}" ({col_defs})'  # noqa: S608
                )

                # Insert rows
                placeholders = ', '.join(['?'] * len(fields))
                quoted_fields = ', '.join(f'"{f}"' for f in fields)
                insert_sql = (
                    f'INSERT INTO "{table_name}" '  # noqa: S608
                    f'({quoted_fields}) VALUES ({placeholders})'
                )
                for record in records:
                    values = [
                        str(record.get(f, '')) if record.get(f) is not None else ''
                        for f in fields
                    ]
                    conn.execute(insert_sql, values)

                conn.commit()
            finally:
                conn.close()

            with open(tmp_path, 'rb') as fh:
                return fh.read()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                _logger.warning("Failed to remove temp file: %s", tmp_path)

    def detect_columns(self, file_data, options):
        table_name = options.get('table_name')
        if not table_name:
            raise ValueError("SQLite adapter requires 'table_name' in options")

        tmp_path = _write_temp_db(file_data)
        try:
            conn = sqlite3.connect(tmp_path)
            try:
                cursor = conn.execute(
                    f'PRAGMA table_info("{table_name}")'  # noqa: S608
                )
                return [row[1] for row in cursor.fetchall()]
            finally:
                conn.close()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                _logger.warning("Failed to remove temp file: %s", tmp_path)

    def get_tables(self, file_data):
        """Return a list of all table names in the SQLite database.

        Args:
            file_data (bytes): Raw SQLite database bytes.

        Returns:
            list[str]: Table names.
        """
        tmp_path = _write_temp_db(file_data)
        try:
            conn = sqlite3.connect(tmp_path)
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                return [row[0] for row in cursor.fetchall()]
            finally:
                conn.close()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                _logger.warning("Failed to remove temp file: %s", tmp_path)
