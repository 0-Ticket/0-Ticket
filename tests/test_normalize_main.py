"""정규화 CLI가 환경변수가 없을 때 종료 코드 2로 끝나는지 확인한다."""

import pytest

from soc.normalize.__main__ import main


def test_missing_write_database_url_exits_with_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert main() == 2
    assert "DATABASE_URL" in capsys.readouterr().err
