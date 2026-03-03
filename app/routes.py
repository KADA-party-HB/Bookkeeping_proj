from flask import Blueprint, request, render_template, redirect, url_for, flash, session, abort

from .db import query, execute, tx
from .sql import (
    # customers
    SQL_LIST_CUSTOMERS, SQL_GET_CUSTOMER, SQL_GET_CUSTOMER_BY_USER_ID, SQL_CREATE_CUSTOMER,
    SQL_LIST_BOOKINGS_FOR_CUSTOMER,

    # items
    SQL_LIST_ITEMS, SQL_AVAILABLE_ITEMS,
    SQL_ADD_TENT_ITEM, SQL_ADD_FURNISHING_ITEM,
    SQL_ITEM_HAS_ACTIVE_OR_FUTURE_BOOKING, SQL_DELETE_BOOKING_ITEMS_FOR_ITEM, SQL_DELETE_ITEM,

    # bookings
    SQL_CREATE_BOOKING, SQL_BOOKING_DETAIL, SQL_BOOKING_DETAIL_FOR_CUSTOMER,
    SQL_BOOKING_ITEMS, SQL_BOOKING_TOTAL, SQL_LIST_ALL_BOOKINGS,
    SQL_CONFIRM_BOOKING, SQL_CANCEL_BOOKING,
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

# Home: search + select items + place booking
@bp.get("/")
def home():
    uid, role = current_user()

    start = request.args.get("start_date", "")
    end = request.args.get("end_date", "")
    items = None
    customers = None

    if start and end:
        items = query(SQL_AVAILABLE_ITEMS, (start, end))

        if role == "admin":
            customers = query(SQL_LIST_CUSTOMERS)
        elif role == "customer" and uid:
            customers = [query(SQL_GET_CUSTOMER_BY_USER_ID, (uid,), one=True)]
        else:
            customers = None

    return render_template(
        "home.html",
        start_date=start,
        end_date=end,
        items=items,
        customers=customers,
        role=role
    )

@bp.post("/bookings/create")
def booking_create_from_home():
    uid, role = require_login()
    if not uid:
        flash("Please log in to place a booking.", "error")
        return redirect(url_for("auth.login_form"))

    start = request.form.get("start_date", "").strip()
    end = request.form.get("end_date", "").strip()
    item_ids = request.form.getlist("item_ids")

    if not start or not end:
        flash("Choose dates first.", "error")
        return redirect(url_for("routes.home"))

    if not item_ids:
        flash("Select at least one item.", "error")
        return redirect(url_for("routes.home", start_date=start, end_date=end))

    # Resolve customer_id
    if role == "admin":
        customer_id = request.form.get("customer_id", "").strip()
        if not customer_id:
            flash("Select a customer.", "error")
            return redirect(url_for("routes.home", start_date=start, end_date=end))
    else:
        cust = query(SQL_GET_CUSTOMER_BY_USER_ID, (uid,), one=True)
        if not cust:
            flash("No customer profile linked to this account.", "error")
            return redirect(url_for("routes.home", start_date=start, end_date=end))
        customer_id = str(cust["id"])

    try:
        item_ids_int = sorted({int(x) for x in item_ids})
    except ValueError:
        flash("Invalid item selection.", "error")
        return redirect(url_for("routes.home", start_date=start, end_date=end))

    available = query(SQL_AVAILABLE_ITEMS, (start, end))
    avail_ids = {row["id"] for row in available}
    if any(iid not in avail_ids for iid in item_ids_int):
        flash("Some selected items are no longer available. Please search again.", "error")
        return redirect(url_for("routes.home", start_date=start, end_date=end))

    def work(cur):
        # Lock item rows for reducing race conditions
        placeholders = ",".join(["%s"] * len(item_ids_int))
        cur.execute(
            f"SELECT id FROM items WHERE id IN ({placeholders}) ORDER BY id FOR UPDATE;",
            tuple(item_ids_int),
        )

        # Create booking header
        cur.execute(SQL_CREATE_BOOKING, (customer_id, start, end))
        booking_id = cur.fetchone()["id"]

        # Add booking_items lines
        for iid in item_ids_int:
            cur.execute(
                """
                INSERT INTO booking_items (booking_id, item_id, price_per_day)
                SELECT %s, i.id, i.daily_rate
                FROM items i
                WHERE i.id = %s;
                """,
                (booking_id, iid),
            )

        return booking_id

    try:
        booking_id = tx(work)
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

    # customer: goes to own customer detail directly
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

    full_name = request.form.get("full_name","").strip()
    email = request.form.get("email","").strip().lower()
    phone = request.form.get("phone","").strip() or None

    if not full_name or not email:
        flash("Full name and email are required.", "error")
        return redirect(url_for("routes.customer_new_form"))

    try:
        row = query(SQL_CREATE_CUSTOMER, (full_name, email, phone, None), one=True, commit=True)
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

# Admin: Inventory
@bp.get("/admin/items")
def admin_items():
    require_admin()
    return render_template("admin_items.html", items=query(SQL_LIST_ITEMS), role="admin")

@bp.get("/admin/items/tent/new")
def admin_tent_new_form():
    require_admin()
    return render_template("admin_tent_new.html", role="admin")

@bp.post("/admin/items/tent/new")
def admin_tent_new():
    require_admin()

    sku = request.form.get("sku","").strip()
    display_name = request.form.get("display_name","").strip()
    daily_rate = request.form.get("daily_rate","").strip()
    capacity = request.form.get("capacity","").strip()
    season_rating = request.form.get("season_rating","").strip()

    build_time = request.form.get("estimated_build_time_minutes","").strip() or "10"
    construction_cost = request.form.get("construction_cost","").strip() or "0"
    deconstruction_cost = request.form.get("deconstruction_cost","").strip() or "0"
    packed_weight = request.form.get("packed_weight_kg","").strip() or None
    floor_area = request.form.get("floor_area_m2","").strip() or None

    if not sku or not display_name or daily_rate=="" or not capacity or not season_rating:
        flash("Missing required fields.", "error")
        return redirect(url_for("routes.admin_tent_new_form"))

    try:
        row = query(SQL_ADD_TENT_ITEM, (
            sku, display_name, daily_rate,
            capacity, season_rating,
            build_time, construction_cost, deconstruction_cost,
            packed_weight, floor_area
        ), one=True, commit=True)
        flash(f"Tent item created (item_id={row['new_item_id']}).", "success")
    except Exception as e:
        flash(f"Failed: {str(e)}", "error")

    return redirect(url_for("routes.admin_items"))

@bp.get("/admin/items/furnishing/new")
def admin_furn_new_form():
    require_admin()
    return render_template("admin_furn_new.html", role="admin")

@bp.post("/admin/items/furnishing/new")
def admin_furn_new():
    require_admin()

    sku = request.form.get("sku","").strip()
    display_name = request.form.get("display_name","").strip()
    daily_rate = request.form.get("daily_rate","").strip()

    furnishing_kind = request.form.get("furnishing_kind","").strip()
    weight_kg = request.form.get("weight_kg","").strip() or None
    notes = request.form.get("notes","").strip() or None

    if not sku or not display_name or daily_rate=="" or not furnishing_kind:
        flash("Missing required fields.", "error")
        return redirect(url_for("routes.admin_furn_new_form"))

    try:
        row = query(SQL_ADD_FURNISHING_ITEM, (
            sku, display_name, daily_rate,
            furnishing_kind, weight_kg, notes
        ), one=True, commit=True)
        flash(f"Furnishing created (item_id={row['new_item_id']}).", "success")
    except Exception as e:
        flash(f"Failed: {str(e)}", "error")

    return redirect(url_for("routes.admin_items"))

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

# Booking detail + confirm/cancel
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
    return render_template("booking_detail.html", booking=booking, items=items, total=total, role=role)

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