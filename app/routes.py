from flask import Blueprint, request, render_template, redirect, url_for, flash, session, abort

from datetime import timedelta
from werkzeug.security import generate_password_hash

from .db import query, execute, tx
from .sql import (
    SQL_CREATE_USER,
    SQL_LINK_CUSTOMER_TO_USER,
    # customers
    SQL_LIST_CUSTOMERS,
    SQL_GET_CUSTOMER,
    SQL_GET_CUSTOMER_BY_USER_ID,
    SQL_CREATE_CUSTOMER,
    SQL_LIST_BOOKINGS_FOR_CUSTOMER,
    SQL_GET_CUSTOMER_FOR_EDIT,
    SQL_UPDATE_CUSTOMER,

    # rental periods
    SQL_LIST_RENTAL_PERIODS,
    SQL_GET_RENTAL_PERIOD,
    SQL_CREATE_RENTAL_PERIOD,
    SQL_UPDATE_RENTAL_PERIOD,
    SQL_DELETE_RENTAL_PERIOD,
    SQL_RENTAL_PERIOD_USAGE_COUNT,

    # booking
    SQL_AVAILABLE_CATEGORIES,
    SQL_CREATE_BOOKING_WITH_ALLOCATIONS,

    # units
    SQL_LIST_UNITS,
    SQL_LIST_CATEGORIES_FOR_DROPDOWN,
    SQL_GET_UNIT_FOR_EDIT,
    SQL_UPDATE_UNIT,
    SQL_ADD_ITEM_UNIT,
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
    SQL_BOOKING_TOTAL,
    SQL_LIST_ALL_BOOKINGS,
    SQL_CONFIRM_BOOKING,
    SQL_CANCEL_BOOKING,
)

bp = Blueprint("routes", __name__)


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
        return None, None
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


# Home (category availability)
@bp.get("/")
def home():
    uid, role = current_user()
    start = request.args.get("start_date", "")
    end = request.args.get("end_date", "")

    categories = None
    customers = None

    if start and end:
        # SQL_AVAILABLE_CATEGORIES expects:
        # 1) end_date
        # 2) start_date
        # 3) end_date
        # 4) start_date
        categories = query(SQL_AVAILABLE_CATEGORIES, (end, start, start, end))

        if role == "admin":
            customers = query(SQL_LIST_CUSTOMERS)
        elif role == "customer" and uid:
            cust = query(SQL_GET_CUSTOMER_BY_USER_ID, (uid,), one=True)
            customers = [cust] if cust else None
        else:
            customers = None

    return render_template(
        "home.html",
        start_date=start,
        end_date=end,
        categories=categories,
        customers=customers,
        role=role,
    )


