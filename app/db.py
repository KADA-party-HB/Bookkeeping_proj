import os
import psycopg
from psycopg.rows import dict_row
from flask import g

# Create a new DB connection; rows are returned as dictionaries instead of default tuples.

def _connect():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set (see .env.example).")
    return psycopg.connect(dsn, row_factory=dict_row)

# Returns the current DB session (connection) or creates a new one.

def get_db():
    if "db" not in g:
        g.db = _connect()
    return g.db

# Close the database connection at the end of the request.

def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

# Register a CLI command; checks whether the database connection works.

def init_db(app):
    @app.cli.command("ping-db")
    def ping_db():
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
        conn.close()
        print("OK")

# Run a SQL query and optionally return results.
# one=True: return only one row
# commit=True: commit changes (for INSERT/UPDATE/DELETE)

def query(sql, params=None, *, one=False, commit=False):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        if cur.description is None:
            if commit:
                conn.commit()
            return None
        result = cur.fetchone() if one else cur.fetchall()
    if commit:
        conn.commit()
    return result

# Execute a SQL statement that does not return rows (e.g. INSERT, UPDATE, DELETE).

def execute(sql, params=None):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
    conn.commit()

# Run multiple SQL statements in a transaction (commit on success, rollback on error).

def tx(fn):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            result = fn(cur)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
