"""수집 CLI는 설정 경고를 stderr에 남기고 멈추지 않는다(#340, D-067)."""

from pathlib import Path

import pytest

from soc.ingest import __main__ as cli
from soc.ingest.config import load_config

REPO_CONFIG = Path(__file__).resolve().parents[3] / "config"


def ingest_with_event_source() -> dict:
    """배포 설정에 이벤트 대상 하나를 더한 것.

    배포 설정은 이벤트를 수집하지 않지만(#382, D-081) CLI의 경고 경로는 그대로다.
    경고를 내는 대상을 테스트가 만들어 둔다.
    """
    ingest = load_config(REPO_CONFIG)["ingest"]
    ingest["sources"] = [
        *ingest["sources"],
        {"kind": "event", "key": "logs-nginx.access-*", "time_field": "@timestamp"},
    ]
    return ingest


def test_cli_prints_config_warnings_and_keeps_going(monkeypatch, capsys) -> None:
    ingest = ingest_with_event_source()
    ingest["sources"][1]["calss"] = 4002  # class 오타
    monkeypatch.setattr(cli, "load_config", lambda: {"ingest": ingest})
    monkeypatch.delenv("ELK_URL", raising=False)

    code = cli.main([])

    err = capsys.readouterr().err
    assert "경고:" in err and "'calss'" in err
    # 경고 뒤에 환경변수 검사까지 갔다 = 설정 경고로 멈추지 않았다
    assert code == 2 and "ELK_URL" in err


@pytest.mark.parametrize("value", [2004, 9999, "4002"])
def test_cli_warns_for_a_bad_class_without_stopping(monkeypatch, capsys, value) -> None:
    ingest = ingest_with_event_source()
    ingest["sources"][1]["class"] = value
    monkeypatch.setattr(cli, "load_config", lambda: {"ingest": ingest})
    monkeypatch.delenv("ELK_URL", raising=False)

    code = cli.main([])

    err = capsys.readouterr().err
    assert "경고:" in err and "Base Event(0)" in err
    assert code == 2 and "ELK_URL" in err
