"""Store migrations use only the numbers their issues were given.

#50 0010-0019, #59 0050-0059, #60 0060-0069.
"""

import pytest

from soc.db import discover_migrations

RANGES = {
    "create_source_records": (10, 19),
    "create_normalized_records": (10, 19),
    "create_normalize_state": (50, 59),
    "create_lookup_tables": (60, 69),
}


@pytest.mark.parametrize("name", sorted(RANGES))
def test_store_migrations_use_only_their_number_range(name):
    found = {m.name: m.version for m in discover_migrations()}
    low, high = RANGES[name]
    assert low <= found[name] <= high
