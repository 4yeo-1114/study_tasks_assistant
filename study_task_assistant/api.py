"""Uvicorn entry point; HTTP implementation lives in web/api.py."""
from web.api import app, create_app, get_default_database_url, normalize_database_url
