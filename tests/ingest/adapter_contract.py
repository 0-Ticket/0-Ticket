"""Shared contract tests every SIEM connector must pass (box 3, K3, K66).

Subclass ``AdapterContract`` in a ``Test*`` class and provide the fixtures below.
The direct adapter and the fake SIEM use it now; the Wazuh adapter will reuse it.
"""

import pytest

from soc.contracts import validate_contract
from soc.ingest.siem.base import FetchBatch, HealthStatus

BIG_LIMIT = 10_000


def walk(fetch):
    """Call ``fetch(cursor)`` from the start until nothing is left. Returns (items, last_cursor).

    A batch with only skipped records may move the cursor; a batch with nothing must not.
    """
    cursor, items = None, []
    for _ in range(BIG_LIMIT):
        batch = fetch(cursor)
        if not batch.items and not batch.skipped:
            assert batch.next_cursor == cursor, "an empty batch must not move the cursor"
            return items, cursor
        items.extend(batch.items)
        cursor = batch.next_cursor
    pytest.fail("connector never reached the end")


def dump(items):
    return [item.model_dump(mode="json") for item in items]


class AdapterContract:
    """Fixtures to provide:

    - ``connector``: a healthy connector holding at least 3 items
    - ``unhealthy_connector``: a connector whose SIEM cannot be reached
    - ``forbidden_text``: strings (secrets, log content) a health detail must never show
    """

    def test_fetch_returns_c2_batch(self, connector):
        batch = connector.fetch(None, BIG_LIMIT)
        assert isinstance(batch, FetchBatch)
        assert len(batch.items) >= 3
        for item in batch.items:
            validate_contract("SiemAlert", item.model_dump(mode="json"))

    def test_small_batches_walk_every_item_once(self, connector):
        everything = dump(connector.fetch(None, BIG_LIMIT).items)
        walked, _ = walk(lambda cursor: connector.fetch(cursor, 1))
        assert dump(walked) == everything

    def test_last_cursor_returns_nothing_new(self, connector):
        _, last = walk(lambda cursor: connector.fetch(cursor, 2))
        again = connector.fetch(last, BIG_LIMIT)
        assert again.items == ()
        assert again.next_cursor == last

    def test_limit_is_respected(self, connector):
        assert len(connector.fetch(None, 2).items) == 2

    def test_same_cursor_gives_same_result(self, connector):
        first = connector.fetch(None, 2)
        assert dump(connector.fetch(first.next_cursor, 2).items) == dump(
            connector.fetch(first.next_cursor, 2).items
        )

    def test_limit_below_one_is_rejected(self, connector):
        with pytest.raises(ValueError):
            connector.fetch(None, 0)

    def test_health_check_ok(self, connector):
        status = connector.health_check()
        assert isinstance(status, HealthStatus)
        assert status.ok is True

    def test_health_check_reports_failure_instead_of_raising(self, unhealthy_connector):
        status = unhealthy_connector.health_check()
        assert status.ok is False
        assert status.detail

    def test_health_detail_hides_secrets_and_log_content(
        self, connector, unhealthy_connector, forbidden_text
    ):
        for status in (connector.health_check(), unhealthy_connector.health_check()):
            for text in forbidden_text:
                assert text not in status.detail