# Booking create
@bp.post("/bookings/create")
def booking_create_from_home():
    uid, role = require_login()
    if not uid:
        flash("Please log in to place a booking.", "error")
        return redirect(url_for("auth.login_form"))

    start = request.form.get("start_date", "").strip()
    end = request.form.get("end_date", "").strip()
    if not start or not end:
        flash("Choose dates first.", "error")
        return redirect(url_for("routes.home"))

    if role == "admin":
        create_new_user = _to_bool(request.form.get("create_new_user"))
        customer_id = request.form.get("customer_id", "").strip()
        new_full_name = request.form.get("new_customer_full_name", "").strip()
        new_email = _normalize_email(request.form.get("new_customer_email"))
        new_phone = _to_str_or_none(request.form.get("new_customer_phone"))
        new_address = _to_str_or_none(request.form.get("new_customer_address"))
        new_password = request.form.get("new_customer_password", "")

        if create_new_user:
            if not new_full_name or not new_email or not new_password:
                flash("Name, email and password are required to create a new user during booking.", "error")
                return redirect(url_for("routes.home", start_date=start, end_date=end))
        elif not customer_id:
            flash("Select a customer or create a new user.", "error")
            return redirect(url_for("routes.home", start_date=start, end_date=end))
    else:
        cust = query(SQL_GET_CUSTOMER_BY_USER_ID, (uid,), one=True)
        if not cust:
            flash("No customer profile linked to this account.", "error")
            return redirect(url_for("routes.home", start_date=start, end_date=end))
        customer_id = str(cust["id"])
        create_new_user = False

    include_delivery = _to_bool(request.form.get("include_delivery"))
    include_setup_service = _to_bool(request.form.get("include_setup_service"))
    delivery_fee = _to_str_or_none(request.form.get("delivery_fee")) if include_delivery else None
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

    selections = []
    custom_total_prices = []
    custom_price_notes = []

    for key, value in request.form.items():
        if not key.startswith("qty_"):
            continue

        try:
            cat_id = int(key.split("_", 1)[1])
            qty = int(value) if value.strip() else 0
        except Exception:
            continue

        if qty <= 0:
            continue

        selections.append((cat_id, qty))

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

    visible_categories = query(SQL_AVAILABLE_CATEGORIES, (end, start, start, end))
    visible_by_id = {row["id"]: row for row in visible_categories}

    for idx, cat_id in enumerate(category_ids):
        cat_row = visible_by_id.get(cat_id)

        if not cat_row:
            flash(f"Category {cat_id} is no longer available.", "error")
            return redirect(url_for("routes.home", start_date=start, end_date=end))

        if cat_row["available_units"] <= 0:
            flash(f"{cat_row['display_name']} has no available units.", "error")
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

                if create_new_user:
                    password_hash = generate_password_hash(new_password)
                    cur.execute(SQL_CREATE_USER, (new_email, password_hash, "customer"))
                    user = cur.fetchone()

                    cur.execute(SQL_LINK_CUSTOMER_TO_USER, (user["id"], new_email))
                    customer = cur.fetchone()

                    if not customer:
                        cur.execute(
                            SQL_CREATE_CUSTOMER,
                            (new_full_name, new_email, new_phone, new_address, user["id"]),
                        )
                        customer = cur.fetchone()

                    effective_customer_id = customer["id"]

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
                        booking_custom_total_price,
                        booking_custom_price_note,
                        custom_total_prices,
                        custom_price_notes,
                    ),
                )
                return cur.fetchone()

            row = tx(work)
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
                    custom_total_prices,
                    custom_price_notes,
                ),
                one=True,
                commit=True,
            )

        booking_id = row["booking_id"]
        flash(f"Booking created (id={booking_id}).", "success")
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
        return render_template("customers.html", customers=query(SQL_LIST_CUSTOMERS), role=role)

    cust = query(SQL_GET_CUSTOMER_BY_USER_ID, (uid,), one=True)
    if not cust:
        flash("No customer profile linked to this account.", "error")
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

    if not full_name:
        flash("Full name is required.", "error")
        return redirect(url_for("routes.customer_new_form"))

    try:
        row = query(SQL_CREATE_CUSTOMER, (full_name, email, phone, address, None), one=True, commit=True)
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

    bookings = query(SQL_LIST_BOOKINGS_FOR_CUSTOMER, (customer_id,))
    return render_template("customer_detail.html", customer=cust, bookings=bookings, role=role)


# Admin: Bookings list
@bp.get("/admin/bookings")
def admin_bookings():
    require_admin()
    bookings = query(SQL_LIST_ALL_BOOKINGS)
    return render_template("admin_bookings.html", bookings=bookings, role="admin")


