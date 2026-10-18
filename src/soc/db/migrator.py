"""Apply numbered SQL files in order and record them in schema_migrations.

Files are named `NNNN_<name>.sql` (four digits, lowercase name). Each file runs
in its own transaction together with its record, so a failing file leaves no
trace and the next run retries it. Applied files are never run again; a change
to the schema is a new file. Run them with `uv run python -m soc.db.migrate`.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import psycopg

DEFAULT_MIGRATIONS = Path(__file__).resolve().parent / "migrations"
FILE_NAME = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version integer PRIMARY KEY,
    name text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


class MigrationError(RuntimeError):
    """A migration file is misnamed, duplicated, or failed to apply."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path

    @property
    def label(self) -> str:
        return f"{self.version:04d}_{self.name}"


def discover_migrations(directory: Path = DEFAULT_MIGRATIONS) -> list[Migration]:
    """Return the `.sql` files of `directory` in version order."""
    found: dict[int, Migration] = {}
    for path in sorted(Path(directory).glob("*.sql")):
        match = FILE_NAME.match(path.name)
        if match is None:
            raise MigrationError(f"{path.name}: migration files are named NNNN_<name>.sql")
        migration = Migration(int(match["version"]), match["name"], path)
        if migration.version in found:
            other = found[migration.version].path.name
            raise MigrationError(f"Version {match['version']} is used twice: {other}, {path.name}")
        found[migration.version] = migration
    return [found[version] for version in sorted(found)]


def apply_migrations(
    conn: psycopg.Connection, directory: Path = DEFAULT_MIGRATIONS
) -> list[Migration]:
    """Apply the files not yet recorded and return them in the order applied."""
    migrations = discover_migrations(directory)
    with conn.transaction():
        conn.execute(_CREATE_TABLE)
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    done = []
    for migration in migrations:
        if migration.version in applied:
            continue
        try:
            with conn.transaction():
                conn.execute(migration.path.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                    (migration.version, migration.name),
                )
        except psycopg.Error as error:
            raise MigrationError(f"{migration.label} failed: {error}") from error
        done.append(migration)
    return done
