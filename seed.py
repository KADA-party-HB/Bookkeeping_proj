import os
from decimal import Decimal

from dotenv import load_dotenv
import psycopg
from werkzeug.security import generate_password_hash

load_dotenv()

ADMIN_EMAIL = "karl.wikell@gmail.com"
ADMIN_PASSWORD = "DV1703"

TEMP_USER_EMAIL = "hej.hej@hej.hej"
TEMP_USER_PASSWORD = "DV1703"


def get_conn() -> psycopg.Connection:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set.")
    return psycopg.connect(dsn)


def upsert_user(conn, email: str, password: str, role: str) -> int:
    pw_hash = generate_password_hash(password)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (email, password_hash, role)
            VALUES (%s, %s, %s)
            ON CONFLICT (email)
            DO UPDATE SET
              password_hash = EXCLUDED.password_hash,
              role = EXCLUDED.role
            RETURNING id;
            """,
            (email, pw_hash, role),
        )
        return cur.fetchone()[0]


def upsert_customer_for_user(conn, user_id: int, full_name: str, email: str, phone: str | None):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO customers (full_name, email, phone, user_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (email)
            DO UPDATE SET
              full_name = EXCLUDED.full_name,
              phone = EXCLUDED.phone,
              user_id = EXCLUDED.user_id
            RETURNING id;
            """,
            (full_name, email, phone, user_id),
        )
        return cur.fetchone()[0]


def upsert_category(conn, display_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO categories (display_name)
            VALUES (%s)
            ON CONFLICT (display_name)
            DO UPDATE SET display_name = EXCLUDED.display_name
            RETURNING id;
            """,
            (display_name,),
        )
        return cur.fetchone()[0]


def upsert_tent_category(
    conn,
    category_id: int,
    capacity: int,
    season_rating: int,
    build_time: int,
    setup_service_fee: Decimal,
    packed_weight_kg: Decimal | None = None,
    floor_area_m2: Decimal | None = None,
):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tent_categories (
              category_id,
              capacity,
              season_rating,
              packed_weight_kg,
              floor_area_m2,
              estimated_build_time_minutes,
              setup_service_fee
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (category_id)
            DO UPDATE SET
              capacity = EXCLUDED.capacity,
              season_rating = EXCLUDED.season_rating,
              packed_weight_kg = EXCLUDED.packed_weight_kg,
              floor_area_m2 = EXCLUDED.floor_area_m2,
              estimated_build_time_minutes = EXCLUDED.estimated_build_time_minutes,
              setup_service_fee = EXCLUDED.setup_service_fee;
            """,
            (
                category_id,
                capacity,
                season_rating,
                packed_weight_kg,
                floor_area_m2,
                build_time,
                setup_service_fee,
            ),
        )


def upsert_furn_category(
    conn,
    category_id: int,
    kind: str,
    weight_kg: Decimal | None,
    notes: str | None,
):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO furnishing_categories (category_id, furnishing_kind, weight_kg, notes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (category_id)
            DO UPDATE SET
              furnishing_kind = EXCLUDED.furnishing_kind,
              weight_kg = EXCLUDED.weight_kg,
              notes = EXCLUDED.notes;
            """,
            (category_id, kind, weight_kg, notes),
        )


def upsert_rental_period(conn, label: str, min_days: int, max_days: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO rental_periods (label, min_days, max_days)
            VALUES (%s, %s, %s)
            ON CONFLICT (min_days, max_days)
            DO UPDATE SET label = EXCLUDED.label
            RETURNING id;
            """,
            (label, min_days, max_days),
        )
        return cur.fetchone()[0]


