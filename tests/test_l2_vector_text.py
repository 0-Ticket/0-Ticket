"""손으로 만든 같은 사건·다른 사건의 분류 임베딩 텍스트."""

import json
from pathlib import Path
from types import SimpleNamespace

from soc.l2.branch.embed import embedding_text

FIXTURE = Path(__file__).parent / "fixtures" / "l2" / "vector_cases.json"


def test_branch_text_keeps_behavior_and_roles_without_model_reasons() -> None:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    texts = {case["name"]: embedding_text(SimpleNamespace(hunt=None, **case)) for case in cases}

    assert "cmd=id" in texts["same_webshell"]
    assert "cmd=pwd" in texts["same_webshell_followup"]
    assert "UNION SELECT" in texts["different_sqli_same_source"]
    assert "role=src" in texts["same_webshell"]
    assert "web-rule" in texts["same_webshell"]
    assert texts["same_webshell"] != texts["different_sqli_same_source"]
    assert all("판정 이유" not in text and "모델 이유" not in text for text in texts.values())


def test_branch_text_limits_untrusted_summaries() -> None:
    case = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"][0]
    case["events"] = [{"message": "X" * 100_000}]

    text = embedding_text(SimpleNamespace(hunt=None, **case))

    assert len(text) <= 2048
    assert "X" * 1000 not in text
