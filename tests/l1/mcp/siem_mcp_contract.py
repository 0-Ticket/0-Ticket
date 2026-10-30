"""Shared contract tests every SIEM MCP adapter must pass (boxes 28, 42, K18, K66).

Subclass ``SiemMcpAdapterContract`` in a ``Test*`` class and provide the fixtures
below. The fake adapter uses it now; the Wazuh adapter will reuse it. Adapters
answer with C2 content without source_record_id, and only ever read.
"""

from collections.abc import Mapping

import pytest

from soc.contracts import Entity, validate_contract
from soc.ingest.siem.base import HealthStatus
from soc.l1.mcp.siem.base import READ_ONLY_METHODS, SiemQuery, to_c2_records


class SiemMcpAdapterContract:
    """Fixtures to provide:

    - ``adapter``: a healthy adapter
    - ``unhealthy_adapter``: an adapter whose SIEM cannot be reached
    - ``forbidden_text``: strings (secrets, log content) a health detail must never show
    - ``sample_query``: a SiemQuery matching at least two of the adapter's records
    """

    def test_query_returns_c2_content_without_source_record_id(self, adapter, sample_query):
        records = adapter.query(sample_query)
        assert len(records) >= 2
        for record in records:
            assert isinstance(record, Mapping)
            assert "source_record_id" not in record

    def test_core_output_is_valid_c2_with_source_record_id(self, adapter, sample_query):
        for record in to_c2_records(adapter.query(sample_query)):
            assert record["source_record_id"].startswith("src_")
            validate_contract("SiemAlert", record)

    def test_records_match_the_requested_kind(self, adapter, sample_query):
        for record in adapter.query(sample_query):
            assert record["kind"] == sample_query.kind

    def test_records_stay_inside_the_requested_window(self, adapter, sample_query):
        wider = SiemQuery(
            entity=sample_query.entity,
            kind=sample_query.kind,
            start_at=sample_query.start_at - 86_400_000,
            end_at=sample_query.end_at + 86_400_000,
            limit=sample_query.limit,
        )
        assert len(adapter.query(wider)) >= len(adapter.query(sample_query))
        narrow = SiemQuery(
            entity=sample_query.entity,
            kind=sample_query.kind,
            start_at=sample_query.start_at,
            end_at=sample_query.start_at,
            limit=sample_query.limit,
        )
        assert len(adapter.query(narrow)) <= len(adapter.query(sample_query))

    def test_limit_is_respected(self, adapter, sample_query):
        one = SiemQuery(
            entity=sample_query.entity,
            kind=sample_query.kind,
            start_at=sample_query.start_at,
            end_at=sample_query.end_at,
            limit=1,
        )
        assert len(adapter.query(one)) == 1

    def test_same_query_gives_the_same_records(self, adapter, sample_query):
        assert adapter.query(sample_query) == adapter.query(sample_query)

    def test_unknown_entity_type_is_not_an_error(self, adapter, sample_query):
        unknown = SiemQuery(
            entity=Entity(type="not_a_registered_entity_type", value="x"),
            kind=sample_query.kind,
            start_at=sample_query.start_at,
            end_at=sample_query.end_at,
            limit=sample_query.limit,
        )
        assert adapter.query(unknown) == ()

    def test_adapter_exposes_read_only_methods_only(self, adapter):
        public = {
            name
            for name in dir(adapter)
            if not name.startswith("_") and callable(getattr(adapter, name))
        }
        assert public <= READ_ONLY_METHODS, "a SIEM MCP adapter may only read"

    def test_health_check_ok(self, adapter):
        status = adapter.health_check()
        assert isinstance(status, HealthStatus)
        assert status.ok is True

    def test_health_check_reports_failure_instead_of_raising(self, unhealthy_adapter):
        status = unhealthy_adapter.health_check()
        assert status.ok is False
        assert status.detail

    def test_health_detail_hides_secrets_and_log_content(
        self, adapter, unhealthy_adapter, forbidden_text
    ):
        for status in (adapter.health_check(), unhealthy_adapter.health_check()):
            for text in forbidden_text:
                assert text not in status.detail

    @pytest.mark.parametrize("limit", [0, -1])
    def test_limit_below_one_is_rejected(self, sample_query, limit):
        with pytest.raises(ValueError):
            SiemQuery(
                entity=sample_query.entity,
                kind=sample_query.kind,
                start_at=sample_query.start_at,
                end_at=sample_query.end_at,
                limit=limit,
            )

    def test_window_that_ends_before_it_starts_is_rejected(self, sample_query):
        with pytest.raises(ValueError):
            SiemQuery(
                entity=sample_query.entity,
                kind=sample_query.kind,
                start_at=sample_query.end_at + 1,
                end_at=sample_query.end_at,
                limit=sample_query.limit,
            )

    def test_unknown_kind_is_rejected(self, sample_query):
        with pytest.raises(ValueError):
            SiemQuery(
                entity=sample_query.entity,
                kind="incident",
                start_at=sample_query.start_at,
                end_at=sample_query.end_at,
                limit=sample_query.limit,
            )
