from contextlib import contextmanager
import os

import psycopg

from core.config import DATABASE_URL_ENV_VAR


def get_database_url() -> str:
    database_url = os.getenv(DATABASE_URL_ENV_VAR, "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Add it to your .env file.")
    return database_url


@contextmanager
def get_connection():
    connection = psycopg.connect(get_database_url())
    try:
        yield connection
    finally:
        connection.close()
