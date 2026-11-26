"""정규화 CLI가 환경변수가 없을 때 종료 코드 2로 끝나는지 확인한다."""

import pytest

from soc.normalize.__main__ import main
from soc.normalize.retry import main as retry_main


def test_missing_write_database_url_exits_with_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert main() == 2
    assert "DATABASE_URL" in capsys.readouterr().err


def test_retry_command_requires_write_database_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert retry_main() == 2
    assert "DATABASE_URL" in capsys.readouterr().err


def test_reprocess_command_requires_write_database_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert main(["reprocess", "--dry-run"]) == 2
    assert "DATABASE_URL" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["reprocess", "--limit", "0"],
        ["reprocess", "--since", "x"],
        ["reprocess", "--kind", "log"],
        ["reprocess", "--kind", "event", "--source", "suricata"],  # --source는 알럿 전용
    ],
)
def test_reprocess_command_rejects_bad_options(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(argv)

    assert stopped.value.code == 2


def test_reprocess_kind_event_without_source_is_rejected() -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["reprocess", "--kind", "event", "--dry-run"])

    assert stopped.value.code == 2
