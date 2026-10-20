"""Store migrations use only the numbers their issues were given.

#50 0010-0019, #59 0050-0059, #60 0060-0069, #69 0090-0099, #87 0094 (in the box 25 range).
"""

import pytest

from soc.db import discover_migrations

RANGES = {
    "create_source_records": (10, 19),
    "create_normalized_records": (10, 19),
    "create_normalize_state": (50, 59),
    "create_lookup_tables": (60, 69),
    "create_branch_results": (90, 99),
    "create_l1_decisions": (90, 99),
    "index_ticket_list": (90, 99),
    "create_branch_state": (90, 99),
    "create_alert_dedup_representatives": (94, 94),
}


@pytest.mark.parametrize("name", sorted(RANGES))
def test_store_migrations_use_only_their_number_range(name):
    found = {m.name: m.version for m in discover_migrations()}
    low, high = RANGES[name]
    assert low <= found[name] <= high
