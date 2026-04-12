from flask import Blueprint, request, render_template, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash

from .db import query, tx
from .sql import (
    SQL_CREATE_USER,
    SQL_GET_USER_BY_EMAIL,
    SQL_LINK_CUSTOMER_TO_USER,
    SQL_CREATE_CUSTOMER,
)

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _normalize_email(value):
    return (value or "").strip().lower()


@bp.get("/login")
def login_form():
    return render_template("login.html")


@bp.post("/login")
def login():
    email = _normalize_email(request.form.get("email"))
    password = request.form.get("password", "")

    if not email or not password:
        flash("Email and password are required.", "error")
        return redirect(url_for("auth.login_form"))

    user = query(SQL_GET_USER_BY_EMAIL, (email,), one=True)
    if not user or not check_password_hash(user["password_hash"], password):
        flash("Invalid email or password.", "error")
        return redirect(url_for("auth.login_form"))

    session.clear()
    session["user_id"] = user["id"]
    session["role"] = user["role"]

    flash("Logged in.", "success")
    return redirect(url_for("routes.home"))


@bp.get("/register")
def register_form():
    return render_template("register.html")


@bp.post("/register")
def register():
    full_name = request.form.get("full_name", "").strip()
    email = _normalize_email(request.form.get("email"))
    phone = (request.form.get("phone", "") or "").strip() or None
    password = request.form.get("password", "")

    if not full_name or not email or not password:
        flash("Name, email and password are required.", "error")
        return redirect(url_for("auth.register_form"))

    pw_hash = generate_password_hash(password)

    try:
        def work(cur):
            cur.execute(SQL_CREATE_USER, (email, pw_hash, "customer"))
            user = cur.fetchone()

            # If admin already created a customer with same email, link it
            cur.execute(SQL_LINK_CUSTOMER_TO_USER, (user["id"], email))
            linked = cur.fetchone()

            # Otherwise create a new customer profile linked to this user
            if not linked:
                cur.execute(SQL_CREATE_CUSTOMER, (full_name, email, phone, user["id"]))
                cur.fetchone()

            return user

        user = tx(work)

    except Exception:
        flash("Registration failed (email may already exist).", "error")
        return redirect(url_for("auth.register_form"))

    session.clear()
    session["user_id"] = user["id"]
    session["role"] = user["role"]

    flash("Account created.", "success")
    return redirect(url_for("routes.home"))


@bp.get("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("routes.home"))