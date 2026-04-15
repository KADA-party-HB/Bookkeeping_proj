from flask import (
    Blueprint,
    current_app,
    request,
    render_template,
    redirect,
    url_for,
    flash,
    session,
    abort,
    jsonify,
)

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from werkzeug.security import generate_password_hash

from .db import PaginationOptions, paginate_query, query, execute, tx
from .delivery import (
    DeliveryAddressValidationError,
    DeliveryServiceError,
    resolve_delivery_quote,
)
from .sql import (
    # auth / users
    SQL_CREATE_USER,
    SQL_GET_USER_BY_EMAIL,

    # customers
    SQL_GET_CUSTOMER_BY_EMAIL,
    SQL_LIST_CUSTOMERS,
    SQL_GET_CUSTOMER,
    SQL_GET_CUSTOMER_BY_FULL_NAME,
    SQL_GET_CUSTOMER_BY_USER_ID,
    SQL_CREATE_CUSTOMER,
    SQL_LIST_BOOKINGS_FOR_CUSTOMER,
    SQL_GET_CUSTOMER_FOR_EDIT,
    SQL_UPDATE_CUSTOMER,
    SQL_EXPIRE_STALE_PENDING_BOOKINGS,
    SQL_ACTIVE_PENDING_BOOKING_COUNT,

    # rental periods
    SQL_LIST_RENTAL_PERIODS,
    SQL_GET_RENTAL_PERIOD,
    SQL_CREATE_RENTAL_PERIOD,
    SQL_UPDATE_RENTAL_PERIOD,
    SQL_DELETE_RENTAL_PERIOD,
    SQL_RENTAL_PERIOD_USAGE_COUNT,

    # booking
    SQL_AVAILABLE_CATEGORIES,
    SQL_FIND_CATEGORY_RENTAL_PRICING,
    SQL_CREATE_BOOKING,
    SQL_CREATE_BOOKING_WITH_ALLOCATIONS,

    # items
    SQL_LIST_ITEMS,
    SQL_LIST_CATEGORIES_FOR_DROPDOWN,
    SQL_GET_ITEM_FOR_EDIT,
    SQL_UPDATE_ITEM,
    SQL_CREATE_ITEM,
    SQL_ITEM_HAS_ACTIVE_OR_FUTURE_BOOKING,
    SQL_DELETE_BOOKING_ITEMS_FOR_ITEM,
    SQL_DELETE_ITEM,

    # categories
    SQL_LIST_CATEGORIES,
    SQL_GET_CATEGORY_FOR_EDIT,
    SQL_CREATE_CATEGORY,
    SQL_CREATE_TENT_CATEGORY_ROW,
    SQL_CREATE_FURN_CATEGORY_ROW,
    SQL_UPDATE_CATEGORY_BASE,
    SQL_UPDATE_TENT_CATEGORY,
    SQL_UPDATE_FURN_CATEGORY,

    # category rental period pricing
    SQL_LIST_CATEGORY_RENTAL_PERIOD_PRICES,
    SQL_UPSERT_CATEGORY_RENTAL_PERIOD_PRICE,

    # booking details
    SQL_BOOKING_DETAIL,
    SQL_BOOKING_DETAIL_FOR_CUSTOMER,
    SQL_BOOKING_ITEMS,
    SQL_BOOKING_ITEMS_FOR_BOOKINGS,
    SQL_BOOKING_TOTAL,
    SQL_LIST_ALL_BOOKINGS,
    SQL_CONFIRM_BOOKING,
    SQL_CANCEL_BOOKING,
    SQL_DELETE_BOOKING,
    SQL_UPDATE_BOOKING_ADMIN_FIELDS,
    SQL_BOOKING_ALLOCATION_CANDIDATES,
    SQL_DELETE_BOOKING_ITEMS_FOR_BOOKING,
    SQL_INSERT_BOOKING_ITEM,
)

bp = Blueprint("routes", __name__)

DELIVERY_BASE_FEE = Decimal("449.00")
DELIVERY_INCLUDED_DISTANCE_KM = Decimal("10")
DELIVERY_EXTRA_FEE_PER_KM = Decimal("5.00")
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


def current_user():
    return session.get("user_id"), session.get("role")


def require_login():
    uid, role = current_user()
    if not uid:
        return None, None
    return uid, role


def require_admin():
    uid, role = require_login()
    if not uid:
        abort(403)
    if role != "admin":
        abort(403)
    return uid, role


def _to_bool(value):
    return value in ("on", "true", "1", "yes")


def _to_int_or_none(value):
    value = (value or "").strip()
    return int(value) if value != "" else None


def _to_str_or_none(value):
    value = (value or "").strip()
    return value if value != "" else None


def _normalize_email(value):
    return (value or "").strip().lower()


def _expire_stale_pending_bookings():
    execute(
        SQL_EXPIRE_STALE_PENDING_BOOKINGS,
        (current_app.config["PENDING_BOOKING_HOLD_DAYS"],),
    )


def _customer_pending_booking_limit_reached(customer_id: int) -> bool:
    row = query(
        SQL_ACTIVE_PENDING_BOOKING_COUNT,
        (
            customer_id,
            current_app.config["PENDING_BOOKING_HOLD_DAYS"],
        ),
        one=True,
    )
    return (row["pending_count"] if row else 0) >= current_app.config[
        "MAX_ACTIVE_PENDING_BOOKINGS_PER_CUSTOMER"
    ]


def _pending_booking_hold_label() -> str:
    days = current_app.config["PENDING_BOOKING_HOLD_DAYS"]
    return f"{days} dag{'ar' if days != 1 else ''}"


def _pagination_options(*, default_per_page=DEFAULT_PAGE_SIZE):
    return PaginationOptions.from_mapping(
        request.args,
        default_per_page=default_per_page,
        max_per_page=MAX_PAGE_SIZE,
    )


@bp.app_context_processor
def inject_pagination_helpers():
    def pagination_url(*, page=None, per_page=None):
        if not request.endpoint:
            return "#"

        args = request.args.to_dict(flat=True)
        if page is not None:
            args["page"] = page
        if per_page is not None:
            args["per_page"] = per_page
            if page is None:
                args["page"] = 1

        return url_for(request.endpoint, **(request.view_args or {}), **args)

    return {"pagination_url": pagination_url}


def _delivery_validation_error_message(code: str) -> str:
    error_map = {
        "missing_address": "Ange en leveransadress.",
        "address_not_found": "Vi kunde inte hitta den adressen.",
        "address_too_broad": "Ange en mer exakt gatuadress.",
        "address_low_confidence": "Vi kunde inte verifiera adressen tillräckligt noggrant. Lägg till mer information.",
    }
    return error_map.get(code, "Vi kunde inte validera leveransadressen.")


def _delivery_service_error_message(code: str) -> str:
    error_map = {
        "map_api_not_configured": "Validering av leveransadress är inte konfigurerad ännu.",
        "delivery_origin_not_configured": "Leveransursprunget är inte konfigurerat ännu.",
        "map_api_connection_error": "Vi kunde inte nå karttjänsten just nu.",
        "map_api_http_error": "Karttjänsten returnerade ett fel.",
        "map_api_invalid_response": "Karttjänsten returnerade ogiltiga data.",
        "route_not_found": "Vi kunde inte beräkna en leveransrutt för den adressen.",
    }
    return error_map.get(code, "Vi kunde inte beräkna leverans just nu.")


@bp.before_app_request
def expire_stale_pending_bookings_before_request():
    _expire_stale_pending_bookings()


