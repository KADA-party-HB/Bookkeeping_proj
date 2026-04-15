import os
from contextlib import contextmanager
from dataclasses import dataclass
from math import ceil

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


@dataclass(frozen=True)
class PaginationOptions:
    page: int = 1
    per_page: int = 25
    max_per_page: int = 100
    per_page_options: tuple[int, ...] = (10, 25, 50, 100)

    @classmethod
    def from_mapping(
        cls,
        mapping,
        *,
        default_per_page=25,
        max_per_page=100,
        per_page_options=(10, 25, 50, 100),
    ):
        def _parse_int(value, fallback):
            try:
                return int(value)
            except (TypeError, ValueError):
                return fallback

        page = max(_parse_int(mapping.get("page"), 1), 1)
        per_page = _parse_int(mapping.get("per_page"), default_per_page)
        per_page = max(min(per_page, max_per_page), 1)

        normalized_options = tuple(
            sorted(
                {
                    option
                    for option in (*per_page_options, per_page, default_per_page)
                    if isinstance(option, int) and option > 0 and option <= max_per_page
                }
            )
        )

        return cls(
            page=page,
            per_page=per_page,
            max_per_page=max_per_page,
            per_page_options=normalized_options,
        )


@dataclass(frozen=True)
class PaginatedResult:
    items: list
    page: int
    per_page: int
    total_items: int
    total_pages: int
    per_page_options: tuple[int, ...] = (10, 25, 50, 100)

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.total_pages

    @property
    def prev_page(self):
        return self.page - 1 if self.has_prev else None

    @property
    def next_page(self):
        return self.page + 1 if self.has_next else None

    @property
    def start_index(self):
        if self.total_items == 0:
            return 0
        return ((self.page - 1) * self.per_page) + 1

    @property
    def end_index(self):
        if self.total_items == 0:
            return 0
        return min(self.page * self.per_page, self.total_items)

    def iter_pages(self, *, left_edge=1, left_current=1, right_current=2, right_edge=1):
        last = 0
        for num in range(1, self.total_pages + 1):
            if (
                num <= left_edge
                or (self.page - left_current - 1 < num < self.page + right_current)
                or num > self.total_pages - right_edge
            ):
                if last + 1 != num:
                    yield None
                yield num
                last = num


def paginate_query(sql, params=None, *, pagination=None, count_sql=None, count_params=None):
    pagination = pagination or PaginationOptions()
    base_sql = sql.strip().rstrip(";")
    base_params = tuple(params or ())
    effective_count_sql = (
        count_sql.strip().rstrip(";")
        if count_sql
        else f"SELECT COUNT(*) AS total_items FROM ({base_sql}) AS pagination_count_source"
    )
    effective_count_params = tuple(count_params if count_params is not None else base_params)

    with cursor(commit=False) as cur:
        cur.execute(effective_count_sql, effective_count_params)
        count_row = cur.fetchone()
        total_items = int(count_row["total_items"] if count_row else 0)

        if total_items == 0:
            return PaginatedResult(
                items=[],
                page=1,
                per_page=pagination.per_page,
                total_items=0,
                total_pages=1,
                per_page_options=pagination.per_page_options,
            )

        total_pages = max(ceil(total_items / pagination.per_page), 1)
        current_page = min(pagination.page, total_pages)
        offset = (current_page - 1) * pagination.per_page

        cur.execute(
            f"SELECT * FROM ({base_sql}) AS pagination_source LIMIT %s OFFSET %s",
            base_params + (pagination.per_page, offset),
        )
        items = cur.fetchall()

    return PaginatedResult(
        items=items,
        page=current_page,
        per_page=pagination.per_page,
        total_items=total_items,
        total_pages=total_pages,
        per_page_options=pagination.per_page_options,
    )
