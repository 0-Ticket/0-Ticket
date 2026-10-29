"""Command: apply pending migrations to the database in DATABASE_URL.

Usage: `uv run python -m soc.db.migrate`
"""

from soc.config import load_config
from soc.db.connection import connect
from soc.db.migrator import apply_migrations


def main() -> None:
    with connect(load_config()) as conn:
        applied = apply_migrations(conn)
    if applied:
        for migration in applied:
            print(f"applied {migration.label}")
    else:
        print("database is up to date")


if __name__ == "__main__":
    main()