def _calculate_delivery_fee_from_distance(distance_km_value):
    distance_text = (distance_km_value or "").strip().replace(",", ".")
    if distance_text == "":
        raise ValueError("missing_delivery_distance")

    try:
        distance_km = Decimal(distance_text)
    except InvalidOperation as exc:
        raise ValueError("invalid_delivery_distance") from exc

    if distance_km < 0:
        raise ValueError("negative_delivery_distance")

    extra_distance = max(distance_km - DELIVERY_INCLUDED_DISTANCE_KM, Decimal("0"))
    delivery_fee = DELIVERY_BASE_FEE + (extra_distance * DELIVERY_EXTRA_FEE_PER_KM)
    return delivery_fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _parse_manual_delivery_fee(delivery_fee_value):
    fee_text = (delivery_fee_value or "").strip().replace(",", ".")
    if fee_text == "":
        raise ValueError("missing_delivery_fee_override")

    try:
        delivery_fee = Decimal(fee_text)
    except InvalidOperation as exc:
        raise ValueError("invalid_delivery_fee_override") from exc

    if delivery_fee < 0:
        raise ValueError("negative_delivery_fee_override")

    return delivery_fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _build_booking_item_summary(items):
    summary_map = {}
    summary_rows = []

    for item in items:
        if item.get("is_tent"):
            type_label = "Tent"
        elif item.get("is_furnishing"):
            type_label = "Furnishing"
        else:
            type_label = "Item"

        key = (
            item.get("category_id"),
            item.get("display_name"),
            type_label,
            item.get("quoted_period_label"),
            item.get("quoted_period_price"),
            item.get("effective_setup_fee"),
            item.get("custom_total_price"),
            item.get("effective_line_total"),
        )

        if key not in summary_map:
            summary_map[key] = {
                "category_id": item.get("category_id"),
                "display_name": item.get("display_name"),
                "type_label": type_label,
                "quoted_period_label": item.get("quoted_period_label"),
                "quoted_period_price": item.get("quoted_period_price"),
                "effective_setup_fee": item.get("effective_setup_fee"),
                "custom_total_price": item.get("custom_total_price"),
                "effective_line_total": item.get("effective_line_total"),
                "quantity": 0,
                "group_total": 0,
            }
            summary_rows.append(summary_map[key])

        summary_map[key]["quantity"] += 1
        summary_map[key]["group_total"] += item.get("effective_line_total") or 0

    return summary_rows


def _query_available_categories(start_date: str, end_date: str):
    return query(SQL_AVAILABLE_CATEGORIES, (start_date, end_date))


def _load_booking_allocation_candidates(
    cur,
    category_id: int,
    start_date: str,
    end_date: str,
    *,
    current_booking_id=None,
):
    cur.execute(
        SQL_BOOKING_ALLOCATION_CANDIDATES,
        (current_booking_id, start_date, end_date, category_id),
    )
    return cur.fetchall()


def _format_turnaround_item_labels(item_labels):
    labels = [label for label in dict.fromkeys(item_labels) if label]
    return ", ".join(labels)

def _build_full_delivery_address(address, postal_city):
    parts = []
    address_text = (address or "").strip()
    postal_city_text = _sanitize_postal_city(postal_city) or ""

    if address_text:
        parts.append(address_text)
    if postal_city_text:
        parts.append(postal_city_text)

    return ", ".join(parts) if parts else None


_POSTAL_CITY_POSTAL_CODE_RE = re.compile(r"^(?:SE[-\s]?)?\d{3}\s?\d{2}\s*", re.IGNORECASE)


def _sanitize_postal_city(value):
    text = _to_str_or_none(value)
    if text is None:
        return None

    text = re.sub(r"\s+", " ", text).strip(" ,")
    text = _POSTAL_CITY_POSTAL_CODE_RE.sub("", text).strip(" ,")
    text = re.sub(r"\s+", " ", text).strip(" ,")
    return text or None


def _create_admin_booking_with_allocations(
    cur,
    *,
    customer_id,
    start_date: str,
    end_date: str,
    selections,
    include_delivery: bool,
    delivery_fee,
    delivery_address,
    delivery_distance_km,
    include_setup_service: bool,
    booking_custom_total_price,
    booking_custom_price_note,
    booking_note,
    custom_total_prices,
    custom_price_notes,
    category_context_by_id,
):
    cur.execute(
        SQL_CREATE_BOOKING,
        (
            customer_id,
            start_date,
            end_date,
            include_delivery,
            delivery_fee,
            delivery_address,
            delivery_distance_km,
            include_setup_service,
            booking_custom_total_price,
            booking_custom_price_note,
            booking_note,
            None,
        ),
    )
    booking_id = cur.fetchone()["id"]

    turnaround_item_labels = []
    rental_days = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days + 1

    for idx, (category_id, qty) in enumerate(selections):
        category_context = category_context_by_id[category_id]

        cur.execute(SQL_FIND_CATEGORY_RENTAL_PRICING, (category_id, rental_days))
        pricing_row = cur.fetchone()

        custom_total_price = custom_total_prices[idx]
        custom_price_note = custom_price_notes[idx]

        if pricing_row:
            rental_period_id = pricing_row["rental_period_id"]
            quoted_period_label = pricing_row["period_label"]
            quoted_period_price = pricing_row["period_price"]
        else:
            if custom_total_price is None and booking_custom_total_price is None:
                raise ValueError(
                    f'{category_context["display_name"]} needs a custom price because no standard price matches the selected dates, unless you set a booking total override.'
                )
            rental_period_id = None
            quoted_period_label = None
            quoted_period_price = None

        setup_service_fee = (
            category_context["setup_service_fee"]
            if include_setup_service and category_context["is_tent"]
            else None
        )

        candidates = _load_booking_allocation_candidates(
            cur,
            category_id,
            start_date,
            end_date,
        )
        chosen_candidates = candidates[:qty]

        if len(chosen_candidates) < qty:
            raise ValueError(
                f'Cannot place booking because only {len(chosen_candidates)} of {qty} items are available in "{category_context["display_name"]}".'
            )

        for candidate in chosen_candidates:
            cur.execute(
                SQL_INSERT_BOOKING_ITEM,
                (
                    booking_id,
                    candidate["item_id"],
                    rental_period_id,
                    quoted_period_label,
                    quoted_period_price,
                    setup_service_fee,
                    custom_total_price,
                    custom_price_note,
                    None,
                ),
            )
            if candidate["is_turnaround"]:
                turnaround_item_labels.append(
                    f'{category_context["display_name"]} ({candidate["sku"]})'
                )

    return booking_id, turnaround_item_labels


def _reallocate_booking_items_for_dates(
    cur,
    booking_id: int,
    start_date: str,
    end_date: str,
    *,
    include_setup_service: bool,
    booking_has_total_override: bool,
):
    cur.execute(SQL_BOOKING_ITEMS, (booking_id,))
    current_items = cur.fetchall()
    if not current_items:
        return 0, 0, []

    rows_by_category = {}
    for row in current_items:
        rows_by_category.setdefault(row["category_id"], []).append(row)

    reassigned_rows = []
    moved_rows_with_metadata = 0
    turnaround_item_labels = []
    rental_days = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days + 1
    pricing_by_category = {}

    for category_rows in rows_by_category.values():
        category_id = category_rows[0]["category_id"]
        display_name = category_rows[0]["display_name"]
        current_item_ids = {row["item_id"] for row in category_rows}

        cur.execute(SQL_FIND_CATEGORY_RENTAL_PRICING, (category_id, rental_days))
        pricing_by_category[category_id] = cur.fetchone()

        candidates = _load_booking_allocation_candidates(
            cur,
            category_id,
            start_date,
            end_date,
            current_booking_id=booking_id,
        )
        candidates.sort(
            key=lambda candidate: (
                1 if candidate["is_turnaround"] else 0,
                0 if candidate["item_id"] in current_item_ids else 1,
                candidate["item_id"],
            )
        )

        needed_count = len(category_rows)
        chosen_candidates = candidates[:needed_count]
        if len(chosen_candidates) < needed_count:
            raise ValueError(
                f'Cannot move booking to these dates because only {len(chosen_candidates)} of {needed_count} items are available in "{display_name}".'
            )

        candidate_by_item_id = {candidate["item_id"]: candidate for candidate in chosen_candidates}
        chosen_ids = set(candidate_by_item_id)
        kept_ids = set()
        pending_rows = []

        for row in category_rows:
            if row["item_id"] in chosen_ids and row["item_id"] not in kept_ids:
                reassigned_rows.append((row, row["item_id"], candidate_by_item_id[row["item_id"]]))
                kept_ids.add(row["item_id"])
            else:
                pending_rows.append(row)

        remaining_ids = [
            candidate["item_id"]
            for candidate in chosen_candidates
            if candidate["item_id"] not in kept_ids
        ]

        for row, new_item_id in zip(pending_rows, remaining_ids):
            reassigned_rows.append((row, new_item_id, candidate_by_item_id[new_item_id]))

    cur.execute(SQL_DELETE_BOOKING_ITEMS_FOR_BOOKING, (booking_id,))

    reallocated_count = 0
    for row, new_item_id, candidate in reassigned_rows:
        pricing_row = pricing_by_category[row["category_id"]]

        if pricing_row:
            rental_period_id = pricing_row["rental_period_id"]
            quoted_period_label = pricing_row["period_label"]
            quoted_period_price = pricing_row["period_price"]
        else:
            has_line_override = row["custom_total_price"] is not None
            if not has_line_override and not booking_has_total_override:
                raise ValueError(
                    f'Cannot move booking to these dates because "{row["display_name"]}" has no standard price configured for {rental_days} day{"s" if rental_days != 1 else ""}.'
                )
            rental_period_id = None
            quoted_period_label = None
            quoted_period_price = None

        setup_service_fee = (
            row["current_setup_service_fee"]
            if include_setup_service and row["is_tent"]
            else None
        )

        cur.execute(
            SQL_INSERT_BOOKING_ITEM,
            (
                booking_id,
                new_item_id,
                rental_period_id,
                quoted_period_label,
                quoted_period_price,
                setup_service_fee,
                row["custom_total_price"],
                row["custom_price_note"],
                row["line_note"],
            ),
        )
        if candidate["is_turnaround"]:
            turnaround_item_labels.append(f'{row["display_name"]} ({candidate["sku"]})')
        if row["item_id"] != new_item_id:
            reallocated_count += 1
            if (
                row["line_note"]
                or row["custom_total_price"] is not None
                or row["custom_price_note"]
            ):
                moved_rows_with_metadata += 1

    return reallocated_count, moved_rows_with_metadata, turnaround_item_labels


