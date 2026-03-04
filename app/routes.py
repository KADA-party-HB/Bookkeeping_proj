from flask import Blueprint, request, render_template, redirect, url_for, flash, session, abort

from .db import query, execute, tx
from .sql import (
    # customers
    SQL_LIST_CUSTOMERS, SQL_GET_CUSTOMER, SQL_GET_CUSTOMER_BY_USER_ID, SQL_CREATE_CUSTOMER,
    SQL_LIST_BOOKINGS_FOR_CUSTOMER,

    # booking
    SQL_AVAILABLE_CATEGORIES, SQL_CREATE_BOOKING_WITH_ALLOCATIONS,

    # units
    SQL_LIST_UNITS, SQL_LIST_CATEGORIES_FOR_DROPDOWN,
    SQL_GET_UNIT_FOR_EDIT, SQL_UPDATE_UNIT,
    SQL_ADD_ITEM_UNIT,
    SQL_ITEM_HAS_ACTIVE_OR_FUTURE_BOOKING, SQL_DELETE_BOOKING_ITEMS_FOR_ITEM, SQL_DELETE_ITEM,

    # categories
    SQL_LIST_CATEGORIES, SQL_GET_CATEGORY_FOR_EDIT,
    SQL_CREATE_CATEGORY, SQL_CREATE_TENT_CATEGORY_ROW, SQL_CREATE_FURN_CATEGORY_ROW,
    SQL_UPDATE_CATEGORY_BASE, SQL_UPDATE_TENT_CATEGORY, SQL_UPDATE_FURN_CATEGORY,

    # booking details
    SQL_BOOKING_DETAIL, SQL_BOOKING_DETAIL_FOR_CUSTOMER,
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

# Home (category availability)
@bp.get("/")
def home():
    uid, role = current_user()
    start = request.args.get("start_date", "")
    end = request.args.get("end_date", "")

    categories = None
    customers = None

    if start and end:
        categories = query(SQL_AVAILABLE_CATEGORIES, (start, end))
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
        categories=categories,
        customers=customers,
        role=role
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

    # customer_id
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

    # parse qty
    selections = []
    for k, v in request.form.items():
        if k.startswith("qty_"):
            try:
                cat_id = int(k.split("_", 1)[1])
                qty = int(v) if v.strip() else 0
            except Exception:
                continue
            if qty > 0:
                selections.append((cat_id, qty))

    if not selections:
        flash("Select at least one category quantity.", "error")
        return redirect(url_for("routes.home", start_date=start, end_date=end))

    category_ids = [cid for cid, _ in selections]
    qtys = [q for _, q in selections]

    try:
        row = query(
            SQL_CREATE_BOOKING_WITH_ALLOCATIONS,
            (customer_id, start, end, category_ids, qtys),
            one=True,
            commit=True
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

# Admin: Items (physical items)
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
    is_active = (request.form.get("is_active") == "on")

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
    is_active = (request.form.get("is_active") == "on")

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

# Admin: CATEGORIES (shared product models)
@bp.get("/admin/categories")
def admin_categories():
    require_admin()
    categories = query(SQL_LIST_CATEGORIES)
    return render_template("admin_categories.html", categories=categories, role="admin")

@bp.get("/admin/categories/tent/new")
def admin_category_tent_new_form():
    require_admin()
    return render_template("admin_category_tent_new.html", role="admin")

@bp.post("/admin/categories/tent/new")
def admin_category_tent_new():
    require_admin()

    name = request.form.get("display_name","").strip()
    daily_rate = request.form.get("daily_rate","").strip()
    capacity = request.form.get("capacity","").strip()
    season_rating = request.form.get("season_rating","").strip()
    build_time = request.form.get("estimated_build_time_minutes","").strip() or "10"
    construction_cost = request.form.get("construction_cost","").strip() or "0"
    deconstruction_cost = request.form.get("deconstruction_cost","").strip() or "0"
    packed_weight = request.form.get("packed_weight_kg","").strip() or None
    floor_area = request.form.get("floor_area_m2","").strip() or None

    if not name or daily_rate=="" or not capacity or not season_rating:
        flash("Missing required fields.", "error")
        return redirect(url_for("routes.admin_category_tent_new_form"))

    def work(cur):
        cur.execute(SQL_CREATE_CATEGORY, (name, daily_rate))
        cat_id = cur.fetchone()["id"]
        cur.execute(SQL_CREATE_TENT_CATEGORY_ROW, (
            cat_id, capacity, season_rating, packed_weight, floor_area,
            build_time, construction_cost, deconstruction_cost
        ))
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
    return render_template("admin_category_furn_new.html", role="admin")

@bp.post("/admin/categories/furnishing/new")
def admin_category_furn_new():
    require_admin()

    name = request.form.get("display_name","").strip()
    daily_rate = request.form.get("daily_rate","").strip()
    kind = request.form.get("furnishing_kind","").strip()
    weight_kg = request.form.get("weight_kg","").strip() or None
    notes = request.form.get("notes","").strip() or None

    if not name or daily_rate=="" or not kind:
        flash("Missing required fields.", "error")
        return redirect(url_for("routes.admin_category_furn_new_form"))

    def work(cur):
        cur.execute(SQL_CREATE_CATEGORY, (name, daily_rate))
        cat_id = cur.fetchone()["id"]
        cur.execute(SQL_CREATE_FURN_CATEGORY_ROW, (cat_id, kind, weight_kg, notes))
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
    return render_template("admin_category_edit.html", cat=cat, role="admin")

@bp.post("/admin/categories/<int:category_id>/edit")
def admin_category_edit_save(category_id: int):
    require_admin()
    cat = query(SQL_GET_CATEGORY_FOR_EDIT, (category_id,), one=True)
    if not cat:
        flash("Category not found.", "error")
        return redirect(url_for("routes.admin_categories"))

    display_name = request.form.get("display_name","").strip()
    daily_rate = request.form.get("daily_rate","").strip()
    if not display_name or daily_rate == "":
        flash("Name and daily rate are required.", "error")
        return redirect(url_for("routes.admin_category_edit_form", category_id=category_id))

    def to_int(v):
        v = (v or "").strip()
        return int(v) if v != "" else None

    def to_num(v):
        v = (v or "").strip()
        return v if v != "" else None

    def work(cur):
        cur.execute(SQL_UPDATE_CATEGORY_BASE, (display_name, daily_rate, category_id))

        if cat["is_tent"]:
            capacity = to_int(request.form.get("capacity"))
            season_rating = to_int(request.form.get("season_rating"))
            packed_weight_kg = to_num(request.form.get("packed_weight_kg"))
            floor_area_m2 = to_num(request.form.get("floor_area_m2"))
            build_time = to_int(request.form.get("estimated_build_time_minutes"))
            construction_cost = to_num(request.form.get("construction_cost")) or "0"
            deconstruction_cost = to_num(request.form.get("deconstruction_cost")) or "0"
            cur.execute(SQL_UPDATE_TENT_CATEGORY, (
                capacity, season_rating, packed_weight_kg, floor_area_m2,
                build_time, construction_cost, deconstruction_cost,
                category_id
            ))
        else:
            kind = request.form.get("furnishing_kind","").strip()
            weight_kg = to_num(request.form.get("weight_kg"))
            notes = request.form.get("notes","").strip() or None
            cur.execute(SQL_UPDATE_FURN_CATEGORY, (kind, weight_kg, notes, category_id))

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