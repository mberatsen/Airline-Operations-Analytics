"""MySQL connection helpers: connect from .env, run SQL files, apply the schema."""
import os
from pathlib import Path
from typing import Optional

import pymysql
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "sql" / "schema"
SCHEMA_FILES = ("01_create_tables.sql", "02_views.sql")


def connect(database: Optional[str] = None) -> pymysql.Connection:
    """Open a connection using MYSQL_* settings from .env.

    database overrides MYSQL_DATABASE; with neither set, no database is selected.
    local_infile is on and autocommit is off.
    """
    load_dotenv(ROOT / ".env")
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST") or "127.0.0.1",
        port=int(os.getenv("MYSQL_PORT") or 3306),
        user=os.getenv("MYSQL_USER") or "root",
        password=os.getenv("MYSQL_PASSWORD") or "",
        database=database or os.getenv("MYSQL_DATABASE") or None,
        charset="utf8mb4",
        local_infile=True,
        autocommit=False,
    )


def run_sql_file(conn, path: Path) -> None:
    """Execute a SQL file, splitting statements on a ';' at the end of a line."""
    statements, buf = [], []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        buf.append(line)
        if line.rstrip().endswith(";"):
            statements.append("\n".join(buf))
            buf = []
    if "".join(buf).strip():
        statements.append("\n".join(buf))
    with conn.cursor() as cur:
        for stmt in statements:
            if stmt.strip():
                cur.execute(stmt)
    conn.commit()


def apply_schema(conn) -> None:
    """Drop and recreate all tables, then (re)create the views."""
    for name in SCHEMA_FILES:
        run_sql_file(conn, SCHEMA_DIR / name)
