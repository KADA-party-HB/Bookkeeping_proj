import os
import logging
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from .db import init_db, close_db
from .routes import bp as routes_bp
from .auth import bp as auth_bp


def _env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_optional_flag(name):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _env_decimal(name, default):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return Decimal(str(default))
    try:
        return Decimal(value.strip())
    except InvalidOperation as exc:
        raise RuntimeError(f"{name} must be a valid decimal value.") from exc


def create_app():
    load_dotenv()

    app_env = (os.getenv("APP_ENV") or "development").strip().lower()
    preferred_url_scheme = os.getenv("PREFERRED_URL_SCHEME") or (
        "https" if app_env == "production" else "http"
    )
    secret_key = (os.getenv("SECRET_KEY") or "").strip()
    if not secret_key:
        raise RuntimeError("SECRET_KEY must be set before the app can start.")

    pending_booking_hold_days = _env_int("PENDING_BOOKING_HOLD_DAYS", 7)
    if pending_booking_hold_days <= 0:
        raise RuntimeError("PENDING_BOOKING_HOLD_DAYS must be greater than 0.")

    max_active_pending_bookings = _env_int(
        "MAX_ACTIVE_PENDING_BOOKINGS_PER_CUSTOMER",
        3,
    )
    if max_active_pending_bookings <= 0:
        raise RuntimeError("MAX_ACTIVE_PENDING_BOOKINGS_PER_CUSTOMER must be greater than 0.")

    map_api_timeout_seconds = _env_int("MAP_API_TIMEOUT_SECONDS", 10)
    if map_api_timeout_seconds <= 0:
        raise RuntimeError("MAP_API_TIMEOUT_SECONDS must be greater than 0.")

    delivery_address_min_confidence = _env_decimal(
        "DELIVERY_ADDRESS_MIN_CONFIDENCE",
        "0.85",
    )
    if delivery_address_min_confidence < 0 or delivery_address_min_confidence > 1:
        raise RuntimeError("DELIVERY_ADDRESS_MIN_CONFIDENCE must be between 0 and 1.")

    max_content_length = _env_int("MAX_CONTENT_LENGTH", 1_048_576)
    if max_content_length <= 0:
        raise RuntimeError("MAX_CONTENT_LENGTH must be greater than 0.")

    stale_booking_cleanup_interval_seconds = _env_int(
        "STALE_BOOKING_CLEANUP_INTERVAL_SECONDS",
        300,
    )
    if stale_booking_cleanup_interval_seconds < 0:
        raise RuntimeError("STALE_BOOKING_CLEANUP_INTERVAL_SECONDS cannot be negative.")

    login_rate_limit_attempts = _env_int("LOGIN_RATE_LIMIT_ATTEMPTS", 5)
    if login_rate_limit_attempts <= 0:
        raise RuntimeError("LOGIN_RATE_LIMIT_ATTEMPTS must be greater than 0.")

    login_rate_limit_window_seconds = _env_int("LOGIN_RATE_LIMIT_WINDOW_SECONDS", 300)
    if login_rate_limit_window_seconds <= 0:
        raise RuntimeError("LOGIN_RATE_LIMIT_WINDOW_SECONDS must be greater than 0.")

    registration_rate_limit_attempts = _env_int("REGISTRATION_RATE_LIMIT_ATTEMPTS", 5)
    if registration_rate_limit_attempts <= 0:
        raise RuntimeError("REGISTRATION_RATE_LIMIT_ATTEMPTS must be greater than 0.")

    registration_rate_limit_window_seconds = _env_int(
        "REGISTRATION_RATE_LIMIT_WINDOW_SECONDS",
        900,
    )
    if registration_rate_limit_window_seconds <= 0:
        raise RuntimeError("REGISTRATION_RATE_LIMIT_WINDOW_SECONDS must be greater than 0.")

    guest_quote_rate_limit_attempts = _env_int("GUEST_QUOTE_RATE_LIMIT_ATTEMPTS", 20)
    if guest_quote_rate_limit_attempts <= 0:
        raise RuntimeError("GUEST_QUOTE_RATE_LIMIT_ATTEMPTS must be greater than 0.")

    guest_quote_rate_limit_window_seconds = _env_int(
        "GUEST_QUOTE_RATE_LIMIT_WINDOW_SECONDS",
        300,
    )
    if guest_quote_rate_limit_window_seconds <= 0:
        raise RuntimeError("GUEST_QUOTE_RATE_LIMIT_WINDOW_SECONDS must be greater than 0.")

    guest_booking_rate_limit_attempts = _env_int("GUEST_BOOKING_RATE_LIMIT_ATTEMPTS", 8)
    if guest_booking_rate_limit_attempts <= 0:
        raise RuntimeError("GUEST_BOOKING_RATE_LIMIT_ATTEMPTS must be greater than 0.")

    guest_booking_rate_limit_window_seconds = _env_int(
        "GUEST_BOOKING_RATE_LIMIT_WINDOW_SECONDS",
        600,
    )
    if guest_booking_rate_limit_window_seconds <= 0:
        raise RuntimeError("GUEST_BOOKING_RATE_LIMIT_WINDOW_SECONDS must be greater than 0.")

    mail_enabled = _env_flag("MAIL_ENABLED", default=False)
    smtp_host = (os.getenv("SMTP_HOST") or "").strip()
    smtp_port = _env_int("SMTP_PORT", 587)
    if smtp_port <= 0:
        raise RuntimeError("SMTP_PORT must be greater than 0.")

    smtp_use_ssl = _env_optional_flag("SMTP_USE_SSL")
    smtp_use_starttls = _env_optional_flag("SMTP_USE_STARTTLS")

    if smtp_use_ssl is None and smtp_use_starttls is None:
        if smtp_port == 465:
            smtp_use_ssl = True
            smtp_use_starttls = False
        else:
            smtp_use_ssl = False
            smtp_use_starttls = True
    elif smtp_use_ssl is None:
        smtp_use_ssl = False if smtp_use_starttls else smtp_port == 465
    elif smtp_use_starttls is None:
        smtp_use_starttls = not smtp_use_ssl

    if smtp_use_starttls and smtp_use_ssl:
        raise RuntimeError("SMTP_USE_STARTTLS and SMTP_USE_SSL cannot both be enabled.")

    smtp_timeout_seconds = _env_int("SMTP_TIMEOUT_SECONDS", 15)
    if smtp_timeout_seconds <= 0:
        raise RuntimeError("SMTP_TIMEOUT_SECONDS must be greater than 0.")

    smtp_from_email = (os.getenv("SMTP_FROM_EMAIL") or "").strip()
    if mail_enabled:
        if not smtp_host:
            raise RuntimeError("SMTP_HOST must be set when MAIL_ENABLED is enabled.")
        if not smtp_from_email:
            raise RuntimeError("SMTP_FROM_EMAIL must be set when MAIL_ENABLED is enabled.")

    app = Flask(__name__)
    app.logger.setLevel(logging.INFO)
    app.config.update(
        SECRET_KEY=secret_key,
        PREFERRED_URL_SCHEME=preferred_url_scheme,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE=os.getenv("SESSION_COOKIE_SAMESITE", "Lax"),
        SESSION_COOKIE_SECURE=_env_flag(
            "SESSION_COOKIE_SECURE",
            default=preferred_url_scheme == "https",
        ),
        PENDING_BOOKING_HOLD_DAYS=pending_booking_hold_days,
        MAX_ACTIVE_PENDING_BOOKINGS_PER_CUSTOMER=max_active_pending_bookings,
        MAP_API_KEY=(os.getenv("MAP_API_KEY") or "").strip(),
        MAP_API_GEOCODE_URL=(
            os.getenv("MAP_API_GEOCODE_URL")
            or "https://api.geoapify.com/v1/geocode/search"
        ),
        MAP_API_ROUTE_URL=(
            os.getenv("MAP_API_ROUTE_URL")
            or "https://api.geoapify.com/v1/routing"
        ),
        MAP_API_TIMEOUT_SECONDS=map_api_timeout_seconds,
        MAP_API_USER_AGENT=(
            os.getenv("MAP_API_USER_AGENT")
            or "KadaPartyRentals/1.0"
        ),
        DELIVERY_ORIGIN_ADDRESS=(os.getenv("DELIVERY_ORIGIN_ADDRESS") or "").strip(),
        DELIVERY_GEOCODE_COUNTRYCODE=(
            os.getenv("DELIVERY_GEOCODE_COUNTRYCODE") or ""
        ).strip(),
        DELIVERY_ROUTE_MODE=(os.getenv("DELIVERY_ROUTE_MODE") or "drive").strip(),
        DELIVERY_ADDRESS_MIN_CONFIDENCE=delivery_address_min_confidence,
        MAX_CONTENT_LENGTH=max_content_length,
        STALE_BOOKING_CLEANUP_INTERVAL_SECONDS=stale_booking_cleanup_interval_seconds,
        LOGIN_RATE_LIMIT_ATTEMPTS=login_rate_limit_attempts,
        LOGIN_RATE_LIMIT_WINDOW_SECONDS=login_rate_limit_window_seconds,
        REGISTRATION_RATE_LIMIT_ATTEMPTS=registration_rate_limit_attempts,
        REGISTRATION_RATE_LIMIT_WINDOW_SECONDS=registration_rate_limit_window_seconds,
        GUEST_QUOTE_RATE_LIMIT_ATTEMPTS=guest_quote_rate_limit_attempts,
        GUEST_QUOTE_RATE_LIMIT_WINDOW_SECONDS=guest_quote_rate_limit_window_seconds,
        GUEST_BOOKING_RATE_LIMIT_ATTEMPTS=guest_booking_rate_limit_attempts,
        GUEST_BOOKING_RATE_LIMIT_WINDOW_SECONDS=guest_booking_rate_limit_window_seconds,
        MAIL_ENABLED=mail_enabled,
        SMTP_HOST=smtp_host,
        SMTP_PORT=smtp_port,
        SMTP_USERNAME=(os.getenv("SMTP_USERNAME") or "").strip(),
        SMTP_PASSWORD=os.getenv("SMTP_PASSWORD") or "",
        SMTP_USE_STARTTLS=smtp_use_starttls,
        SMTP_USE_SSL=smtp_use_ssl,
        SMTP_TIMEOUT_SECONDS=smtp_timeout_seconds,
        SMTP_FROM_EMAIL=smtp_from_email,
        SMTP_FROM_NAME=(os.getenv("SMTP_FROM_NAME") or "KADA PartyTillbehör").strip(),
        BOOKING_EMAIL_REPLY_TO=(os.getenv("BOOKING_EMAIL_REPLY_TO") or "").strip(),
        BOOKING_EMAIL_SITE_NAME=(os.getenv("BOOKING_EMAIL_SITE_NAME") or "KADA PartyTillbehör").strip(),
    )

    if _env_flag("TRUST_PROXY_HEADERS", default=False):
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=_env_int("PROXY_FIX_X_FOR", 1),
            x_proto=_env_int("PROXY_FIX_X_PROTO", 1),
            x_host=_env_int("PROXY_FIX_X_HOST", 1),
            x_port=_env_int("PROXY_FIX_X_PORT", 1),
        )

    init_db(app)
    app.teardown_appcontext(close_db)

    app.register_blueprint(auth_bp)
    app.register_blueprint(routes_bp)

    app.logger.info(
        "mail_config_ready enabled=%s host=%s port=%s ssl=%s starttls=%s from_email=%s",
        mail_enabled,
        smtp_host,
        smtp_port,
        smtp_use_ssl,
        smtp_use_starttls,
        smtp_from_email,
    )

    return app
