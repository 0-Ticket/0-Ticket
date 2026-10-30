"""Shared contract tests every SIEM connector must pass (SIEM connector, K3, K66).

Subclass ``AdapterContract`` in a ``Test*`` class and provide the fixtures below.
The direct adapter and the fake SIEM use it now; the Wazuh adapter will reuse it.
Adapters return C2 content without source_record_id; the core entry assigns it.
"""

from collections.abc import Mapping

import pytest

from soc.contracts import SiemAlert, validate_contract
from soc.ingest.connector import SiemIngest
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
    return [item.model_dump(mode="json") if isinstance(item, SiemAlert) else item for item in items]


class AdapterContract:
    """Fixtures to provide:

    - ``connector``: a healthy connector holding at least 3 items
    - ``unhealthy_connector``: a connector whose SIEM cannot be reached
    - ``forbidden_text``: strings (secrets, log content) a health detail must never show
    """

    def test_fetch_returns_c2_content_without_source_record_id(self, connector):
        batch = connector.fetch(None, BIG_LIMIT)
        assert isinstance(batch, FetchBatch)
        assert len(batch.items) >= 3
        for item in batch.items:
            assert isinstance(item, Mapping)
            assert "source_record_id" not in item

    def test_core_output_is_valid_c2_with_source_record_id(self, connector):
        for item in SiemIngest(connector, BIG_LIMIT).fetch(None).items:
            assert item.source_record_id.startswith("src_")
            validate_contract("SiemAlert", item.model_dump(mode="json"))

    def test_same_cursor_gives_same_source_record_ids(self, connector):
        ingest = SiemIngest(connector, 2)
        cursor = ingest.fetch(None).next_cursor
        first = [item.source_record_id for item in ingest.fetch(cursor).items]
        assert first
        assert first == [item.source_record_id for item in ingest.fetch(cursor).items]

    def test_different_items_get_different_source_record_ids(self, connector):
        items, _ = walk(SiemIngest(connector, 2).fetch)
        assert len({item.source_record_id for item in items}) == len(items)

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
