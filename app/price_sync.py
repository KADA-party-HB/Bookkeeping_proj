from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .sql import (
    SQL_LIST_CATEGORIES,
    SQL_LIST_RENTAL_PERIODS,
    SQL_UPSERT_CATEGORY_RENTAL_PERIOD_PRICE,
)


_PRICE_FILE_PATH = Path(__file__).with_name("prices.json")
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


def load_price_catalog() -> dict:
    return json.loads(_PRICE_FILE_PATH.read_text(encoding="utf-8"))


def apply_price_catalog(cur) -> dict:
    catalog = load_price_catalog()
    product_rows = catalog.get("products")
    if not isinstance(product_rows, list) or not product_rows:
        raise ValueError("prices.json must contain a non-empty 'products' list.")

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
                    (_to_decimal(setup_service_fee, field_name=f"{product_label} setup_service_fee"), category["id"]),
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
        "source_path": str(_PRICE_FILE_PATH),
    }
