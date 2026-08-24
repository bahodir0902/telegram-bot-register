from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db.migrations import EXPECTED_COLUMNS, EXPECTED_TABLES, SCHEMA_VERSION


class HealthcheckError(RuntimeError):
    """Raised when the local runtime state is not ready to serve the bot."""


def check_database(path: Path) -> None:
    """Verify an existing SQLite database without creating or modifying it."""

    resolved_path = path.resolve()
    if not resolved_path.is_file():
        raise HealthcheckError("database file does not exist")

    try:
        with sqlite3.connect(
            f"{resolved_path.as_uri()}?mode=ro",
            uri=True,
            timeout=2.0,
        ) as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version != SCHEMA_VERSION:
                raise HealthcheckError(
                    f"database schema version is {version}; expected {SCHEMA_VERSION}"
                )
            rows = connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            ).fetchall()
            existing_tables = {str(row[0]) for row in rows}
            missing_tables = EXPECTED_TABLES - existing_tables
            if missing_tables:
                missing = ", ".join(sorted(missing_tables))
                raise HealthcheckError(f"database schema is missing tables: {missing}")

            for table, expected_columns in EXPECTED_COLUMNS.items():
                columns = {
                    str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')
                }
                missing_columns = expected_columns - columns
                if missing_columns:
                    missing = ", ".join(sorted(missing_columns))
                    raise HealthcheckError(f"database table {table} is missing columns: {missing}")

            result = connection.execute("PRAGMA quick_check(1)").fetchone()
            if result is None or result[0] != "ok":
                raise HealthcheckError("database integrity check failed")
    except HealthcheckError:
        raise
    except sqlite3.Error as exc:
        raise HealthcheckError("database cannot be opened or queried") from exc
