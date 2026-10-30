"""elastic connector (box 3, #99): ES _search -> C2, against a fake ES, never a real one."""

import base64
import copy
import json
import logging
from urllib.parse import unquote

import pytest
from adapter_contract import AdapterContract, walk
from fake_elasticsearch import (
    ALERT_INDEX,
    API_KEY,
    EVENT_INDEX,
    FakeElasticsearch,
    load_hits,
    unreachable_url,
)

from soc.config import ConfigError, MissingSecretError, load_config
from soc.ingest.connector import SiemIngest, open_connector, to_c2
from soc.ingest.siem import SIEM_CONNECTORS
from soc.ingest.siem.base import InvalidCursorError
from soc.ingest.siem.elastic import (
    MUTABLE_ALERT_FIELDS,
    ElasticError,
    create_elastic,
    hit_to_c2,
)

ENV = {"SIEM_TOKEN": API_KEY}
BIG = 10_000
ATTACKER = "198.51.100.23"
LOG_TEXT = "UNION SELECT"


def siem_settings(base_url: str):
    siem = load_config(environ={}).siem
    return siem.model_copy(update={"adapter": "elastic", "base_url": base_url})


def lab_indices(extra_events=()):
    return {
        ALERT_INDEX: load_hits("alert_hits.json"),
        EVENT_INDEX: [*extra_events, *load_hits("event_hits.json")],
    }


def ids(items):
    return [item["raw_ids"][0].rsplit("_", 1)[1] for item in items]


@pytest.fixture
def fake():
    with FakeElasticsearch(lab_indices()) as server:
        yield server


@pytest.fixture
def elastic(fake):
    return create_elastic(siem_settings(fake.url), ENV)


class TestElasticContract(AdapterContract):
    @pytest.fixture
    def connector(self, elastic):
        return elastic

    @pytest.fixture
    def unhealthy_connector(self):
        return create_elastic(siem_settings(unreachable_url()), ENV)

    @pytest.fixture
    def forbidden_text(self):
        return [API_KEY, ATTACKER, LOG_TEXT]


def test_alerts_come_first_then_events_as_c2(elastic):
    items = elastic.fetch(None, BIG).items
    assert [item["kind"] for item in items] == ["alert"] * 3 + ["event"] * 5
    assert {item["mapping_profile"] for item in items[:3]} == {"elastic_security_alert"}
    assert {item["mapping_profile"] for item in items[3:]} == {"elastic_access_event"}
    assert items[0]["raw_ids"] == ["raw_es_.internal.alerts-security.alerts-default-000001_al-1"]
    assert items[3]["raw_ids"] == ["raw_es_.ds-logs-generic-default-2026.10.21-000001_ev-1"]


def _keys(view):
    if isinstance(view, dict):
        for key, value in view.items():
            yield key
            yield from _keys(value)
    elif isinstance(view, list):
        for value in view:
            yield from _keys(value)


def test_dotted_and_nested_keys_give_the_same_shape(elastic):
    items = {ids([item])[0]: item["fields"] for item in elastic.fetch(None, BIG).items}
    assert not [key for fields in items.values() for key in _keys(fields) if "." in key]
    # al-3 and ev-4 carry source.address as a dotted key, the others nested.
    assert items["al-3"]["source"] == {"address": "192.0.2.77"}
    assert items["al-3"]["url"] == {"original": "/#/search?q=<script>alert(1)</script>"}
    assert items["ev-4"]["source"] == {"address": "192.0.2.50"}
    assert items["al-1"]["kibana"]["alert"]["rule"]["rule_id"] == "a2a-web-attack-juice-shop"
    # Lists of objects are expanded too.
    assert items["al-1"]["kibana"]["alert"]["ancestors"][0]["id"] == "ev-2"


def test_mutable_alert_fields_are_left_out_and_asked_to_be_excluded(fake, elastic):
    for item in elastic.fetch(None, BIG).items[:3]:
        alert = item["fields"]["kibana"]["alert"]
        assert "workflow_status" not in alert
        assert "status" not in alert
        assert "last_detected" not in alert
    alert_bodies = [r.body for r in fake.requests if unquote(r.path) == f"/{ALERT_INDEX}/_search"]
    assert alert_bodies
    for body in alert_bodies:
        assert body["_source"] == {"excludes": list(MUTABLE_ALERT_FIELDS)}


