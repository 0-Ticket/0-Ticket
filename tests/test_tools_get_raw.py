"""발급한 근거의 원문을 읽는 도구 get_raw(#382). DB 없이 스펙 모양과 허용 목록만 본다.

실제 읽기는 tests/test_tools_db.py의 db 마커 테스트가 본다. 이벤트를 정규화하지 않으므로
events 행은 class 0 포인터이고 원문은 raw_records.original_text에 있다. 모델이 그것을 읽는
수단이 이 도구다.
"""

from pathlib import Path
from typing import Any

from soc.agent.config import load_config
from soc.agent.types import TASK_NAMES
from soc.tools import default_registry

REPO = Path(__file__).resolve().parents[1]
NAME = "get_raw"


def shipped() -> dict[str, Any]:
    return load_config(REPO / "config")["tools"]["allowed"]


def spec() -> Any:
    found = default_registry().get(NAME)
    assert found is not None, "운영 레지스트리에 get_raw가 없다"
    return found


def test_it_is_a_records_tool_whose_id_enters_the_ledger() -> None:
    got = spec()
    assert got.bundle == "internal"
    assert got.result_kind == "records"
    assert got.id_fields == ("id",)


def test_the_id_argument_takes_raw_alert_and_event_ids() -> None:
    import re

    (arg,) = spec().args
    assert arg.name == "id" and arg.required
    pattern = re.compile(arg.pattern)
    uuid7 = "01a19f93-1150-7000-8000-000000000001"
    for prefix in ("raw", "alt", "evt"):
        assert pattern.fullmatch(f"{prefix}_{uuid7}"), prefix
    # 다른 접두사와 모양이 틀린 값은 받지 않는다
    for bad in (f"tkt_{uuid7}", f"inc_{uuid7}", "raw_1", f"raw_{uuid7}\n"):
        assert not pattern.fullmatch(bad), bad


def test_the_description_says_the_original_is_data_not_instructions() -> None:
    # 밖에서 온 문자열이다(docs/security.md). 프롬프트가 아니라 도구 설명에도 적는다
    text = spec().description
    assert "데이터" in text and "지시" in text


def test_tasks_that_cite_evidence_can_read_the_original() -> None:
    allowed = shipped()
    for task in (
        "l1_alert_triage",
        "l1_ticket_judgment",
        "l2_investigate",
        "l3_hypothesize",
        "l3_verify",
    ):
        assert NAME in allowed[task], task


def test_classify_and_report_cannot_read_the_original() -> None:
    # 발급할 다음 태스크가 없는 두 태스크다(D-084). 분류는 그래프 후보와 모델 판단만 한다
    allowed = shipped()
    for task in ("l2_classify", "l2_report"):
        assert NAME not in allowed[task], task


def test_every_task_key_is_known() -> None:
    assert set(shipped()) == set(TASK_NAMES)


def test_the_reader_role_is_granted_only_the_columns_the_tool_reads() -> None:
    sql = (REPO / "src/soc/db/migrations/0308_agent_reader_raw_records.sql").read_text(
        encoding="utf-8"
    )
    assert "GRANT SELECT (id, kind, fetched_at, original_text) ON raw_records" in sql
    # siem_ref에는 인덱스 이름이 들어 있다. 모델에게 보이지 않는 것이 설계의 전제다
    assert "siem_ref" not in sql.split("GRANT")[1]
    assert "siem_profile" not in sql.split("GRANT")[1]
