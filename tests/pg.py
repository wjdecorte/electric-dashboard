"""Shared PostgreSQL test helper.

Tests need a throwaway database. Point TEST_DATABASE_URL at one (its public schema is wiped
before every test); the default matches the container in the README's development section.
"""

import os

DEFAULT_URL = "postgresql://postgres:test@127.0.0.1:55432/ampersight_test"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", DEFAULT_URL)

import psycopg  # noqa: E402


def reset_database():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as db:
        db.execute("DROP SCHEMA public CASCADE")
        db.execute("CREATE SCHEMA public")