def _collect_category_period_prices_from_form():
    """
    Reads fields in the pattern:
      period_price_<rental_period_id>
      period_sort_<rental_period_id>

    Returns:
      [
        {"rental_period_id": 1, "price": "1499", "sort_order": 0},
        ...
      ]
    """
    rows = []

    for key, value in request.form.items():
        if not key.startswith("period_price_"):
            continue

        raw_id = key.split("period_price_", 1)[1].strip()
        if not raw_id:
            continue

        try:
            rental_period_id = int(raw_id)
        except ValueError:
            continue

        price = (value or "").strip()
        if price == "":
            continue

        sort_order = (request.form.get(f"period_sort_{rental_period_id}", "") or "").strip()
        sort_order = int(sort_order) if sort_order != "" else 0

        rows.append(
            {
                "rental_period_id": rental_period_id,
                "price": price,
                "sort_order": sort_order,
            }
        )

    return rows


def _load_customer_profile_for_user(user_id: int):
    if not user_id:
        return None
    return query(SQL_GET_CUSTOMER_BY_USER_ID, (user_id,), one=True)

def _collect_selected_quantities_from_form():
    """
    Reads duplicate qty_<category_id> fields safely.
    This handles responsive forms where both mobile and desktop inputs
    may exist with the same field name, and uses the highest submitted qty.
    """
    selections = []
    seen_category_ids = set()

    for key in request.form.keys():
        if not key.startswith("qty_"):
            continue

        try:
            category_id = int(key.split("_", 1)[1])
        except Exception:
            continue

        if category_id in seen_category_ids:
            continue
        seen_category_ids.add(category_id)

        raw_values = request.form.getlist(key)

        parsed_values = []
        for raw in raw_values:
            raw = (raw or "").strip()
            if raw == "":
                parsed_values.append(0)
                continue
            try:
                parsed_values.append(int(raw))
            except ValueError:
                parsed_values.append(0)

        qty = max(parsed_values) if parsed_values else 0

        if qty <= 0:
            continue

        selections.append((category_id, qty))

    return selections


# Home (category availability)
@bp.get("/")
def home():
    uid, role = current_user()
    start = request.args.get("start_date", "")
    end = request.args.get("end_date", "")

    categories = None
    customers = None
    customer_profile = None

    if start and end:
        categories = _query_available_categories(start, end)

        if role == "admin":
            customers = query(SQL_LIST_CUSTOMERS)

    if role == "customer" and uid:
        customer_profile = _load_customer_profile_for_user(uid)

    if role == "admin":
        return render_template(
            "home.html",
            start_date=start,
            end_date=end,
            categories=categories,
            customers=customers,
            role=role,
        )

    return render_template(
        "guest_home.html",
        start_date=start,
        end_date=end,
        categories=categories,
        customer_profile=customer_profile,
        role=role,
    )


@bp.post("/guest/delivery-quote")
def guest_delivery_quote():
    payload = request.get_json(silent=True) or {}
    address = (payload.get("address") or "").strip()
    current_app.logger.info(
        "guest_delivery_quote_requested address=%r",
        address,
    )

    try:
        quote = resolve_delivery_quote(address)
    except DeliveryAddressValidationError as exc:
        current_app.logger.info(
            "guest_delivery_quote_validation_failed address=%r error_code=%s",
            address,
            exc.code,
        )
        return (
            jsonify(
                {
                    "ok": False,
                    "error": _delivery_validation_error_message(exc.code),
                    "error_code": exc.code,
                }
            ),
            422,
        )
    except DeliveryServiceError as exc:
        current_app.logger.warning(
            "guest_delivery_quote_service_failed address=%r error_code=%s",
            address,
            exc.code,
        )
        return (
            jsonify(
                {
                    "ok": False,
                    "error": _delivery_service_error_message(exc.code),
                    "error_code": exc.code,
                }
            ),
            503,
        )

    delivery_fee = _calculate_delivery_fee_from_distance(str(quote["distance_km"]))
    current_app.logger.info(
        "guest_delivery_quote_succeeded address=%r formatted=%r distance_km=%s delivery_fee=%s confidence=%s result_type=%r",
        address,
        quote["formatted_address"],
        str(quote["distance_km"]),
        str(delivery_fee),
        str(quote["confidence"]),
        quote["result_type"],
    )
    return jsonify(
        {
            "ok": True,
            "formatted_address": quote["formatted_address"],
            "distance_km": str(quote["distance_km"]),
            "delivery_fee": str(delivery_fee),
            "confidence": str(quote["confidence"]),
            "result_type": quote["result_type"],
        }
    )

