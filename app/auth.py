from flask import Blueprint, request, render_template, redirect, url_for, flash, session, current_app
from psycopg import errors
from werkzeug.security import generate_password_hash, check_password_hash

from .db import query, tx
from .sql import (
    SQL_CREATE_USER,
    SQL_GET_USER_BY_EMAIL,
    SQL_GET_CUSTOMER_BY_EMAIL,
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
        flash("E-post och lösenord krävs.", "error")
        return redirect(url_for("auth.login_form"))

    user = query(SQL_GET_USER_BY_EMAIL, (email,), one=True)
    if not user or not check_password_hash(user["password_hash"], password):
        flash("Felaktig e-post eller lösenord.", "error")
        return redirect(url_for("auth.login_form"))

    session.clear()
    session["user_id"] = user["id"]
    session["role"] = user["role"]

    flash("Du är nu inloggad.", "success")
    return redirect(url_for("routes.home"))


@bp.get("/logout")
def logout_redirect():
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
        flash("Namn, e-post och lösenord krävs.", "error")
        return redirect(url_for("auth.register_form"))

    existing_user = query(SQL_GET_USER_BY_EMAIL, (email,), one=True)
    if existing_user:
        flash("Den e-postadressen är redan registrerad. Logga in i stället.", "error")
        return redirect(url_for("auth.login_form"))

    existing_customer = query(SQL_GET_CUSTOMER_BY_EMAIL, (email,), one=True)
    if existing_customer:
        flash(
            "Den e-postadressen tillhör redan en befintlig kundprofil. Av säkerhetsskäl är egen registrering blockerad för e-postadresser som redan finns på en förskapad kund. Be en administratör att uppdatera eller ta bort kundens e-postadress innan du registrerar dig.",
            "error",
        )
        return redirect(url_for("auth.register_form"))

    pw_hash = generate_password_hash(password)

    try:
        def work(cur):
            cur.execute(SQL_CREATE_USER, (email, pw_hash, "customer"))
            user = cur.fetchone()

            cur.execute(SQL_CREATE_CUSTOMER, (full_name, email, phone, None, None, user["id"]))
            cur.fetchone()

            return user

        user = tx(work)

    except errors.UniqueViolation:
        flash("Den e-postadressen är redan registrerad. Logga in i stället.", "error")
        return redirect(url_for("auth.login_form"))
    except Exception:
        current_app.logger.exception("Registration failed for email %s", email)
        flash("Registreringen misslyckades. Försök igen.", "error")
        return redirect(url_for("auth.register_form"))

    session.clear()
    session["user_id"] = user["id"]
    session["role"] = user["role"]

    flash("Kontot är skapat.", "success")
    return redirect(url_for("routes.home"))


@bp.post("/logout")
def logout():
    session.clear()
    flash("Du är nu utloggad.", "success")
    return redirect(url_for("routes.home"))
