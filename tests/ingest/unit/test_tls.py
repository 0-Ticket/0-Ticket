"""수집의 CA 인증서 경로 설정 [ingest] ca_cert_path(#264).

자체 서명 HTTPS ELK에 붙을 때 쓴다. 빈 값이면 지금처럼 httpx 기본 신뢰 저장소를 쓴다.
샘플 인증서는 tests/fixtures/tls/의 테스트용 공개 CA다(개인 키 없음).
"""

import ssl
from pathlib import Path
from typing import Any

import httpx
import pytest
from fake_elk import API_KEY, BASE_URL, make_settings

from soc.ingest import __main__ as main_module
from soc.ingest import elk
from soc.ingest.config import ConfigError, load_config, read_settings

TLS = Path(__file__).resolve().parents[2] / "fixtures" / "tls"
CA = TLS / "ca.pem"
NOT_A_CERT = TLS / "not_a_cert.pem"
REPO_CONFIG = Path(__file__).resolve().parents[3] / "config"


def ingest_with(**change: Any) -> dict[str, Any]:
    ingest = load_config(REPO_CONFIG)["ingest"]
    ingest.update(change)
    return ingest


def test_default_config_has_empty_ca_cert_path() -> None:
    assert load_config(REPO_CONFIG)["ingest"]["ca_cert_path"] == ""
    assert read_settings(ingest_with()).ca_cert_path == ""


def test_missing_key_is_empty() -> None:
    ingest = ingest_with()
    ingest.pop("ca_cert_path")
    assert read_settings(ingest).ca_cert_path == ""


def test_path_is_read_as_given() -> None:
    assert read_settings(ingest_with(ca_cert_path=str(CA))).ca_cert_path == str(CA)


@pytest.mark.parametrize("value", [1, True, None, ["a.pem"]])
def test_non_string_is_config_error(value: Any) -> None:
    with pytest.raises(ConfigError):
        read_settings(ingest_with(ca_cert_path=value))


def test_empty_path_keeps_default_verification() -> None:
    assert elk.tls_verify(make_settings()) is True


def test_ca_file_becomes_ssl_context() -> None:
    context = elk.tls_verify(make_settings(ca_cert_path=str(CA)))
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    subjects = [dict(item[0] for item in cert["subject"]) for cert in context.get_ca_certs()]
    assert {"commonName": "0-Ticket test CA"} in subjects


@pytest.mark.parametrize("path", [TLS / "missing.pem", NOT_A_CERT, TLS])
def test_unreadable_ca_file_is_config_error_without_path(path: Path) -> None:
    with pytest.raises(ConfigError) as caught:
        elk.tls_verify(make_settings(ca_cert_path=str(path)))
    assert str(TLS) not in str(caught.value)
    assert "ca_cert_path" in str(caught.value)


def test_make_client_passes_the_ca_context(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    real = httpx.Client

    def spy(*args: Any, **kwargs: Any) -> httpx.Client:
        seen.append(kwargs.get("verify"))
        return real(*args, **kwargs)

    monkeypatch.setattr(elk.httpx, "Client", spy)
    with elk.make_client(make_settings(ca_cert_path=str(CA)), BASE_URL, API_KEY):
        pass
    with elk.make_client(make_settings(), BASE_URL, API_KEY):
        pass
    assert isinstance(seen[0], ssl.SSLContext)
    assert seen[1] is True


def must_not_run(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("CA 파일을 읽지 못하면 연결하지 않는다")


@pytest.mark.parametrize("path", [TLS / "missing.pem", NOT_A_CERT])
def test_main_exits_2_before_connecting_when_ca_is_unreadable(
    monkeypatch: pytest.MonkeyPatch, path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ELK_URL", BASE_URL)
    monkeypatch.setenv("ELK_API_KEY", API_KEY)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake-user:DB-SECRET@db.example.com/soc")
    monkeypatch.setattr(
        main_module, "load_config", lambda: {"ingest": ingest_with(ca_cert_path=str(path))}
    )
    monkeypatch.setattr(main_module.psycopg, "connect", must_not_run)
    monkeypatch.setattr(main_module.elk, "make_client", must_not_run)
    assert main_module.main() == 2
    err = capsys.readouterr().err
    assert "ca_cert_path" in err
    assert str(TLS) not in err and API_KEY not in err
