from app import create_app
from werkzeug.serving import make_ssl_devcert
import os

CERT_DIR = "certs"
CERT_BASE = os.path.join(CERT_DIR, "devcert")
CERT_FILE = f"{CERT_BASE}.crt"
KEY_FILE = f"{CERT_BASE}.key"

os.makedirs(CERT_DIR, exist_ok=True)

if not os.path.exists(CERT_FILE) or not os.path.exists(KEY_FILE):
    make_ssl_devcert(CERT_BASE, host="localhost")

app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=9343,
        ssl_context=(CERT_FILE, KEY_FILE),
        debug=True,
    )