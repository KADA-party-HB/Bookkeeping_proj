import os
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

    app = Flask(__name__)
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

    return app