def test_kibana_status_changes_do_not_change_the_source_record_id():
    hit = load_hits("alert_hits.json")[0]
    changed = copy.deepcopy(hit)
    changed["_source"].update(
        {
            "kibana.alert.workflow_status": "acknowledged",
            "kibana.alert.workflow_user": "analyst",
            "kibana.alert.status": "recovered",
            "kibana.alert.last_detected": "2026-10-21T02:00:00.000Z",
            "kibana.alert.updated_by": {"user": {"id": "u1", "name": "analyst"}},
        }
    )
    first = to_c2(hit_to_c2(hit, "alert", "elastic_security_alert"))
    second = to_c2(hit_to_c2(changed, "alert", "elastic_security_alert"))
    assert first.source_record_id == second.source_record_id


def test_bad_hits_are_counted_as_skipped_without_logging_content(caplog):
    caplog.set_level(logging.DEBUG)
    with FakeElasticsearch(lab_indices(extra_events=load_hits("bad_hits.json"))) as fake:
        batch = create_elastic(siem_settings(fake.url), ENV).fetch(None, BIG)
    assert batch.skipped == 2
    assert len(batch.items) == 8
    for text in ("192.0.2.90", "192.0.2.91", "'an'", "bad-array", "bad-conflict"):
        assert text not in caplog.text
    assert "skipped 2" in caplog.text.lower()


def test_skipped_hits_still_move_the_cursor():
    bad = load_hits("bad_hits.json")
    with FakeElasticsearch({ALERT_INDEX: [], EVENT_INDEX: bad}) as fake:
        connector = create_elastic(siem_settings(fake.url), ENV)
        first = connector.fetch(None, 1)
        assert (first.items, first.skipped) == ((), 1)
        assert first.next_cursor is not None
        second = connector.fetch(first.next_cursor, 5)
        assert (second.items, second.skipped) == ((), 1)
        assert connector.fetch(second.next_cursor, 5).next_cursor == second.next_cursor


@pytest.mark.parametrize("limit", [1, 2, 3, 4, 5])
def test_same_second_events_are_not_lost_or_repeated_across_batches(elastic, limit):
    walked, _ = walk(lambda cursor: elastic.fetch(cursor, limit))
    assert ids(walked) == ["al-1", "al-2", "al-3", "ev-1", "ev-2", "ev-3", "ev-4", "ev-5"]


def test_a_batch_that_ends_inside_one_second_resumes_inside_it(fake, elastic):
    # 3 alerts + ev-1 + ev-2; ev-3 has the same @timestamp as ev-2.
    first = elastic.fetch(None, 5)
    assert ids(first.items)[-1] == "ev-2"
    second = elastic.fetch(first.next_cursor, 1)
    assert ids(second.items) == ["ev-3"]
    event_bodies = [r.body for r in fake.requests if unquote(r.path) == f"/{EVENT_INDEX}/_search"]
    must_not = event_bodies[-1]["query"]["bool"]["must_not"]
    assert must_not == [{"ids": {"values": ["ev-2"]}}]


def test_new_documents_after_the_last_cursor_are_fetched(fake, elastic):
    _, last = walk(lambda cursor: elastic.fetch(cursor, 3))
    newcomer = copy.deepcopy(load_hits("event_hits.json")[4])
    newcomer["_id"] = "ev-6"  # same @timestamp as the last event read
    later = copy.deepcopy(newcomer)
    later["_id"] = "ev-7"
    later["_source"]["@timestamp"] = "2026-10-21T01:05:00.000Z"
    fake.indices[EVENT_INDEX].extend([newcomer, later])
    assert ids(elastic.fetch(last, BIG).items) == ["ev-6", "ev-7"]


def test_sort_is_on_timestamp_only_never_on_id(fake, elastic):
    walk(lambda cursor: elastic.fetch(cursor, 2))
    sorts = [r.body["sort"] for r in fake.requests if r.body and "sort" in r.body]
    assert sorts
    for sort in sorts:
        assert [next(iter(entry)) for entry in sort] == ["@timestamp"]


def test_only_search_requests_reach_elasticsearch(fake, elastic):
    walk(lambda cursor: elastic.fetch(cursor, 2))
    elastic.health_check()
    allowed = {f"/{ALERT_INDEX}/_search", f"/{EVENT_INDEX}/_search"}
    assert fake.requests
    for request in fake.requests:
        assert request.method in {"GET", "POST"}
        assert unquote(request.path) in allowed


