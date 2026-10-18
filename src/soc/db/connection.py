"""Open a PostgreSQL connection from settings; the URL comes from the environment only."""

from collections.abc import Mapping
from urllib.parse import unquote, urlsplit

import psycopg

from soc.config import Settings, read_secret


class DatabaseConnectionError(ConnectionError):
    """The database could not be reached. The message never contains the URL or password."""


def _password(url: str) -> str | None:
    try:
        password = urlsplit(url).password
    except ValueError:
        return None
    return unquote(password) if password else None


def _redact(message: str, url: str) -> str:
    for secret in (url, _password(url)):
        if secret:
            message = message.replace(secret, "***")
    return message


def connect(settings: Settings, environ: Mapping[str, str] | None = None) -> psycopg.Connection:
    """Connect with the URL held in the environment variable `database.url_env` names."""
    env_name = settings.database.url_env
    url = read_secret(env_name, environ)
    try:
        return psycopg.connect(url, connect_timeout=settings.database.connect_timeout_seconds)
    except psycopg.ProgrammingError:
        # An unparsable URL: the driver's message quotes it, password included.
        raise DatabaseConnectionError(f"{env_name} is not a valid PostgreSQL URL") from None
    except psycopg.OperationalError as error:
        reason = _redact(str(error), url)
        raise DatabaseConnectionError(f"Could not connect using {env_name}: {reason}") from None
