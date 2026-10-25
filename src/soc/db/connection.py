"""Open a PostgreSQL connection from settings; the URL comes from the environment only."""

from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout, TooManyRequests

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


# Read-only transactions on top of the read-only account: a write fails even if
# that account was granted more than SELECT (docs/security-policy.md 4).
READ_ONLY_OPTIONS = "-c default_transaction_read_only=on"


def connect(settings: Settings, environ: Mapping[str, str] | None = None) -> psycopg.Connection:
    """Connect with the URL held in the environment variable `database.url_env` names."""
    return _connect(settings.database.url_env, settings, environ)


def connect_readonly(
    settings: Settings, environ: Mapping[str, str] | None = None
) -> psycopg.Connection:
    """Connect with the read-only account `database.readonly_url_env` names.

    This is the connection agent tools read through (box 15). It also forces
    read-only transactions, so a write fails on the connection, not only on the
    account's grants.
    """
    return _connect(settings.database.readonly_url_env, settings, environ, READ_ONLY_OPTIONS)


def _connect(
    env_name: str,
    settings: Settings,
    environ: Mapping[str, str] | None,
    options: str | None = None,
) -> psycopg.Connection:
    url = read_secret(env_name, environ)
    try:
        # Autocommit: a read must not leave a transaction open, or a later
        # `with connection.transaction()` becomes a savepoint inside it and
        # close rolls the write back (#83). Multi-statement writes still use
        # `with connection.transaction()`.
        return psycopg.connect(
            url,
            autocommit=True,
            connect_timeout=settings.database.connect_timeout_seconds,
            **({"options": options} if options else {}),
        )
    except psycopg.ProgrammingError:
        # An unparsable URL: the driver's message quotes it, password included.
        raise DatabaseConnectionError(f"{env_name} is not a valid PostgreSQL URL") from None
    except psycopg.OperationalError as error:
        reason = _redact(str(error), url)
        raise DatabaseConnectionError(f"Could not connect using {env_name}: {reason}") from None


# What the pool raises when it cannot hand out a connection. These subclass
# psycopg.OperationalError, so they are caught by name: catching that base would
# turn an error raised while a request reads into "could not connect".
POOL_ERRORS = (PoolClosed, PoolTimeout, TooManyRequests)


class ReadonlyPool:
    """Read-only connections the screen API borrows one of per request (box 27, #104).

    The pool opens its own connections, so it carries the same options a single
    connection gets: autocommit (#83) and the read-only transaction option, which
    makes a write fail on the connection and not only on the account's grants
    (``docs/security-policy.md`` 4). Pool failures become
    ``DatabaseConnectionError`` with the URL and password taken out.
    """

    def __init__(self, pool: ConnectionPool, env_name: str, url: str, timeout_seconds: int) -> None:
        self._pool = pool
        self._env_name = env_name
        self._url = url
        self._timeout_seconds = timeout_seconds

    def open(self) -> None:
        """Fill the pool, for the service to start. Raises DatabaseConnectionError."""
        try:
            # Waiting is the point: the default opens connections in the background,
            # and a database that cannot be reached would only show up on the first
            # request instead of failing the start.
            self._pool.open(wait=True, timeout=self._timeout_seconds)
        except POOL_ERRORS as error:
            raise self._failure(error) from None

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        """Borrow one connection and give it back when the block ends."""
        with ExitStack() as stack:
            try:
                conn = stack.enter_context(self._pool.connection())
            except POOL_ERRORS as error:
                raise self._failure(error) from None
            # Only the borrow above is converted. Whatever the block raises stays
            # what it is, and the stack gives the connection back either way.
            yield conn

    def close(self) -> None:
        self._pool.close()

    def _failure(self, error: Exception) -> DatabaseConnectionError:
        reason = _redact(str(error), self._url)
        return DatabaseConnectionError(f"Could not connect using {self._env_name}: {reason}")


def open_readonly_pool(
    settings: Settings, environ: Mapping[str, str] | None = None
) -> ReadonlyPool:
    """A pool on the read-only account `database.readonly_url_env` names (box 27).

    The pool is created closed; the service opens it when it starts and closes it
    when it shuts down.
    """
    env_name = settings.database.readonly_url_env
    url = read_secret(env_name, environ)
    try:
        # The pool hands the URL to its background workers without parsing it first,
        # so an unparsable one would come back as a start timeout instead of this.
        conninfo_to_dict(url)
    except psycopg.ProgrammingError:
        raise DatabaseConnectionError(f"{env_name} is not a valid PostgreSQL URL") from None
    database = settings.database
    pool = ConnectionPool(
        url,
        open=False,
        # One idle connection is enough for a read-only screen API; the pool grows
        # up to max_size as requests come in.
        min_size=1,
        max_size=database.pool_max_size,
        timeout=database.pool_timeout_seconds,
        kwargs={
            "autocommit": True,
            "options": READ_ONLY_OPTIONS,
            "connect_timeout": database.connect_timeout_seconds,
        },
    )
    return ReadonlyPool(pool, env_name, url, database.pool_timeout_seconds)