@bp.post("/guest/bookings/create")
def guest_booking_create():
    uid, role = current_user()
    if role == "admin":
        abort(403)

    start = request.form.get("start_date", "").strip()
    end = request.form.get("end_date", "").strip()
    if not start or not end:
        flash("Välj datum först.", "error")
        return redirect(url_for("routes.home"))
    if end < start:
        flash("Slutdatum kan inte vara tidigare än startdatum.", "error")
        return redirect(url_for("routes.home", start_date=start, end_date=end))

    customer = _load_customer_profile_for_user(uid) if uid else None
    if uid and not customer:
        flash("Det finns ingen kundprofil kopplad till det här kontot.", "error")
        return redirect(url_for("routes.home", start_date=start, end_date=end))
    if customer and _customer_pending_booking_limit_reached(customer["id"]):
        flash(
            f"Du har redan maximalt antal aktiva väntande bokningar. Väntande bokningar förfaller efter {_pending_booking_hold_label()}.",
            "error",
        )
        return redirect(url_for("routes.customer_detail", customer_id=customer["id"]))

    include_delivery = _to_bool(request.form.get("include_delivery"))
    include_setup_service = _to_bool(request.form.get("include_setup_service"))
    booking_note = _to_str_or_none(request.form.get("booking_note"))

    if include_setup_service and not include_delivery:
        flash("Montering kräver leverans i bokningsformuläret.", "error")
        return redirect(url_for("routes.home", start_date=start, end_date=end))

    account_full_name = request.form.get("full_name", "").strip()
    account_email = _normalize_email(request.form.get("email")) or None
    account_phone = _to_str_or_none(request.form.get("phone"))
    account_address = _to_str_or_none(request.form.get("address"))
    account_postal_city = _sanitize_postal_city(request.form.get("postal_city"))
    account_password = request.form.get("password", "")

    if customer:
        account_full_name = customer["full_name"]
        account_email = customer["email"] or account_email
        account_phone = account_phone if account_phone is not None else customer["phone"]
        account_address = account_address if account_address is not None else customer["address"]
    else:
        if not account_full_name or not account_email or not account_password:
            flash("Namn, e-post och lösenord krävs för att skapa ett konto.", "error")
            return redirect(url_for("routes.home", start_date=start, end_date=end))

        if query(SQL_GET_USER_BY_EMAIL, (account_email,), one=True):
            flash("Den e-postadressen är redan registrerad. Logga in i stället.", "error")
            return redirect(url_for("auth.login_form"))

        if query(SQL_GET_CUSTOMER_BY_EMAIL, (account_email,), one=True):
            flash(
                "Den e-postadressen tillhör redan en befintlig kundprofil. Kontakta personalen för att koppla den till ett konto.",
                "error",
            )
            return redirect(url_for("routes.home", start_date=start, end_date=end))

    delivery_lookup_address = _build_full_delivery_address(account_address, account_postal_city)

    selections = _collect_selected_quantities_from_form()
    category_ids = [category_id for category_id, _ in selections]
    qtys = [qty for _, qty in selections]

    if not selections:
        flash("Välj minst en kategori och antal.", "error")
        return redirect(url_for("routes.home", start_date=start, end_date=end))

    visible_categories = _query_available_categories(start, end)
    visible_by_id = {row["id"]: row for row in visible_categories}

    for category_id, requested_qty in selections:
        category = visible_by_id.get(category_id)
        allowed_items = category["available_items"] if category else 0

        if not category:
            flash(f"Kategori {category_id} är inte längre tillgänglig.", "error")
            return redirect(url_for("routes.home", start_date=start, end_date=end))

        if allowed_items <= 0:
            flash(f"{category['display_name']} har inga tillgängliga artiklar.", "error")
            return redirect(url_for("routes.home", start_date=start, end_date=end))

        if requested_qty > allowed_items:
            flash(
                f'{category["display_name"]} har bara {allowed_items} tillgänglig{"a artiklar" if allowed_items != 1 else " artikel"} för de här datumen.',
                "error",
            )
            return redirect(url_for("routes.home", start_date=start, end_date=end))

        if not category["has_standard_price"]:
            flash(
                f"{category['display_name']} har inget standardpris för de valda datumen.",
                "error",
            )
            return redirect(url_for("routes.home", start_date=start, end_date=end))

    if include_delivery and not delivery_lookup_address:
        flash("Ange leveransadressen innan du skickar bokningen.", "error")
        return redirect(url_for("routes.home", start_date=start, end_date=end))

    try:
        if include_delivery:
            quote = resolve_delivery_quote(delivery_lookup_address)
            delivery_fee = str(_calculate_delivery_fee_from_distance(str(quote["distance_km"])))
            delivery_address = quote["formatted_address"]
            delivery_distance_km = str(quote["distance_km"])
        else:
            delivery_fee = None
            delivery_address = None
            delivery_distance_km = None
    except DeliveryAddressValidationError as exc:
        flash(_delivery_validation_error_message(exc.code), "error")
        return redirect(url_for("routes.home", start_date=start, end_date=end))
    except DeliveryServiceError as exc:
        flash(_delivery_service_error_message(exc.code), "error")
        return redirect(url_for("routes.home", start_date=start, end_date=end))

    try:
        def work(cur):
            effective_customer_id = customer["id"] if customer else None
            created_user = None

            if customer:
                cur.execute(
                    SQL_UPDATE_CUSTOMER,
                    (
                        account_full_name,
                        account_email,
                        account_phone,
                        account_address,
                        account_postal_city,
                        customer["id"],
                    ),
                )
                cur.fetchone()
            else:
                password_hash = generate_password_hash(account_password)
                cur.execute(SQL_CREATE_USER, (account_email, password_hash, "customer"))
                created_user = cur.fetchone()

                cur.execute(
                    SQL_CREATE_CUSTOMER,
                    (
                        account_full_name,
                        account_email,
                        account_phone,
                        account_address,
                        account_postal_city,
                        created_user["id"],
                    ),
                )
                effective_customer_id = cur.fetchone()["id"]

            cur.execute(
                SQL_CREATE_BOOKING_WITH_ALLOCATIONS,
                (
                    effective_customer_id,
                    start,
                    end,
                    category_ids,
                    qtys,
                    include_delivery,
                    delivery_fee,
                    include_setup_service,
                    None,
                    None,
                    booking_note,
                    delivery_address,
                    delivery_distance_km,
                    [None] * len(category_ids),
                    [None] * len(category_ids),
                ),
            )
            booking_row = cur.fetchone()
            return booking_row["booking_id"], created_user, effective_customer_id

        booking_id, created_user, effective_customer_id = tx(work)

        if created_user:
            session.clear()
            session["user_id"] = created_user["id"]
            session["role"] = created_user["role"]

        flash(f"Bokning skapad (id={booking_id}).", "success")
        flash(
            f"Väntande bokningar reserverar lagret i {_pending_booking_hold_label()} om inte personalen bekräftar dem tidigare.",
            "success",
        )
        return redirect(url_for("routes.booking_detail", booking_id=booking_id))
    except Exception as exc:
        flash(f"Kunde inte lägga bokningen: {str(exc)}", "error")
        return redirect(url_for("routes.home", start_date=start, end_date=end))

