import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from flask import g


def _connect():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set (see .env.example).")
    return psycopg.connect(dsn, row_factory=dict_row)


def get_db():
    if "db" not in g:
        g.db = _connect()
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    @app.cli.command("ping-db")
    def ping_db():
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
            print("OK")
        finally:
            conn.close()


@contextmanager
def cursor(commit=False):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise


def fetch_all(sql, params=None):
    with cursor(commit=False) as cur:
        cur.execute(sql, params or ())
        if cur.description is None:
            return []
        return cur.fetchall()


def fetch_one(sql, params=None):
    with cursor(commit=False) as cur:
        cur.execute(sql, params or ())
        if cur.description is None:
            return None
        return cur.fetchone()


def execute(sql, params=None):
    with cursor(commit=True) as cur:
        cur.execute(sql, params or ())
        return cur.rowcount


def execute_many(sql, seq_of_params):
    with cursor(commit=True) as cur:
        cur.executemany(sql, seq_of_params)
        return cur.rowcount


def query(sql, params=None, *, one=False, commit=False):
    with cursor(commit=commit) as cur:
        cur.execute(sql, params or ())
        if cur.description is None:
            return None
        return cur.fetchone() if one else cur.fetchall()


def insert_returning(sql, params=None):
    with cursor(commit=True) as cur:
        cur.execute(sql, params or ())
        if cur.description is None:
            return None
        return cur.fetchone()


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