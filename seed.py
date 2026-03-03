# seed.py
import os
from decimal import Decimal

from dotenv import load_dotenv
import psycopg
from werkzeug.security import generate_password_hash

load_dotenv()

ADMIN_EMAIL = "karl.wikell@gmail.com"
ADMIN_PASSWORD = "DV1703"


def get_conn() -> psycopg.Connection:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set. Create a .env file (see .env.example).")
    return psycopg.connect(dsn)


def upsert_admin(conn: psycopg.Connection) -> int:
    pw_hash = generate_password_hash(ADMIN_PASSWORD)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (email, password_hash, role)
            VALUES (%s, %s, 'admin')
            ON CONFLICT (email)
            DO UPDATE SET
              password_hash = EXCLUDED.password_hash,
              role = 'admin'
            RETURNING id;
            """,
            (ADMIN_EMAIL, pw_hash),
        )
        return cur.fetchone()[0]


def upsert_item(conn: psycopg.Connection, *, sku: str, display_name: str, daily_rate: Decimal) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO items (sku, display_name, status, daily_rate)
            VALUES (%s, %s, 'active', %s)
            ON CONFLICT (sku)
            DO UPDATE SET
              display_name = EXCLUDED.display_name,
              status = 'active',
              daily_rate = EXCLUDED.daily_rate
            RETURNING id;
            """,
            (sku, display_name, daily_rate),
        )
        return cur.fetchone()[0]


def upsert_tent(
    conn: psycopg.Connection,
    *,
    item_id: int,
    capacity: int,
    season_rating: int,
    floor_area_m2: Decimal,
    build_time_minutes: int,
    setup_teardown_total: Decimal,
):
    # Split combined “Montering & nedmontering” evenly
    setup = (setup_teardown_total / Decimal("2")).quantize(Decimal("0.01"))
    teardown = setup

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tents (
              item_id, capacity, season_rating, floor_area_m2,
              estimated_build_time_minutes, construction_cost, deconstruction_cost
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (item_id)
            DO UPDATE SET
              capacity = EXCLUDED.capacity,
              season_rating = EXCLUDED.season_rating,
              floor_area_m2 = EXCLUDED.floor_area_m2,
              estimated_build_time_minutes = EXCLUDED.estimated_build_time_minutes,
              construction_cost = EXCLUDED.construction_cost,
              deconstruction_cost = EXCLUDED.deconstruction_cost;
            """,
            (item_id, capacity, season_rating, floor_area_m2, build_time_minutes, setup, teardown),
        )


def upsert_furnishing(
    conn: psycopg.Connection,
    *,
    item_id: int,
    kind: str,
    notes: str,
):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO furnishings (item_id, furnishing_kind, notes)
            VALUES (%s, %s, %s)
            ON CONFLICT (item_id)
            DO UPDATE SET
              furnishing_kind = EXCLUDED.furnishing_kind,
              notes = EXCLUDED.notes;
            """,
            (item_id, kind, notes),
        )


def main():
    conn = get_conn()
    try:
        # One transaction so the deferred subtype trigger is satisfied
        with conn.transaction():
            admin_id = upsert_admin(conn)
            print(f"Admin user upserted: id={admin_id}, email={ADMIN_EMAIL}")

            # --- Furnishings (from the image) ---
            # Table
            item_id = upsert_item(conn, sku="FURN-TABLE-01", display_name="Table (1 st)", daily_rate=Decimal("80"))
            upsert_furnishing(
                conn,
                item_id=item_id,
                kind="table",
                notes="Table for about 6 people",
            )
            print("Seeded: Table")

            # Chairrs
            item_id = upsert_item(conn, sku="FURN-CHAIR-01", display_name="Chair (1 st)", daily_rate=Decimal("20"))
            upsert_furnishing(
                conn,
                item_id=item_id,
                kind="chair",
                notes="",
            )
            print("Seeded: Chairs")

            # Benches
            item_id = upsert_item(conn, sku="FURN-BENCHSET-01", display_name="Bench (1 set)", daily_rate=Decimal("249"))
            upsert_furnishing(
                conn,
                item_id=item_id,
                kind="bench_set",
                notes="Good for large events",
            )
            print("Seeded: Bänkset")

            tents = [
                ("Tält 6×6 m",  "TENT-6X6-01",  Decimal("36.0"), 45, 45, Decimal("1599"), Decimal("1399"), 5),
                ("Tält 8×4 m",  "TENT-8X4-01",  Decimal("32.0"), 40, 45, Decimal("1399"), Decimal("1099"), 4),
                ("Tält 6×10 m", "TENT-6X10-01", Decimal("60.0"), 80, 60, Decimal("2399"), Decimal("2099"), 5),
                ("Tält 5×3 m",  "TENT-5X3-01",  Decimal("15.0"), 16, 30, Decimal("899"),  Decimal("699"), 3),
                ("Tält 8×5 m",  "TENT-8X5-01",  Decimal("40.0"), 50, 50, Decimal("1299"), Decimal("1099"), 2),
            ]

            for name, sku, area, cap, build_min, setup_total, day_price, quality in tents:
                item_id = upsert_item(conn, sku=sku, display_name=name, daily_rate=day_price)
                upsert_tent(
                    conn,
                    item_id=item_id,
                    capacity=cap,
                    season_rating=quality,
                    floor_area_m2=area,
                    build_time_minutes=build_min,
                    setup_teardown_total=setup_total,
                )
                print(f"Seeded: {name}")

        print("Seeding completed.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()