# Booking create
@bp.post("/bookings/create")
def booking_create_from_home():
    uid, role = require_login()
    if not uid:
        flash("Please log in to place a booking.", "error")
        return redirect(url_for("auth.login_form"))
    if role != "admin":
        flash("Use the guest booking form for customer bookings.", "error")
        return redirect(url_for("routes.home"))

    start = request.form.get("start_date", "").strip()
    end = request.form.get("end_date", "").strip()
    if not start or not end:
        flash("Choose dates first.", "error")
        return redirect(url_for("routes.home"))
    if end < start:
        flash("End date cannot be earlier than start date.", "error")
        return redirect(url_for("routes.home", start_date=start, end_date=end))

    if role == "admin":
        customer_id = request.form.get("customer_id", "").strip()
        create_new_customer = _to_bool(request.form.get("create_new_customer"))
        new_full_name = request.form.get("new_customer_full_name", "").strip()
        new_email = _to_str_or_none(request.form.get("new_customer_email"))
        new_phone = _to_str_or_none(request.form.get("new_customer_phone"))
        new_address = _to_str_or_none(request.form.get("new_customer_address"))
        new_postal_city = _sanitize_postal_city(request.form.get("new_customer_postal_city"))

        if create_new_customer:
            if not new_full_name:
                flash("Full name is required to create a new customer during booking.", "error")
                return redirect(url_for("routes.home", start_date=start, end_date=end))
        elif not customer_id:
            flash("Select a customer or create a new customer.", "error")
            return redirect(url_for("routes.home", start_date=start, end_date=end))
    else:
        cust = query(SQL_GET_CUSTOMER_BY_USER_ID, (uid,), one=True)
        if not cust:
            flash("No customer profile linked to this account.", "error")
            return redirect(url_for("routes.home", start_date=start, end_date=end))
        if _customer_pending_booking_limit_reached(cust["id"]):
            flash(
                f"You already have the maximum number of active pending bookings. Pending bookings expire after {_pending_booking_hold_label()}.",
                "error",
            )
            return redirect(url_for("routes.customer_detail", customer_id=cust["id"]))
        customer_id = str(cust["id"])
        create_new_customer = False

    include_delivery = _to_bool(request.form.get("include_delivery"))
    include_setup_service = _to_bool(request.form.get("include_setup_service"))
    if include_delivery:
        admin_delivery_override = role == "admin" and _to_bool(
            request.form.get("delivery_fee_override_enabled")
        )
        if admin_delivery_override:
            try:
                delivery_fee = str(
                    _parse_manual_delivery_fee(request.form.get("delivery_fee_override"))
                )
            except ValueError as exc:
                error_map = {
                    "missing_delivery_fee_override": "Enter a custom delivery fee.",
                    "invalid_delivery_fee_override": "Enter a valid custom delivery fee.",
                    "negative_delivery_fee_override": "Custom delivery fee must be 0 kr or more.",
                }
                flash(error_map.get(str(exc), "Could not use the custom delivery fee."), "error")
                return redirect(url_for("routes.home", start_date=start, end_date=end))
        else:
            try:
                delivery_fee = str(
                    _calculate_delivery_fee_from_distance(request.form.get("delivery_distance_km"))
                )
            except ValueError as exc:
                error_map = {
                    "missing_delivery_distance": "Enter a delivery distance in km to calculate the delivery fee.",
                    "invalid_delivery_distance": "Enter a valid delivery distance in km.",
                    "negative_delivery_distance": "Delivery distance must be 0 km or more.",
                }
                flash(error_map.get(str(exc), "Could not calculate the delivery fee."), "error")
                return redirect(url_for("routes.home", start_date=start, end_date=end))
    else:
        delivery_fee = None
    booking_note = _to_str_or_none(request.form.get("booking_note"))
    booking_custom_total_price = (
        _to_str_or_none(request.form.get("booking_custom_total_price"))
        if role == "admin"
        else None
    )
    booking_custom_price_note = (
        _to_str_or_none(request.form.get("booking_custom_price_note"))
        if role == "admin"
        else None
    )

    selections = _collect_selected_quantities_from_form()
    custom_total_prices = []
    custom_price_notes = []

    for cat_id, _qty in selections:
        if role == "admin":
            custom_total_prices.append(_to_str_or_none(request.form.get(f"custom_price_{cat_id}")))
            custom_price_notes.append(_to_str_or_none(request.form.get(f"custom_price_note_{cat_id}")))
        else:
            custom_total_prices.append(None)
            custom_price_notes.append(None)

    if not selections:
        flash("Select at least one category quantity.", "error")
        return redirect(url_for("routes.home", start_date=start, end_date=end))

    category_ids = [cid for cid, _ in selections]
    qtys = [qty for _, qty in selections]

    visible_categories = _query_available_categories(start, end)
    visible_by_id = {row["id"]: row for row in visible_categories}

    for idx, cat_id in enumerate(category_ids):
        cat_row = visible_by_id.get(cat_id)
        requested_qty = qtys[idx]
        allowed_items = (
            cat_row["admin_available_items"]
            if role == "admin"
            else cat_row["available_items"]
        ) if cat_row else 0

        if not cat_row:
            flash(f"Category {cat_id} is no longer available.", "error")
            return redirect(url_for("routes.home", start_date=start, end_date=end))

        if allowed_items <= 0:
            flash(f"{cat_row['display_name']} has no available items.", "error")
            return redirect(url_for("routes.home", start_date=start, end_date=end))
        if requested_qty > allowed_items:
            flash(
                f'{cat_row["display_name"]} only has {allowed_items} item{"s" if allowed_items != 1 else ""} available for these dates.',
                "error",
            )
            return redirect(url_for("routes.home", start_date=start, end_date=end))

        if role != "admin" and not cat_row["has_standard_price"]:
            flash(
                f"{cat_row['display_name']} has no standard price for the selected dates.",
                "error",
            )
            return redirect(url_for("routes.home", start_date=start, end_date=end))

        if role == "admin" and not cat_row["has_standard_price"] and booking_custom_total_price is None:
            if custom_total_prices[idx] is None:
                flash(
                    f"{cat_row['display_name']} needs a custom price because no standard price matches the selected dates, unless you set a booking total override.",
                    "error",
                )
                return redirect(url_for("routes.home", start_date=start, end_date=end))

    try:
        if role == "admin":
            def work(cur):
                effective_customer_id = customer_id

                if create_new_customer:
                    cur.execute(SQL_GET_CUSTOMER_BY_FULL_NAME, (new_full_name,))
                    existing_customer = cur.fetchone()

                    if existing_customer:
                        cur.execute(
                            SQL_UPDATE_CUSTOMER,
                            (
                                new_full_name,
                                new_email if new_email is not None else existing_customer["email"],
                                new_phone if new_phone is not None else existing_customer["phone"],
                                new_address if new_address is not None else existing_customer["address"],
                                new_postal_city if new_postal_city is not None else existing_customer["postal_city"],
                                existing_customer["id"],
                            ),
                        )
                        customer = cur.fetchone()
                    else:
                        cur.execute(
                            SQL_CREATE_CUSTOMER,
                            (new_full_name, new_email, new_phone, new_address, new_postal_city, None),
                        )
                        customer = cur.fetchone()

                    effective_customer_id = customer["id"]

                return _create_admin_booking_with_allocations(
                    cur,
                    customer_id=effective_customer_id,
                    start_date=start,
                    end_date=end,
                    selections=selections,
                    include_delivery=include_delivery,
                    delivery_fee=delivery_fee,
                    delivery_address=None,
                    delivery_distance_km=None,
                    include_setup_service=include_setup_service,
                    booking_custom_total_price=booking_custom_total_price,
                    booking_custom_price_note=booking_custom_price_note,
                    booking_note=booking_note,
                    custom_total_prices=custom_total_prices,
                    custom_price_notes=custom_price_notes,
                    category_context_by_id=visible_by_id,
                )

            booking_id, turnaround_item_labels = tx(work)
        else:
            row = query(
                SQL_CREATE_BOOKING_WITH_ALLOCATIONS,
                (
                    customer_id,
                    start,
                    end,
                    category_ids,
                    qtys,
                    include_delivery,
                    delivery_fee,
                    include_setup_service,
                    booking_custom_total_price,
                    booking_custom_price_note,
                    booking_note,
                    None,
                    None,
                    custom_total_prices,
                    custom_price_notes,
                ),
                one=True,
                commit=True,
            )
            booking_id = row["booking_id"]
            turnaround_item_labels = []

        flash(f"Booking created (id={booking_id}).", "success")
        if role != "admin":
            flash(
                f"Pending bookings hold stock for {_pending_booking_hold_label()} unless staff confirms them.",
                "success",
            )
        if turnaround_item_labels:
            flash(
                f"Warning: same-day turnaround items were allocated for this admin booking: {_format_turnaround_item_labels(turnaround_item_labels)}.",
                "warning",
            )
        return redirect(url_for("routes.booking_detail", booking_id=booking_id))
    except Exception as e:
        flash(f"Could not place booking: {str(e)}", "error")
        return redirect(url_for("routes.home", start_date=start, end_date=end))

# Customers
@bp.get("/customers")
def customers():
    uid, role = require_login()
    if not uid:
        return redirect(url_for("auth.login_form"))

    if role == "admin":
        customers_page = paginate_query(
            SQL_LIST_CUSTOMERS,
            pagination=_pagination_options(),
        )
        return render_template(
            "customers.html",
            customers=customers_page.items,
            customers_page=customers_page,
            role=role,
        )

    cust = query(SQL_GET_CUSTOMER_BY_USER_ID, (uid,), one=True)
    if not cust:
        flash("Det finns ingen kundprofil kopplad till det här kontot.", "error")
        return redirect(url_for("routes.home"))

    return redirect(url_for("routes.customer_detail", customer_id=cust["id"]))


@bp.get("/customers/new")
def customer_new_form():
    require_admin()
    return render_template("customer_new.html", role="admin")


@bp.post("/customers/new")
def customer_new():
    require_admin()

    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower() or None
    phone = request.form.get("phone", "").strip() or None
    address = request.form.get("address", "").strip() or None
    postal_city = _sanitize_postal_city(request.form.get("postal_city"))

    if not full_name:
        flash("Full name is required.", "error")
        return redirect(url_for("routes.customer_new_form"))

    try:
        row = query(SQL_CREATE_CUSTOMER, (full_name, email, phone, address, postal_city, None), one=True, commit=True)
        flash(f"Customer created (id={row['id']}).", "success")
    except Exception as e:
        flash(f"Could not create customer: {str(e)}", "error")

    return redirect(url_for("routes.customers"))


@bp.get("/customers/<int:customer_id>")
def customer_detail(customer_id: int):
    uid, role = require_login()
    if not uid:
        return redirect(url_for("auth.login_form"))

    cust = query(SQL_GET_CUSTOMER, (customer_id,), one=True)
    if not cust:
        abort(404)

    if role != "admin":
        self_cust = query(SQL_GET_CUSTOMER_BY_USER_ID, (uid,), one=True)
        if not self_cust or self_cust["id"] != customer_id:
            abort(403)

    bookings_page = paginate_query(
        SQL_LIST_BOOKINGS_FOR_CUSTOMER,
        (customer_id,),
        pagination=_pagination_options(default_per_page=10),
    )
    return render_template(
        "customer_detail.html",
        customer=cust,
        bookings=bookings_page.items,
        bookings_page=bookings_page,
        role=role,
    )