def test_api_key_is_sent_as_apikey_header_and_never_logged(fake, elastic, caplog):
    caplog.set_level(logging.DEBUG)
    elastic.fetch(None, BIG)
    assert {r.authorization for r in fake.requests} == {f"ApiKey {API_KEY}"}
    fake.status_override = 401
    with pytest.raises(ElasticError) as error:
        elastic.fetch(None, BIG)
    assert "401" in str(error.value)
    assert API_KEY not in str(error.value)
    assert API_KEY not in caplog.text


def test_error_message_holds_the_status_but_not_the_answer(fake, elastic):
    fake.status_override = 500
    with pytest.raises(ElasticError) as error:
        elastic.fetch(None, BIG)
    assert "500" in str(error.value)
    assert "forced" not in str(error.value)


def test_health_check_names_the_index_on_403(fake, elastic):
    fake.status_override = 403
    status = elastic.health_check()
    assert status.ok is False
    assert "403" in status.detail and "alert index" in status.detail


def test_health_check_uses_size_zero_searches(fake, elastic):
    assert elastic.health_check().ok is True
    assert [(r.method, r.query.get("size")) for r in fake.requests] == [("GET", ["0"])] * 2


def _cursor(data) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "not-a-cursor",
        "0:0:0",
        _cursor({"v": 99, "alert": None, "event": None}),
        _cursor({"v": 1, "alert": {"t": "x", "ids": []}, "event": None}),
        _cursor({"v": 1, "alert": {"t": 1, "ids": [1]}, "event": None}),
        _cursor({"v": 1, "alert": None}),
        _cursor([1, 2]),
    ],
)
def test_invalid_cursor_is_rejected(elastic, cursor):
    with pytest.raises(InvalidCursorError):
        elastic.fetch(cursor, 1)


def test_missing_api_key_fails_at_start():
    with pytest.raises(MissingSecretError):
        create_elastic(siem_settings("http://127.0.0.1:9200"), {})


@pytest.mark.parametrize(
    "base_url", ["", "localhost:9200", "http://user:pw@localhost:9200", "http://localhost:9200?x=1"]
)
def test_bad_base_url_is_a_config_error(base_url):
    with pytest.raises(ConfigError) as error:
        create_elastic(siem_settings(base_url), ENV)
    assert "pw" not in str(error.value)


def _org_file(tmp_path, body: str):
    path = tmp_path / "org.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_index_defaults_are_in_the_default_settings():
    elastic = load_config(environ={}).siem.elastic
    assert (elastic.alert_index, elastic.event_index) == (ALERT_INDEX, EVENT_INDEX)


def test_elastic_source_selectors_must_be_nonempty(tmp_path):
    org = _org_file(tmp_path, '[siem.elastic]\nalert_tool = ""\n')
    with pytest.raises(ConfigError, match="alert_tool"):
        load_config(org, environ={})


@pytest.mark.parametrize(
    "name",
    ["", "logs-*/_delete_by_query", "a,b", "a b", "-logs-*", "_all", "+x", "a?b", "a#b", 'a"b'],
)
def test_index_name_with_path_characters_is_rejected(tmp_path, name):
    org = _org_file(tmp_path, f"[siem.elastic]\nevent_index = {json.dumps(name)}\n")
    with pytest.raises(ConfigError, match="event_index"):
        load_config(org, environ={})


def test_elastic_is_chosen_by_setting_only(fake, tmp_path):
    factory = SIEM_CONNECTORS.get("elastic")
    assert factory.factory is create_elastic
    assert factory.mapping_selections(siem_settings(fake.url))
    org = _org_file(tmp_path, f'[siem]\nadapter = "elastic"\nbase_url = "{fake.url}"\n')
    ingest = open_connector(load_config(org, environ={}), ENV)
    assert isinstance(ingest, SiemIngest)
    assert len(ingest.fetch(None).items) == 8


def test_unmapped_elastic_selector_fails_before_connector_factory():
    base = load_config(environ={})
    elastic = base.siem.elastic.model_copy(update={"alert_tool": "unsupported_tool"})
    siem = base.siem.model_copy(update={"adapter": "elastic", "elastic": elastic})
    settings = base.model_copy(update={"siem": siem})

    with pytest.raises(ConfigError, match="no mapping profile"):
        open_connector(settings, environ=ENV)
