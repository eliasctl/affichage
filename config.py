import os
import secrets

SECRET_KEY     = os.environ.get("SECRET_KEY") or secrets.token_hex(24)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-moi")