# Admin: Bookings list
@bp.get("/admin/bookings")
def admin_bookings():
    require_admin()
    bookings_page = paginate_query(
        SQL_LIST_ALL_BOOKINGS,
        pagination=_pagination_options(default_per_page=20),
    )
    return render_template(
        "admin_bookings.html",
        bookings=bookings_page.items,
        bookings_page=bookings_page,
        role="admin",
    )


# Admin: Rental periods
@bp.get("/admin/rental-periods")
def admin_rental_periods():
    require_admin()
    rental_periods_page = paginate_query(
        SQL_LIST_RENTAL_PERIODS,
        pagination=_pagination_options(),
    )
    return render_template(
        "admin_rental_periods.html",
        rental_periods=rental_periods_page.items,
        rental_periods_page=rental_periods_page,
        role="admin",
    )


@bp.get("/admin/rental-periods/new")
def admin_rental_period_new_form():
    require_admin()
    return render_template("admin_rental_period_new.html", role="admin")


@bp.post("/admin/rental-periods/new")
def admin_rental_period_new():
    require_admin()

    label = request.form.get("label", "").strip()
    min_days = request.form.get("min_days", "").strip()
    max_days = request.form.get("max_days", "").strip()

    if not label or not min_days or not max_days:
        flash("Label, minimum days and maximum days are required.", "error")
        return redirect(url_for("routes.admin_rental_period_new_form"))

    try:
        row = query(
            SQL_CREATE_RENTAL_PERIOD,
            (label, min_days, max_days),
            one=True,
            commit=True,
        )
        flash(f"Rental period created (id={row['id']}).", "success")
        return redirect(url_for("routes.admin_rental_periods"))
    except Exception as e:
        flash(f"Failed: {str(e)}", "error")
        return redirect(url_for("routes.admin_rental_period_new_form"))


@bp.get("/admin/rental-periods/<int:rental_period_id>/edit")
def admin_rental_period_edit_form(rental_period_id: int):
    require_admin()

    rental_period = query(SQL_GET_RENTAL_PERIOD, (rental_period_id,), one=True)
    if not rental_period:
        flash("Rental period not found.", "error")
        return redirect(url_for("routes.admin_rental_periods"))

    usage = query(SQL_RENTAL_PERIOD_USAGE_COUNT, (rental_period_id,), one=True)
    usage_count = usage["usage_count"] if usage else 0

    return render_template(
        "admin_rental_period_edit.html",
        rental_period=rental_period,
        pricing_usage_count=usage_count,
        allow_delete=(usage_count == 0),
        role="admin",
    )


@bp.post("/admin/rental-periods/<int:rental_period_id>/edit")
def admin_rental_period_edit_save(rental_period_id: int):
    require_admin()

    label = request.form.get("label", "").strip()
    min_days = request.form.get("min_days", "").strip()
    max_days = request.form.get("max_days", "").strip()

    if not label or not min_days or not max_days:
        flash("Label, minimum days and maximum days are required.", "error")
        return redirect(url_for("routes.admin_rental_period_edit_form", rental_period_id=rental_period_id))

    try:
        execute(SQL_UPDATE_RENTAL_PERIOD, (label, min_days, max_days, rental_period_id))
        flash("Rental period updated.", "success")
        return redirect(url_for("routes.admin_rental_periods"))
    except Exception as e:
        flash(f"Update failed: {str(e)}", "error")
        return redirect(url_for("routes.admin_rental_period_edit_form", rental_period_id=rental_period_id))


@bp.post("/admin/rental-periods/<int:rental_period_id>/delete")
def admin_rental_period_delete(rental_period_id: int):
    require_admin()

    usage = query(SQL_RENTAL_PERIOD_USAGE_COUNT, (rental_period_id,), one=True)
    usage_count = usage["usage_count"] if usage else 0

    if usage_count > 0:
        flash("Cannot delete rental period because it is used by category pricing.", "error")
        return redirect(url_for("routes.admin_rental_period_edit_form", rental_period_id=rental_period_id))

    try:
        execute(SQL_DELETE_RENTAL_PERIOD, (rental_period_id,))
        flash("Rental period deleted.", "success")
    except Exception as e:
        flash(f"Delete failed: {str(e)}", "error")

    return redirect(url_for("routes.admin_rental_periods"))


# Admin: Items
@bp.get("/admin/items")
def admin_items():
    require_admin()
    items_page = paginate_query(
        SQL_LIST_ITEMS,
        pagination=_pagination_options(),
    )
    return render_template(
        "admin_items.html",
        items=items_page.items,
        items_page=items_page,
        role="admin",
    )


@bp.get("/admin/items/new")
def admin_item_new_form():
    require_admin()
    categories = query(SQL_LIST_CATEGORIES_FOR_DROPDOWN)
    return render_template("admin_item_new.html", categories=categories, role="admin")


@bp.post("/admin/items/new")
def admin_item_new():
    require_admin()

    category_id = request.form.get("category_id", "").strip()
    sku = request.form.get("sku", "").strip()
    is_active = _to_bool(request.form.get("is_active"))

    if not category_id or not sku:
        flash("Category and SKU are required.", "error")
        return redirect(url_for("routes.admin_item_new_form"))

    try:
        cat_id_int = int(category_id)
        row = query(SQL_CREATE_ITEM, (cat_id_int, sku, is_active), one=True, commit=True)
        flash(f"Item created (item_id={row['new_item_id']}).", "success")
        return redirect(url_for("routes.admin_items"))
    except Exception as e:
        flash(f"Failed: {str(e)}", "error")
        return redirect(url_for("routes.admin_item_new_form"))


@bp.get("/admin/items/<int:item_id>/edit")
def admin_item_edit_form(item_id: int):
    require_admin()

    item = query(SQL_GET_ITEM_FOR_EDIT, (item_id,), one=True)
    if not item:
        flash("Item not found.", "error")
        return redirect(url_for("routes.admin_items"))

    categories = query(SQL_LIST_CATEGORIES_FOR_DROPDOWN)
    return render_template("admin_item_edit.html", item=item, categories=categories, role="admin")


@bp.post("/admin/items/<int:item_id>/edit")
def admin_item_edit_save(item_id: int):
    require_admin()

    category_id = request.form.get("category_id", "").strip()
    sku = request.form.get("sku", "").strip()
    is_active = _to_bool(request.form.get("is_active"))

    if not category_id or not sku:
        flash("Category and SKU are required.", "error")
        return redirect(url_for("routes.admin_item_edit_form", item_id=item_id))

    try:
        cat_id_int = int(category_id)
        query(SQL_UPDATE_ITEM, (cat_id_int, sku, is_active, item_id), commit=True)
        flash("Item updated.", "success")
        return redirect(url_for("routes.admin_items"))
    except Exception as e:
        flash(f"Update failed: {str(e)}", "error")
        return redirect(url_for("routes.admin_item_edit_form", item_id=item_id))


@bp.post("/admin/items/<int:item_id>/delete")
def admin_item_delete(item_id: int):
    require_admin()

    blocked = query(SQL_ITEM_HAS_ACTIVE_OR_FUTURE_BOOKING, (item_id,), one=True)
    if blocked:
        flash("Cannot delete item: it is booked now or in the future.", "error")
        return redirect(url_for("routes.admin_items"))

    def work(cur):
        cur.execute(SQL_DELETE_BOOKING_ITEMS_FOR_ITEM, (item_id,))
        cur.execute(SQL_DELETE_ITEM, (item_id,))
        return True

    try:
        tx(work)
        flash("Item deleted.", "success")
    except Exception as e:
        flash(f"Delete failed: {str(e)}", "error")

    return redirect(url_for("routes.admin_items"))


# Admin: Categories
@bp.get("/admin/categories")
def admin_categories():
    require_admin()
    categories_page = paginate_query(
        SQL_LIST_CATEGORIES,
        pagination=_pagination_options(),
    )
    return render_template(
        "admin_categories.html",
        categories=categories_page.items,
        categories_page=categories_page,
        role="admin",
    )


@bp.get("/admin/categories/tent/new")
def admin_category_tent_new_form():
    require_admin()
    rental_periods = query(SQL_LIST_RENTAL_PERIODS)
    return render_template(
        "admin_category_tent_new.html",
        role="admin",
        rental_periods=rental_periods,
    )


