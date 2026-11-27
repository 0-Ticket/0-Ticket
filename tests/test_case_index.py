"""승인된 Case 색인의 DB 없는 부분(#391, D-084): 텍스트, 백오프, 가벼운 import, 임베더 공유.

샘플: tests/fixtures/case_index/cases.json(손으로 만든 Incident·Artifact·Case).
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from soc.case_index import index, source, text
from soc.contracts import validate_contract
from soc.contracts.alert import contract_data

SAMPLE = json.loads(
    (Path(__file__).parent / "fixtures" / "case_index" / "cases.json").read_text(encoding="utf-8")
)
CASES = {row["id"][-1]: row for row in SAMPLE["cases"]}
ARTIFACTS = {row["id"][-1]: row for row in SAMPLE["incident_artifacts"]}


def build(case: dict[str, Any], artifact: dict[str, Any] | None) -> str:
    return text.case_text(case["title"], case["summary"], artifact)


def test_fixture_rows_match_the_contracts() -> None:
    for table, name in (
        ("incidents", "incident"),
        ("incident_artifacts", "incident_artifact"),
        ("cases", "case"),
    ):
        for row in SAMPLE[table]:
            validate_contract(name, contract_data(name, row))


def test_text_is_labeled_lines_in_the_planned_order() -> None:
    assert build(CASES["1"], ARTIFACTS["2"]) == (
        "title: Web shell on example web server\n"
        "summary: Attacker uploaded a web shell through the upload form\n"
        "cause: Unrestricted file upload was abused\n"
        "impact: The web server executed attacker supplied code\n"
        "further_risk: The same upload path can drop more tools\n"
        "technique: Web Shell\n"
        "technique: Exploit Public-Facing Application"
    )


def test_text_leaves_out_timeline_evidence_ids_entity_values_and_technique_ids() -> None:
    result = build(CASES["1"], ARTIFACTS["2"])
    for forbidden in (
        "TIMELINE-MARKER",
        "evt_",
        "192.0.2.77",
        "T1505",
        "T1190",
        "analysis summary",
    ):
        assert forbidden not in result


def test_blank_and_missing_fields_drop_their_lines() -> None:
    assert build(CASES["2"], None) == "title: Suspicious login burst"
    blank = {"cause": "  ", "impact": "", "further_risk": None, "techniques": []}
    assert text.case_text("T", "  \n ", blank) == "title: T"


def test_whitespace_is_folded_inside_a_field() -> None:
    assert text.case_text("a \n  b\t c", None, None) == "title: a b c"


def test_each_field_and_the_technique_lines_are_capped() -> None:
    result = build(CASES["3"], ARTIFACTS["3"])
    lines = result.split("\n")
    cause = next(line for line in lines if line.startswith("cause: "))
    impact = next(line for line in lines if line.startswith("impact: "))
    assert len(cause) == len("cause: ") + text.MAX_FIELD_CHARS
    assert len(impact) == len("impact: ") + text.MAX_FIELD_CHARS
    techniques = [line for line in lines if line.startswith("technique: ")]
    assert techniques == [f"technique: Technique number {k}" for k in range(text.MAX_TECHNIQUES)]
    assert len(result) <= text.MAX_TEXT_CHARS


def test_total_length_is_capped() -> None:
    long = "가" * 5000
    artifact = {"cause": long, "impact": long, "further_risk": long, "techniques": []}
    result = text.case_text(long, long, artifact)
    assert len(result) == text.MAX_TEXT_CHARS


def test_limits_are_the_planned_draft_values() -> None:
    assert (text.MAX_FIELD_CHARS, text.MAX_TECHNIQUES, text.MAX_TEXT_CHARS) == (1000, 10, 4000)


@pytest.mark.parametrize(
    ("attempts", "seconds"),
    [(1, 30), (2, 60), (3, 120), (4, 240), (5, 480), (6, 600), (7, 600), (10_000, 600)],
)
def test_backoff_doubles_from_thirty_seconds_up_to_ten_minutes(attempts: int, seconds: int) -> None:
    assert index.backoff_seconds(attempts) == seconds


def test_point_id_is_the_case_id_without_its_prefix_and_maps_back() -> None:
    case_id = CASES["1"]["id"]
    assert source.point_id(case_id) == case_id.removeprefix("cas_") != case_id
    assert source.case_id_of(source.point_id(case_id)) == case_id
    with pytest.raises(ValueError):
        source.point_id("tkt_01a19f93-1391-7000-8000-000000000001")


def test_purpose_and_latest_artifact_query() -> None:
    assert source.PURPOSE == "confirmed_cases"
    query = source.LATEST_ARTIFACT_SQL.format(columns="cause")
    assert "FROM incident_artifacts" in query and "incident_reviews" not in query
    assert "ORDER BY analysis_round DESC LIMIT 1" in query


@pytest.mark.parametrize(
    "module",
    ["soc.case_index", "soc.case_index.source", "soc.case_index.outbox", "soc.case_index.text"],
)
def test_light_modules_do_not_pull_in_the_embedder_qdrant_or_l2(module: str) -> None:
    """승인 API와 #392 도구가 가져다 쓰는 모듈이 모델·Qdrant·L2 runtime을 끌어오지 않는다."""
    code = (
        f"import sys, {module}; "
        "bad = [m for m in ('onnxruntime', 'qdrant_client', 'huggingface_hub', 'tokenizers', "
        "'soc.store', 'soc.l2', 'soc.agent') if m in sys.modules]; "
        "sys.exit(','.join(bad) or 0)"
    )
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr or done.stdout


def test_worker_shares_the_branch_services_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    from soc.l2.branch import runtime
    from soc.store.config import EmbedderSettings, QdrantSettings, StoreSettings

    class Embedder:
        def __init__(self, settings: Any) -> None:
            self.settings = settings

    monkeypatch.setattr(runtime, "BgeM3Embedder", Embedder)
    monkeypatch.setattr(runtime, "VectorStore", lambda *args, **kwargs: "store")
    settings = StoreSettings(
        qdrant=QdrantSettings(url_env="QDRANT_URL"),
        embedder=EmbedderSettings(model_id="m", revision="r"),
    )
    runtime.get_service.cache_clear()
    try:
        assert index.get_embedder(settings) is runtime.get_service(settings).embedder
        assert index.get_embedder(settings) is index.get_embedder(settings)
    finally:
        runtime.get_service.cache_clear()


def test_build_worker_needs_the_database_url_and_has_the_executor_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = {
        "store": {
            "qdrant": {"url_env": "QDRANT_URL"},
            "embedder": {
                "model_id": "BAAI/bge-m3",
                "revision": "5617a9f61b028005a4858fdac845db406aefb181",
            },
        }
    }
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError):
        index.build_worker(config)
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-printed")
    worker = index.build_worker(config)
    assert (worker.stage, worker.name) == ("l2", "case_index")
    assert callable(worker.poll) and callable(worker.handle)


def test_executor_can_resolve_the_package_factory() -> None:
    from soc.agent.executor import resolve_factory

    assert callable(resolve_factory("soc.case_index:build_worker"))
