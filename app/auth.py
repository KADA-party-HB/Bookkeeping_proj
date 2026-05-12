from hashlib import sha256

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from psycopg import errors
from werkzeug.security import check_password_hash, generate_password_hash

from .db import query, tx
from .mailer import send_password_reset_email
from .sql import (
    SQL_CREATE_CUSTOMER,
    SQL_CREATE_USER,
    SQL_GET_CUSTOMER_BY_EMAIL,
    SQL_GET_USER_BY_EMAIL,
    SQL_GET_USER_BY_ID,
    SQL_UPDATE_USER_PASSWORD,
)

bp = Blueprint("auth", __name__, url_prefix="/auth")
PASSWORD_RESET_SALT = "password-reset"


def _normalize_email(value):
    return (value or "").strip().lower()


def _password_reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def _password_reset_fingerprint(password_hash: str) -> str:
    return sha256((password_hash or "").encode("utf-8")).hexdigest()


def _generate_password_reset_token(user) -> str:
    return _password_reset_serializer().dumps(
        {
            "user_id": int(user["id"]),
            "fp": _password_reset_fingerprint(user["password_hash"]),
        },
        salt=PASSWORD_RESET_SALT,
    )


def _get_password_reset_user(token: str):
    max_age = int(current_app.config["PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS"])
    try:
        payload = _password_reset_serializer().loads(
            token,
            salt=PASSWORD_RESET_SALT,
            max_age=max_age,
        )
    except SignatureExpired:
        return None, "expired"
    except BadSignature:
        return None, "invalid"

    user_id = payload.get("user_id")
    fingerprint = payload.get("fp")
    if not isinstance(user_id, int) or not isinstance(fingerprint, str):
        return None, "invalid"

    user = query(SQL_GET_USER_BY_ID, (user_id,), one=True)
    if not user:
        return None, "invalid"

    if _password_reset_fingerprint(user["password_hash"]) != fingerprint:
        return None, "used"

    return user, None


@bp.get("/login")
def login_form():
    return render_template("login.html")