@bp.post("/admin/categories/tent/new")
def admin_category_tent_new():
    require_admin()

    name = request.form.get("display_name", "").strip()
    capacity = request.form.get("capacity", "").strip()
    season_rating = request.form.get("season_rating", "").strip()
    build_time = request.form.get("estimated_build_time_minutes", "").strip() or "10"
    setup_service_fee = request.form.get("setup_service_fee", "").strip() or "0"
    packed_weight = _to_str_or_none(request.form.get("packed_weight_kg"))
    floor_area = _to_str_or_none(request.form.get("floor_area_m2"))
    period_rows = _collect_category_period_prices_from_form()

    if not name or not capacity or not season_rating:
        flash("Missing required fields.", "error")
        return redirect(url_for("routes.admin_category_tent_new_form"))

    if not period_rows:
        flash("At least one rental period price is required.", "error")
        return redirect(url_for("routes.admin_category_tent_new_form"))

    def work(cur):
        cur.execute(SQL_CREATE_CATEGORY, (name,))
        cat_id = cur.fetchone()["id"]

        cur.execute(
            SQL_CREATE_TENT_CATEGORY_ROW,
            (
                cat_id,
                capacity,
                season_rating,
                packed_weight,
                floor_area,
                build_time,
                setup_service_fee,
            ),
        )

        for row in period_rows:
            cur.execute(
                SQL_UPSERT_CATEGORY_RENTAL_PERIOD_PRICE,
                (
                    cat_id,
                    row["rental_period_id"],
                    row["price"],
                    row["sort_order"],
                ),
            )

        return cat_id

    try:
        cat_id = tx(work)
        flash(f"Tent category created (id={cat_id}).", "success")
        return redirect(url_for("routes.admin_categories"))
    except Exception as e:
        flash(f"Failed: {str(e)}", "error")
        return redirect(url_for("routes.admin_category_tent_new_form"))


@bp.get("/admin/categories/furnishing/new")
def admin_category_furn_new_form():
    require_admin()
    rental_periods = query(SQL_LIST_RENTAL_PERIODS)
    return render_template(
        "admin_category_furn_new.html",
        role="admin",
        rental_periods=rental_periods,
    )


@bp.post("/admin/categories/furnishing/new")
def admin_category_furn_new():
    require_admin()

    name = request.form.get("display_name", "").strip()
    kind = request.form.get("furnishing_kind", "").strip()
    weight_kg = _to_str_or_none(request.form.get("weight_kg"))
    notes = _to_str_or_none(request.form.get("notes"))
    period_rows = _collect_category_period_prices_from_form()

    if not name or not kind:
        flash("Missing required fields.", "error")
        return redirect(url_for("routes.admin_category_furn_new_form"))

    if not period_rows:
        flash("At least one rental period price is required.", "error")
        return redirect(url_for("routes.admin_category_furn_new_form"))

    def work(cur):
        cur.execute(SQL_CREATE_CATEGORY, (name,))
        cat_id = cur.fetchone()["id"]

        cur.execute(SQL_CREATE_FURN_CATEGORY_ROW, (cat_id, kind, weight_kg, notes))

        for row in period_rows:
            cur.execute(
                SQL_UPSERT_CATEGORY_RENTAL_PERIOD_PRICE,
                (
                    cat_id,
                    row["rental_period_id"],
                    row["price"],
                    row["sort_order"],
                ),
            )

        return cat_id

    try:
        cat_id = tx(work)
        flash(f"Furnishing category created (id={cat_id}).", "success")
        return redirect(url_for("routes.admin_categories"))
    except Exception as e:
        flash(f"Failed: {str(e)}", "error")
        return redirect(url_for("routes.admin_category_furn_new_form"))


@bp.get("/admin/categories/<int:category_id>/edit")
def admin_category_edit_form(category_id: int):
    require_admin()

    cat = query(SQL_GET_CATEGORY_FOR_EDIT, (category_id,), one=True)
    if not cat:
        flash("Category not found.", "error")
        return redirect(url_for("routes.admin_categories"))

    pricing_rows = query(SQL_LIST_CATEGORY_RENTAL_PERIOD_PRICES, (category_id,))
    pricing_map = {row["rental_period_id"]: row for row in pricing_rows}
    rental_periods = query(SQL_LIST_RENTAL_PERIODS)

    return render_template(
        "admin_category_edit.html",
        cat=cat,
        pricing_rows=pricing_rows,
        pricing_map=pricing_map,
        rental_periods=rental_periods,
        role="admin",
    )


@bp.post("/admin/categories/<int:category_id>/edit")
def admin_category_edit_save(category_id: int):
    require_admin()

    cat = query(SQL_GET_CATEGORY_FOR_EDIT, (category_id,), one=True)
    if not cat:
        flash("Category not found.", "error")
        return redirect(url_for("routes.admin_categories"))

    display_name = request.form.get("display_name", "").strip()
    if not display_name:
        flash("Name is required.", "error")
        return redirect(url_for("routes.admin_category_edit_form", category_id=category_id))

    period_rows = _collect_category_period_prices_from_form()
    if not period_rows:
        flash("At least one rental period price is required.", "error")
        return redirect(url_for("routes.admin_category_edit_form", category_id=category_id))

    def work(cur):
        cur.execute(SQL_UPDATE_CATEGORY_BASE, (display_name, category_id))

        if cat["is_tent"]:
            capacity = _to_int_or_none(request.form.get("capacity"))
            season_rating = _to_int_or_none(request.form.get("season_rating"))
            packed_weight_kg = _to_str_or_none(request.form.get("packed_weight_kg"))
            floor_area_m2 = _to_str_or_none(request.form.get("floor_area_m2"))
            build_time = _to_int_or_none(request.form.get("estimated_build_time_minutes"))
            setup_service_fee = _to_str_or_none(request.form.get("setup_service_fee")) or "0"

            cur.execute(
                SQL_UPDATE_TENT_CATEGORY,
                (
                    capacity,
                    season_rating,
                    packed_weight_kg,
                    floor_area_m2,
                    build_time,
                    setup_service_fee,
                    category_id,
                ),
            )
        else:
            kind = request.form.get("furnishing_kind", "").strip()
            weight_kg = _to_str_or_none(request.form.get("weight_kg"))
            notes = _to_str_or_none(request.form.get("notes"))

            cur.execute(
                SQL_UPDATE_FURN_CATEGORY,
                (
                    kind,
                    weight_kg,
                    notes,
                    category_id,
                ),
            )

        cur.execute(
            "DELETE FROM category_rental_period_prices WHERE category_id = %s;",
            (category_id,),
        )

        for row in period_rows:
            cur.execute(
                SQL_UPSERT_CATEGORY_RENTAL_PERIOD_PRICE,
                (
                    category_id,
                    row["rental_period_id"],
                    row["price"],
                    row["sort_order"],
                ),
            )

        return True

    try:
        tx(work)
        flash("Category updated.", "success")
        return redirect(url_for("routes.admin_categories"))
    except Exception as e:
        flash(f"Update failed: {str(e)}", "error")
        return redirect(url_for("routes.admin_category_edit_form", category_id=category_id))


# Booking detail / status
@bp.get("/bookings/<int:booking_id>")
def booking_detail(booking_id: int):
    uid, role = require_login()
    if not uid:
        return redirect(url_for("auth.login_form"))

    if role == "admin":
        booking = query(SQL_BOOKING_DETAIL, (booking_id,), one=True)
    else:
        cust = query(SQL_GET_CUSTOMER_BY_USER_ID, (uid,), one=True)
        if not cust:
            abort(403)
        booking = query(SQL_BOOKING_DETAIL_FOR_CUSTOMER, (booking_id, cust["id"]), one=True)

    if not booking:
        flash("Bokningen hittades inte.", "error")
        return redirect(url_for("routes.home"))

    items = query(SQL_BOOKING_ITEMS, (booking_id,))
    item_summary = _build_booking_item_summary(items)
    total = query(SQL_BOOKING_TOTAL, (booking_id,), one=True)

    return render_template(
        "booking_detail.html",
        booking=booking,
        items=items,
        item_summary=item_summary,
        total=total,
        role=role,
    )


