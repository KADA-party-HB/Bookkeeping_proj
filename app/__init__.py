import os

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


def create_app():
    load_dotenv()

    app_env = (os.getenv("APP_ENV") or "development").strip().lower()
    preferred_url_scheme = os.getenv("PREFERRED_URL_SCHEME") or (
        "https" if app_env == "production" else "http"
    )

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-secret"),
        PREFERRED_URL_SCHEME=preferred_url_scheme,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE=os.getenv("SESSION_COOKIE_SAMESITE", "Lax"),
        SESSION_COOKIE_SECURE=_env_flag(
            "SESSION_COOKIE_SECURE",
            default=preferred_url_scheme == "https",
        ),
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