@bp.post("/login")
def login():
    email = _normalize_email(request.form.get("email"))
    password = request.form.get("password", "")

    if not email or not password:
        flash("E-post och l\u00f6senord kr\u00e4vs.", "error")
        return redirect(url_for("auth.login_form"))

    user = query(SQL_GET_USER_BY_EMAIL, (email,), one=True)
    if not user or not check_password_hash(user["password_hash"], password):
        flash("Felaktig e-post eller l\u00f6senord.", "error")
        return redirect(url_for("auth.login_form"))

    session.clear()
    session["user_id"] = user["id"]
    session["role"] = user["role"]

    flash("Du \u00e4r nu inloggad.", "success")
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
    password_confirm = request.form.get("password_confirm", "")

    if not full_name or not email or not password:
        flash("Namn, e-post och l\u00f6senord kr\u00e4vs.", "error")
        return redirect(url_for("auth.register_form"))

    if password != password_confirm:
        flash("L\u00f6senorden matchar inte.", "error")
        return redirect(url_for("auth.register_form"))

    existing_user = query(SQL_GET_USER_BY_EMAIL, (email,), one=True)
    if existing_user:
        flash("Den e-postadressen \u00e4r redan registrerad. Logga in i st\u00e4llet.", "error")
        return redirect(url_for("auth.login_form"))

    existing_customer = query(SQL_GET_CUSTOMER_BY_EMAIL, (email,), one=True)
    if existing_customer:
        flash(
            "Den e-postadressen tillh\u00f6r redan en befintlig kundprofil. Av s\u00e4kerhetssk\u00e4l \u00e4r egen registrering blockerad f\u00f6r e-postadresser som redan finns p\u00e5 en f\u00f6rskapad kund. Be en administrat\u00f6r att uppdatera eller ta bort kundens e-postadress innan du registrerar dig.",
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
        flash("Den e-postadressen \u00e4r redan registrerad. Logga in i st\u00e4llet.", "error")
        return redirect(url_for("auth.login_form"))
    except Exception:
        current_app.logger.exception("Registration failed for email %s", email)
        flash("Registreringen misslyckades. F\u00f6rs\u00f6k igen.", "error")
        return redirect(url_for("auth.register_form"))

    session.clear()
    session["user_id"] = user["id"]
    session["role"] = user["role"]

    flash("Kontot \u00e4r skapat.", "success")
    return redirect(url_for("routes.home"))


@bp.get("/forgot-password")
def forgot_password_form():
    return render_template("forgot_password.html")


@bp.post("/forgot-password")
def forgot_password():
    email = _normalize_email(request.form.get("email"))

    if not email:
        flash("Ange din e-postadress.", "error")
        return redirect(url_for("auth.forgot_password_form"))

    user = query(SQL_GET_USER_BY_EMAIL, (email,), one=True)
    if user:
        reset_url = url_for(
            "auth.reset_password_form",
            token=_generate_password_reset_token(user),
            _external=True,
        )
        try:
            send_password_reset_email(user=user, reset_url=reset_url)
        except Exception:
            current_app.logger.exception("Password reset email failed for email %s", email)

    if not current_app.config.get("MAIL_ENABLED"):
        flash(
            "E-post \u00e4r inte aktiverat i den h\u00e4r milj\u00f6n. Om adressen finns i systemet loggas \u00e5terst\u00e4llningsl\u00e4nken p\u00e5 servern.",
            "info",
        )

    flash(
        "Om adressen finns i systemet har vi skickat en l\u00e4nk f\u00f6r att \u00e5terst\u00e4lla l\u00f6senordet.",
        "success",
    )
    return redirect(url_for("auth.login_form"))


@bp.get("/reset-password/<token>")
def reset_password_form(token):
    user, error = _get_password_reset_user(token)
    if error:
        if error == "expired":
            flash("L\u00e4nken har g\u00e5tt ut. Beg\u00e4r en ny \u00e5terst\u00e4llningsl\u00e4nk.", "error")
        else:
            flash("L\u00e4nken \u00e4r ogiltig eller har redan anv\u00e4nts. Beg\u00e4r en ny \u00e5terst\u00e4llningsl\u00e4nk.", "error")
        return redirect(url_for("auth.forgot_password_form"))

    return render_template("reset_password.html", token=token, email=user["email"])


@bp.post("/reset-password/<token>")
def reset_password(token):
    user, error = _get_password_reset_user(token)
    if error:
        if error == "expired":
            flash("L\u00e4nken har g\u00e5tt ut. Beg\u00e4r en ny \u00e5terst\u00e4llningsl\u00e4nk.", "error")
        else:
            flash("L\u00e4nken \u00e4r ogiltig eller har redan anv\u00e4nts. Beg\u00e4r en ny \u00e5terst\u00e4llningsl\u00e4nk.", "error")
        return redirect(url_for("auth.forgot_password_form"))

    password = request.form.get("password", "")
    password_confirm = request.form.get("password_confirm", "")

    if not password:
        flash("Ange ett nytt l\u00f6senord.", "error")
        return redirect(url_for("auth.reset_password_form", token=token))

    if password != password_confirm:
        flash("L\u00f6senorden matchar inte.", "error")
        return redirect(url_for("auth.reset_password_form", token=token))

    updated_user = query(
        SQL_UPDATE_USER_PASSWORD,
        (generate_password_hash(password), user["id"]),
        one=True,
        commit=True,
    )
    if not updated_user:
        current_app.logger.warning(
            "Password reset update affected no rows for user_id=%s",
            user["id"],
        )
        flash("Kunde inte uppdatera l\u00f6senordet. F\u00f6rs\u00f6k igen.", "error")
        return redirect(url_for("auth.forgot_password_form"))

    session.clear()
    flash("Ditt l\u00f6senord \u00e4r uppdaterat. Du kan nu logga in.", "success")
    return redirect(url_for("auth.login_form"))


@bp.post("/logout")
def logout():
    session.clear()
    flash("Du \u00e4r nu utloggad.", "success")
    return redirect(url_for("routes.home"))