def set_category_period_price(
    conn,
    category_id: int,
    rental_period_id: int,
    price: Decimal,
    sort_order: int,
):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO category_rental_period_prices (
              category_id,
              rental_period_id,
              price,
              sort_order
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (category_id, rental_period_id)
            DO UPDATE SET
              price = EXCLUDED.price,
              sort_order = EXCLUDED.sort_order;
            """,
            (category_id, rental_period_id, price, sort_order),
        )


def replace_category_period_prices(conn, category_id: int, rows: list[tuple[int, Decimal, int]]):
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM category_rental_period_prices WHERE category_id = %s;",
            (category_id,),
        )

    for rental_period_id, price, sort_order in rows:
        set_category_period_price(conn, category_id, rental_period_id, price, sort_order)


def insert_units(conn, category_id: int, sku_prefix: str, count: int):
    with conn.cursor() as cur:
        for n in range(1, count + 1):
            sku = f"{sku_prefix}-{n:02d}"
            cur.execute(
                """
                INSERT INTO items (category_id, sku, is_active)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (sku)
                DO UPDATE SET
                  category_id = EXCLUDED.category_id,
                  is_active = TRUE;
                """,
                (category_id, sku),
            )


def main():
    conn = get_conn()
    try:
        with conn.transaction():
            # Users / customer
            upsert_user(conn, ADMIN_EMAIL, ADMIN_PASSWORD, "admin")
            temp_uid = upsert_user(conn, TEMP_USER_EMAIL, TEMP_USER_PASSWORD, "customer")
            upsert_customer_for_user(conn, temp_uid, "Temp Customer", TEMP_USER_EMAIL, None)

            # Shared rental periods
            rp_1_day = upsert_rental_period(conn, "1 dag", 1, 1)
            rp_2_3 = upsert_rental_period(conn, "2-3 dagar", 2, 3)
            rp_4_7 = upsert_rental_period(conn, "4-7 dagar", 4, 7)

            rp_3 = upsert_rental_period(conn, "3 dagar", 3, 3)
            rp_4_5 = upsert_rental_period(conn, "4-5 dagar", 4, 5)
            rp_6_7 = upsert_rental_period(conn, "6-7 dagar", 6, 7)

            # Furnishings
            bord = upsert_category(conn, "Bord")
            upsert_furn_category(conn, bord, "table", None, "Populärt till festen")
            replace_category_period_prices(
                conn,
                bord,
                [
                    (rp_1_day, Decimal("70"), 0),
                    (rp_2_3, Decimal("80"), 1),
                    (rp_4_7, Decimal("95"), 2),
                ],
            )
            insert_units(conn, bord, "FURN-BORD", 16)

            stolar_premium = upsert_category(conn, "Stolar premium")
            upsert_furn_category(conn, stolar_premium, "chair_premium", None, "Premiumstolar per styck")
            replace_category_period_prices(
                conn,
                stolar_premium,
                [
                    (rp_1_day, Decimal("19"), 0),
                    (rp_2_3, Decimal("20"), 1),
                    (rp_4_7, Decimal("25"), 2),
                ],
            )
            insert_units(conn, stolar_premium, "FURN-STOL-PREMIUM", 60)

            stolar_standard = upsert_category(conn, "Stolar standard")
            upsert_furn_category(conn, stolar_standard, "chair_standard", None, "Standardstolar per styck")
            replace_category_period_prices(
                conn,
                stolar_standard,
                [
                    (rp_1_day, Decimal("19"), 0),
                    (rp_2_3, Decimal("20"), 1),
                    (rp_4_7, Decimal("25"), 2),
                ],
            )
            insert_units(conn, stolar_standard, "FURN-STOL-STANDARD", 30)

            bankset_stor = upsert_category(conn, "Bänkset stor")
            upsert_furn_category(conn, bankset_stor, "bench_set_large", None, "Perfekt för större grupper")
            replace_category_period_prices(
                conn,
                bankset_stor,
                [
                    (rp_1_day, Decimal("200"), 0),
                    (rp_2_3, Decimal("249"), 1),
                    (rp_4_7, Decimal("319"), 2),
                ],
            )
            insert_units(conn, bankset_stor, "FURN-BANKSET-STOR", 13)

            bankset_sma = upsert_category(conn, "Bänkset små")
            upsert_furn_category(conn, bankset_sma, "bench_set_small", None, "Mindre bänkset")
            replace_category_period_prices(
                conn,
                bankset_sma,
                [
                    (rp_1_day, Decimal("200"), 0),
                    (rp_2_3, Decimal("249"), 1),
                    (rp_4_7, Decimal("319"), 2),
                ],
            )
            insert_units(conn, bankset_sma, "FURN-BANKSET-SMA", 10)

            ljusslinga_10m = upsert_category(conn, "Ljusslinga 10m")
            upsert_furn_category(conn, ljusslinga_10m, "light_string_10m", None, "Ljusslinga 10 meter")
            replace_category_period_prices(
                conn,
                ljusslinga_10m,
                [
                    (rp_1_day, Decimal("299"), 0),
                    (rp_2_3, Decimal("349"), 1),
                    (rp_4_7, Decimal("399"), 2),
                ],
            )
            insert_units(conn, ljusslinga_10m, "FURN-LJUSSLINGA-10M", 4)

            ljusslinga_15m = upsert_category(conn, "Ljusslinga 15m")
            upsert_furn_category(conn, ljusslinga_15m, "light_string_15m", None, "Ljusslinga 15 meter")
            replace_category_period_prices(
                conn,
                ljusslinga_15m,
                [
                    (rp_1_day, Decimal("299"), 0),
                    (rp_2_3, Decimal("349"), 1),
                    (rp_4_7, Decimal("399"), 2),
                ],
            )
            insert_units(conn, ljusslinga_15m, "FURN-LJUSSLINGA-15M", 1)

            # Tents - exactly one of each
            tent_3x3 = upsert_category(conn, "Tält 3×3 m")
            upsert_tent_category(
                conn,
                tent_3x3,
                capacity=3,
                season_rating=2,
                build_time=20,
                setup_service_fee=Decimal("0"),
                floor_area_m2=Decimal("9.0"),
            )
            replace_category_period_prices(
                conn,
                tent_3x3,
                [
                    (rp_3, Decimal("149"), 0),
                    (rp_4_5, Decimal("249"), 1),
                    (rp_6_7, Decimal("379"), 2),
                ],
            )
            insert_units(conn, tent_3x3, "TENT-3X3", 1)

            tent_5x3 = upsert_category(conn, "Tält 5×3 m")
            upsert_tent_category(
                conn,
                tent_5x3,
                capacity=16,
                season_rating=3,
                build_time=50,
                setup_service_fee=Decimal("1199"),
                floor_area_m2=Decimal("15.0"),
            )
            replace_category_period_prices(
                conn,
                tent_5x3,
                [
                    (rp_3, Decimal("999"), 0),
                    (rp_4_5, Decimal("1499"), 1),
                    (rp_6_7, Decimal("1899"), 2),
                ],
            )
            insert_units(conn, tent_5x3, "TENT-5X3", 1)

            tent_6x4 = upsert_category(conn, "Tält 6×4 m")
            upsert_tent_category(
                conn,
                tent_6x4,
                capacity=30,
                season_rating=4,
                build_time=70,
                setup_service_fee=Decimal("1499"),
                floor_area_m2=Decimal("24.0"),
            )
            replace_category_period_prices(
                conn,
                tent_6x4,
                [
                    (rp_3, Decimal("1399"), 0),
                    (rp_4_5, Decimal("1999"), 1),
                    (rp_6_7, Decimal("2499"), 2),
                ],
            )
            insert_units(conn, tent_6x4, "TENT-6X4", 1)

            tent_8x4 = upsert_category(conn, "Tält 8×4 m")
            upsert_tent_category(
                conn,
                tent_8x4,
                capacity=35,
                season_rating=3,
                build_time=78,
                setup_service_fee=Decimal("1399"),
                floor_area_m2=Decimal("32.0"),
            )
            replace_category_period_prices(
                conn,
                tent_8x4,
                [
                    (rp_3, Decimal("1399"), 0),
                    (rp_4_5, Decimal("1699"), 1),
                    (rp_6_7, Decimal("2199"), 2),
                ],
            )
            insert_units(conn, tent_8x4, "TENT-8X4", 1)

            tent_5x10 = upsert_category(conn, "Tält 5×10 m")
            upsert_tent_category(
                conn,
                tent_5x10,
                capacity=70,
                season_rating=5,
                build_time=270,
                setup_service_fee=Decimal("2399"),
                floor_area_m2=Decimal("50.0"),
            )
            replace_category_period_prices(
                conn,
                tent_5x10,
                [
                    (rp_3, Decimal("1799"), 0),
                    (rp_4_5, Decimal("2599"), 1),
                    (rp_6_7, Decimal("3299"), 2),
                ],
            )
            insert_units(conn, tent_5x10, "TENT-5X10", 1)

            tent_6x6 = upsert_category(conn, "Tält 6×6 m")
            upsert_tent_category(
                conn,
                tent_6x6,
                capacity=45,
                season_rating=5,
                build_time=220,
                setup_service_fee=Decimal("1999"),
                floor_area_m2=Decimal("36.0"),
            )
            replace_category_period_prices(
                conn,
                tent_6x6,
                [
                    (rp_3, Decimal("1499"), 0),
                    (rp_4_5, Decimal("2399"), 1),
                    (rp_6_7, Decimal("2999"), 2),
                ],
            )
            insert_units(conn, tent_6x6, "TENT-6X6", 1)

            tent_8x5 = upsert_category(conn, "Tält 8×5 m")
            upsert_tent_category(
                conn,
                tent_8x5,
                capacity=50,
                season_rating=5,
                build_time=110,
                setup_service_fee=Decimal("1699"),
                floor_area_m2=Decimal("40.0"),
            )
            replace_category_period_prices(
                conn,
                tent_8x5,
                [
                    (rp_3, Decimal("1599"), 0),
                    (rp_4_5, Decimal("2099"), 1),
                    (rp_6_7, Decimal("2599"), 2),
                ],
            )
            insert_units(conn, tent_8x5, "TENT-8X5", 1)

            tent_6x10 = upsert_category(conn, "Tält 6×10 m")
            upsert_tent_category(
                conn,
                tent_6x10,
                capacity=80,
                season_rating=5,
                build_time=300,
                setup_service_fee=Decimal("2599"),
                floor_area_m2=Decimal("60.0"),
            )
            replace_category_period_prices(
                conn,
                tent_6x10,
                [
                    (rp_3, Decimal("2099"), 0),
                    (rp_4_5, Decimal("2999"), 1),
                    (rp_6_7, Decimal("3999"), 2),
                ],
            )
            insert_units(conn, tent_6x10, "TENT-6X10", 1)

        print("Seed done.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()