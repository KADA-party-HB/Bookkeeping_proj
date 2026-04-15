import hashlib
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

LOCK_KEY = 86031742


def get_dsn() -> str:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    return dsn


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ensure_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS public.schema_migrations (
            filename text PRIMARY KEY,
            checksum text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )


def get_migrations_dir() -> Path:
    configured = os.getenv("MIGRATIONS_DIR")
    if configured:
        return Path(configured)
    container_path = Path("/app/migrations")
    if container_path.exists():
        return container_path
    return Path(__file__).resolve().parent.parent / "migrations"


def list_migrations(migrations_dir: Path) -> list[Path]:
    if not migrations_dir.exists():
        return []
    return sorted(p for p in migrations_dir.iterdir() if p.is_file() and p.suffix == ".sql")


def main() -> None:
    load_dotenv()
    dsn = get_dsn()
    files = list_migrations(get_migrations_dir())

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s);", (LOCK_KEY,))
        try:
            with conn.cursor() as cur:
                ensure_table(cur)
            conn.commit()

            for path in files:
                sql = path.read_text(encoding="utf-8")
                checksum = sha256_text(sql)

                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT checksum FROM public.schema_migrations WHERE filename = %s;",
                        (path.name,),
                    )
                    row = cur.fetchone()

                if row:
                    applied_checksum = row[0]
                    if applied_checksum != checksum:
                        raise RuntimeError(
                            f"Migration {path.name} was already applied with a different checksum. "
                            "Create a new migration file instead of editing an old one."
                        )
                    print(f"[skip] {path.name}")
                    continue

                try:
                    with conn.cursor() as cur:
                        cur.execute(sql)
                        cur.execute(
                            "INSERT INTO public.schema_migrations (filename, checksum) VALUES (%s, %s);",
                            (path.name, checksum),
                        )
                    conn.commit()
                    print(f"[applied] {path.name}")
                except Exception:
                    conn.rollback()
                    raise
        finally:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s);", (LOCK_KEY,))
            conn.commit()


if __name__ == "__main__":
    main()