@bp.get("/admin/bookings/<int:booking_id>/edit")
def admin_booking_edit_form(booking_id: int):
    require_admin()

    booking = query(SQL_BOOKING_DETAIL, (booking_id,), one=True)
    if not booking:
        flash("Booking not found.", "error")
        return redirect(url_for("routes.admin_bookings"))

    customers = query(SQL_LIST_CUSTOMERS)
    items = query(SQL_BOOKING_ITEMS, (booking_id,))
    total = query(SQL_BOOKING_TOTAL, (booking_id,), one=True)

    return render_template(
        "admin_booking_edit.html",
        booking=booking,
        customers=customers,
        items=items,
        total=total,
        role="admin",
    )


@bp.post("/admin/bookings/<int:booking_id>/edit")
def admin_booking_edit_save(booking_id: int):
    require_admin()

    booking = query(SQL_BOOKING_DETAIL, (booking_id,), one=True)
    if not booking:
        flash("Booking not found.", "error")
        return redirect(url_for("routes.admin_bookings"))

    customer_id = request.form.get("customer_id", "").strip()
    start_date = request.form.get("start_date", "").strip()
    end_date = request.form.get("end_date", "").strip()
    status = request.form.get("status", "").strip()
    include_delivery = _to_bool(request.form.get("include_delivery"))
    include_setup_service = _to_bool(request.form.get("include_setup_service"))
    delivery_fee = _to_str_or_none(request.form.get("delivery_fee")) if include_delivery else None
    custom_total_price = _to_str_or_none(request.form.get("custom_total_price"))
    custom_price_note = _to_str_or_none(request.form.get("custom_price_note"))
    booking_note = _to_str_or_none(request.form.get("booking_note"))
    admin_note = _to_str_or_none(request.form.get("admin_note"))

    if not customer_id or not start_date or not end_date or not status:
        flash("Customer, dates, and status are required.", "error")
        return redirect(url_for("routes.admin_booking_edit_form", booking_id=booking_id))

    if status not in ("pending", "confirmed", "cancelled"):
        flash("Invalid booking status.", "error")
        return redirect(url_for("routes.admin_booking_edit_form", booking_id=booking_id))

    if end_date < start_date:
        flash("End date cannot be earlier than start date.", "error")
        return redirect(url_for("routes.admin_booking_edit_form", booking_id=booking_id))

    try:
        def work(cur):
            cur.execute(
                SQL_UPDATE_BOOKING_ADMIN_FIELDS,
                (
                    customer_id,
                    start_date,
                    end_date,
                    status,
                    include_delivery,
                    delivery_fee,
                    include_setup_service,
                    custom_total_price,
                    custom_price_note,
                    booking_note,
                    admin_note,
                    booking_id,
                ),
            )

            if status == "cancelled":
                return 0, 0, []

            return _reallocate_booking_items_for_dates(
                cur,
                booking_id,
                start_date,
                end_date,
                include_setup_service=include_setup_service,
                booking_has_total_override=custom_total_price is not None,
            )

        reallocated_count, metadata_warning_count, turnaround_item_labels = tx(work)

        if reallocated_count or metadata_warning_count or turnaround_item_labels:
            print(
                "[booking-reallocation]",
                {
                    "booking_id": booking_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "reallocated_count": reallocated_count,
                    "metadata_warning_count": metadata_warning_count,
                    "turnaround_item_labels": turnaround_item_labels,
                },
            )

        if reallocated_count:
            flash(
                f"Booking updated. {reallocated_count} item{'s' if reallocated_count != 1 else ''} {'were' if reallocated_count != 1 else 'was'} reallocated to match the new dates.",
                "success",
            )
        else:
            flash("Booking updated.", "success")
        if metadata_warning_count:
            flash(
                f'Review {metadata_warning_count} reallocated item{"s" if metadata_warning_count != 1 else ""}: existing line notes or custom pricing were kept on the reassigned booking line.',
                "warning",
            )
        if turnaround_item_labels:
            flash(
                f"Same-day turnaround items are now allocated on this booking: {_format_turnaround_item_labels(turnaround_item_labels)}.",
                "warning",
            )
        return redirect(url_for("routes.booking_detail", booking_id=booking_id))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("routes.admin_booking_edit_form", booking_id=booking_id))
    except Exception as e:
        flash(f"Update failed: {str(e)}", "error")
        return redirect(url_for("routes.admin_booking_edit_form", booking_id=booking_id))


@bp.post("/bookings/<int:booking_id>/confirm")
def booking_confirm(booking_id: int):
    require_admin()
    updated = execute(SQL_CONFIRM_BOOKING, (booking_id,))
    if updated:
        flash("Booking confirmed.", "success")
    else:
        flash("Only pending bookings can be confirmed.", "error")
    return redirect(url_for("routes.booking_detail", booking_id=booking_id))


@bp.post("/bookings/<int:booking_id>/cancel")
def booking_cancel(booking_id: int):
    require_admin()
    updated = execute(SQL_CANCEL_BOOKING, (booking_id,))
    if updated:
        flash("Booking cancelled.", "success")
    else:
        flash("Booking is already cancelled.", "error")
    return redirect(url_for("routes.booking_detail", booking_id=booking_id))


@bp.post("/bookings/<int:booking_id>/delete")
def booking_delete(booking_id: int):
    require_admin()

    deleted = execute(SQL_DELETE_BOOKING, (booking_id,))
    if deleted:
        flash("Cancelled booking deleted.", "success")
        return redirect(url_for("routes.admin_bookings"))

    flash("Only cancelled bookings can be deleted.", "error")
    return redirect(url_for("routes.booking_detail", booking_id=booking_id))

@bp.get("/customers/<int:customer_id>/edit")
def customer_edit_form(customer_id: int):
    require_admin()

    customer = query(SQL_GET_CUSTOMER_FOR_EDIT, (customer_id,), one=True)
    if not customer:
        flash("Customer not found.", "error")
        return redirect(url_for("routes.customers"))

    return render_template("customer_edit.html", customer=customer, role="admin")


@bp.post("/customers/<int:customer_id>/edit")
def customer_edit_save(customer_id: int):
    require_admin()

    customer = query(SQL_GET_CUSTOMER_FOR_EDIT, (customer_id,), one=True)
    if not customer:
        flash("Customer not found.", "error")
        return redirect(url_for("routes.customers"))

    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower() or None
    phone = request.form.get("phone", "").strip() or None
    address = request.form.get("address", "").strip() or None
    postal_city = _sanitize_postal_city(request.form.get("postal_city"))

    if not full_name:
        flash("Full name is required.", "error")
        return redirect(url_for("routes.customer_edit_form", customer_id=customer_id))

    try:
        query(
            SQL_UPDATE_CUSTOMER,
            (full_name, email, phone, address, postal_city, customer_id),
            one=True,
            commit=True,
        )
        flash("Customer updated.", "success")
        return redirect(url_for("routes.customer_detail", customer_id=customer_id))
    except Exception as e:
        flash(f"Update failed: {str(e)}", "error")
        return redirect(url_for("routes.customer_edit_form", customer_id=customer_id))
    
@bp.get("/admin/bookings/calendar")
def admin_bookings_calendar():
    require_admin()
    bookings = [b for b in query(SQL_LIST_ALL_BOOKINGS) if b["status"] != "cancelled"]
    booking_ids = [b["id"] for b in bookings]
    items_by_booking_id = {}
    category_inventory = {}

    if booking_ids:
        calendar_items = query(SQL_BOOKING_ITEMS_FOR_BOOKINGS, (booking_ids,))
        for row in calendar_items:
            items_by_booking_id.setdefault(row["booking_id"], []).append(row)

    for item in query(SQL_LIST_ITEMS):
        if not item["is_active"]:
            continue

        category_id = item["category_id"]
        if item["is_tent"]:
            type_label = "Tent"
        elif item["is_furnishing"]:
            type_label = "Furnishing"
        else:
            type_label = "Item"

        if category_id not in category_inventory:
            category_inventory[category_id] = {
                "category_id": category_id,
                "display_name": item["display_name"],
                "type_label": type_label,
                "total_active": 0,
            }

        category_inventory[category_id]["total_active"] += 1

    for b in bookings:
        b["end_date_plus_one"] = b["end_date"] + timedelta(days=1)
        b["calendar_item_summary"] = [
            dict(row)
            for row in _build_booking_item_summary(items_by_booking_id.get(b["id"], []))
        ]

    return render_template(
        "booking_calendar.html",
        bookings=bookings,
        category_inventory=list(category_inventory.values()),
        role="admin",
    )
