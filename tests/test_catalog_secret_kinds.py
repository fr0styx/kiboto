"""A template's secret follows the form its app checks: hexadecimal, a Laravel key, or plain."""

import base64
import re

from backend.services import app_catalog


def test_the_kinds_of_secret():
    hexed = app_catalog.new_secret("encryption_key_hex")
    assert re.fullmatch(r"[0-9a-f]{64}", hexed)
    key = app_catalog.new_secret("app_appkey")
    assert key.startswith("base64:") and len(base64.b64decode(key[7:])) == 32
    plain = app_catalog.new_secret("db_password")
    assert re.fullmatch(r"[A-Za-z0-9_-]{32}", plain)
    assert app_catalog.new_secret("db_password") != plain


def test_one_name_is_one_secret_everywhere_in_an_app():
    kept: dict[str, str] = {}
    a = app_catalog._fill_secrets("{{secret:app_appkey}}", kept)
    b = app_catalog._fill_secrets("KEY={{secret:app_appkey}} PW={{secret:db_password}}", kept)
    assert b.startswith(f"KEY={a} PW=") and set(kept) == {"app_appkey", "db_password"}
