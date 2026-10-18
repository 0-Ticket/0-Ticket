"""The Alert/Event tables use only the migration numbers given to #50 (0010-0019)."""

from soc.db import discover_migrations

STORE_MIGRATIONS = {"create_source_records", "create_normalized_records"}


def test_store_migrations_use_only_their_number_range():
    found = {m.name: m.version for m in discover_migrations() if m.name in STORE_MIGRATIONS}
    assert set(found) == STORE_MIGRATIONS
    assert all(10 <= version <= 19 for version in found.values())