# Admin: Rental periods
@bp.get("/admin/rental-periods")
def admin_rental_periods():
    require_admin()
    rental_periods = query(SQL_LIST_RENTAL_PERIODS)
    return render_template(
        "admin_rental_periods.html",
        rental_periods=rental_periods,
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


# Admin: Units
@bp.get("/admin/items")
def admin_items():
    require_admin()
    return render_template("admin_items.html", items=query(SQL_LIST_UNITS), role="admin")


@bp.get("/admin/items/unit/new")
def admin_unit_new_form():
    require_admin()
    categories = query(SQL_LIST_CATEGORIES_FOR_DROPDOWN)
    return render_template("admin_unit_new.html", categories=categories, role="admin")


@bp.post("/admin/items/unit/new")
def admin_unit_new():
    require_admin()

    category_id = request.form.get("category_id", "").strip()
    sku = request.form.get("sku", "").strip()
    is_active = _to_bool(request.form.get("is_active"))

    if not category_id or not sku:
        flash("Category and SKU are required.", "error")
        return redirect(url_for("routes.admin_unit_new_form"))

    try:
        cat_id_int = int(category_id)
        row = query(SQL_ADD_ITEM_UNIT, (cat_id_int, sku, is_active), one=True, commit=True)
        flash(f"Unit created (item_id={row['new_item_id']}).", "success")
        return redirect(url_for("routes.admin_items"))
    except Exception as e:
        flash(f"Failed: {str(e)}", "error")
        return redirect(url_for("routes.admin_unit_new_form"))


@bp.get("/admin/items/<int:item_id>/edit")
def admin_unit_edit_form(item_id: int):
    require_admin()

    unit = query(SQL_GET_UNIT_FOR_EDIT, (item_id,), one=True)
    if not unit:
        flash("Unit not found.", "error")
        return redirect(url_for("routes.admin_items"))

    categories = query(SQL_LIST_CATEGORIES_FOR_DROPDOWN)
    return render_template("admin_unit_edit.html", unit=unit, categories=categories, role="admin")


@bp.post("/admin/items/<int:item_id>/edit")
def admin_unit_edit_save(item_id: int):
    require_admin()

    category_id = request.form.get("category_id", "").strip()
    sku = request.form.get("sku", "").strip()
    is_active = _to_bool(request.form.get("is_active"))

    if not category_id or not sku:
        flash("Category and SKU are required.", "error")
        return redirect(url_for("routes.admin_unit_edit_form", item_id=item_id))

    try:
        cat_id_int = int(category_id)
        query(SQL_UPDATE_UNIT, (cat_id_int, sku, is_active, item_id), commit=True)
        flash("Unit updated.", "success")
        return redirect(url_for("routes.admin_items"))
    except Exception as e:
        flash(f"Update failed: {str(e)}", "error")
        return redirect(url_for("routes.admin_unit_edit_form", item_id=item_id))


@bp.post("/admin/items/<int:item_id>/delete")
def admin_item_delete(item_id: int):
    require_admin()

    blocked = query(SQL_ITEM_HAS_ACTIVE_OR_FUTURE_BOOKING, (item_id,), one=True)
    if blocked:
        flash("Cannot delete unit: it is booked now or in the future.", "error")
        return redirect(url_for("routes.admin_items"))

    def work(cur):
        cur.execute(SQL_DELETE_BOOKING_ITEMS_FOR_ITEM, (item_id,))
        cur.execute(SQL_DELETE_ITEM, (item_id,))
        return True

    try:
        tx(work)
        flash("Unit deleted.", "success")
    except Exception as e:
        flash(f"Delete failed: {str(e)}", "error")

    return redirect(url_for("routes.admin_items"))


# Admin: Categories
@bp.get("/admin/categories")
def admin_categories():
    require_admin()
    categories = query(SQL_LIST_CATEGORIES)
    return render_template("admin_categories.html", categories=categories, role="admin")


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
        flash("Booking not found.", "error")
        return redirect(url_for("routes.home"))

    items = query(SQL_BOOKING_ITEMS, (booking_id,))
    total = query(SQL_BOOKING_TOTAL, (booking_id,), one=True)

    return render_template(
        "booking_detail.html",
        booking=booking,
        items=items,
        total=total,
        role=role,
    )


@bp.post("/bookings/<int:booking_id>/confirm")
def booking_confirm(booking_id: int):
    require_admin()
    execute(SQL_CONFIRM_BOOKING, (booking_id,))
    flash("Booking confirmed.", "success")
    return redirect(url_for("routes.booking_detail", booking_id=booking_id))


@bp.post("/bookings/<int:booking_id>/cancel")
def booking_cancel(booking_id: int):
    require_admin()
    execute(SQL_CANCEL_BOOKING, (booking_id,))
    flash("Booking cancelled.", "success")
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

    if not full_name:
        flash("Full name is required.", "error")
        return redirect(url_for("routes.customer_edit_form", customer_id=customer_id))

    try:
        query(
            SQL_UPDATE_CUSTOMER,
            (full_name, email, phone, address, customer_id),
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
    bookings = query(SQL_LIST_ALL_BOOKINGS)

    for b in bookings:
        b["end_date_plus_one"] = b["end_date"] + timedelta(days=1)

    return render_template(
        "booking_calendar.html",
        bookings=bookings,
        role="admin",
    )
