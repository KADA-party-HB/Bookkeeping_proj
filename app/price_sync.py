from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .sql import (
    SQL_LIST_ALL_CATEGORY_RENTAL_PERIOD_PRICES,
    SQL_LIST_CATEGORIES,
    SQL_LIST_RENTAL_PERIODS,
    SQL_UPSERT_CATEGORY_RENTAL_PERIOD_PRICE,
)


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _normalize_key(value: str | None) -> str:
    text = (value or "").strip().casefold()
    return _NON_ALNUM_RE.sub("", text)


def _to_decimal(value, *, field_name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid decimal value for {field_name}: {value!r}") from exc

    if amount < 0:
        raise ValueError(f"{field_name} must be 0 or greater.")

    return amount.quantize(Decimal("0.01"))


def _format_decimal(value) -> str:
    if value is None:
        return "0.00"
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


def load_price_catalog_from_bytes(data: bytes) -> dict:
    if not data:
        raise ValueError("The uploaded JSON file is empty.")

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("The uploaded file must be valid UTF-8 JSON.") from exc

    try:
        catalog = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON file: {exc.msg}.") from exc

    if not isinstance(catalog, dict):
        raise ValueError("The uploaded JSON file must contain an object at the top level.")

    return catalog


def export_price_catalog(cur) -> dict:
    cur.execute(SQL_LIST_CATEGORIES)
    categories = cur.fetchall()

    cur.execute(SQL_LIST_RENTAL_PERIODS)
    rental_periods = cur.fetchall()

    cur.execute(SQL_LIST_ALL_CATEGORY_RENTAL_PERIOD_PRICES)
    price_rows = cur.fetchall()

    prices_by_category_id: dict[int, list] = {}
    for row in price_rows:
        prices_by_category_id.setdefault(row["category_id"], []).append(row)

    products = []
    for category in categories:
        category_prices = prices_by_category_id.get(category["id"], [])
        rental_period_prices = {
            row["label"]: _format_decimal(row["price"])
            for row in category_prices
        }

        if category["is_tent"]:
            category_type = "tent"
        elif category["is_furnishing"]:
            category_type = "furnishing"
        else:
            category_type = "item"

        product = {
            "label": category["display_name"],
            "category": category["display_name"],
            "category_id": category["id"],
            "category_type": category_type,
            "applies_to_categories": [category["display_name"]],
            "rental_period_prices": rental_period_prices,
        }

        if category["is_tent"] and category["setup_service_fee"] is not None:
            product["setup_service_fee"] = _format_decimal(category["setup_service_fee"])

        products.append(product)

    return {
        "schema_version": 1,
        "source": "database",
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "rental_periods": [
            {
                "id": row["id"],
                "label": row["label"],
                "min_days": row["min_days"],
                "max_days": row["max_days"],
            }
            for row in rental_periods
        ],
        "products": products,
    }


def apply_price_catalog(cur, catalog: dict) -> dict:
    product_rows = catalog.get("products")
    if not isinstance(product_rows, list) or not product_rows:
        raise ValueError("The JSON file must contain a non-empty 'products' list.")

    cur.execute(SQL_LIST_CATEGORIES)
    categories = cur.fetchall()

    cur.execute(SQL_LIST_RENTAL_PERIODS)
    rental_periods = cur.fetchall()

    categories_by_name = {
        _normalize_key(row["display_name"]): row
        for row in categories
    }
    rental_periods_by_label = {
        _normalize_key(row["label"]): row
        for row in rental_periods
    }
    rental_period_sort_order = {
        row["id"]: index
        for index, row in enumerate(rental_periods)
    }

    updated_category_names: set[str] = set()
    missing_category_targets: list[str] = []
    missing_period_labels: set[str] = set()
    updated_period_prices = 0
    updated_setup_fees = 0

    for product in product_rows:
        if not isinstance(product, dict):
            continue

        product_label = (
            product.get("label")
            or product.get("sheet_product")
            or product.get("category")
            or "Unnamed product"
        )
        target_names = product.get("applies_to_categories") or []
        if not target_names and product.get("category"):
            target_names = [product["category"]]

        matched_categories = []
        seen_category_ids = set()
        for target_name in target_names:
            category = categories_by_name.get(_normalize_key(target_name))
            if not category:
                missing_category_targets.append(f"{product_label}: {target_name}")
                continue
            if category["id"] in seen_category_ids:
                continue
            seen_category_ids.add(category["id"])
            matched_categories.append(category)

        if not matched_categories:
            continue

        rental_period_prices = product.get("rental_period_prices") or {}
        setup_service_fee = product.get("setup_service_fee")

        for category in matched_categories:
            category_changed = False

            if setup_service_fee is not None and category.get("is_tent"):
                cur.execute(
                    """
                    UPDATE tent_categories
                    SET setup_service_fee = %s
                    WHERE category_id = %s;
                    """,
                    (
                        _to_decimal(
                            setup_service_fee,
                            field_name=f"{product_label} setup_service_fee",
                        ),
                        category["id"],
                    ),
                )
                updated_setup_fees += 1
                category_changed = True

            for period_label, raw_price in rental_period_prices.items():
                rental_period = rental_periods_by_label.get(_normalize_key(period_label))
                if not rental_period:
                    missing_period_labels.add(str(period_label))
                    continue

                cur.execute(
                    SQL_UPSERT_CATEGORY_RENTAL_PERIOD_PRICE,
                    (
                        category["id"],
                        rental_period["id"],
                        _to_decimal(raw_price, field_name=f"{product_label} {period_label}"),
                        rental_period_sort_order[rental_period["id"]],
                    ),
                )
                updated_period_prices += 1
                category_changed = True

            if category_changed:
                updated_category_names.add(category["display_name"])

    return {
        "updated_categories": sorted(updated_category_names),
        "updated_period_prices": updated_period_prices,
        "updated_setup_fees": updated_setup_fees,
        "missing_category_targets": missing_category_targets,
        "missing_period_labels": sorted(missing_period_labels),
    }
