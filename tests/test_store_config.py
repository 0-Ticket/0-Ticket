"""[store] 설정 로더와 Qdrant 주소 환경변수 검사(#257)."""

from pathlib import Path

import pytest

from soc.store import config as store_config
from soc.store.config import ConfigError, QdrantSettings, load_config, read_settings
from soc.store.qdrant import StoreError, create_client

REVISION = "5617a9f61b028005a4858fdac845db406aefb181"


def _table(**over: object) -> dict[str, object]:
    """검사를 통과하는 [store] 표에 일부만 바꿔 돌려준다."""
    store: dict[str, object] = {
        "qdrant": {"url_env": "QDRANT_URL"},
        "embedder": {"model_id": "BAAI/bge-m3", "revision": REVISION},
    }
    store.update(over)
    return store


def test_default_config_has_store_tables(default_config_dir: Path) -> None:
    settings = read_settings(load_config(default_config_dir)["store"])

    assert settings.qdrant.url_env == "QDRANT_URL"
    assert settings.embedder.model_id == "BAAI/bge-m3"
    assert settings.embedder.revision == REVISION


def test_local_toml_overrides_default(default_config_dir: Path) -> None:
    (default_config_dir / "local.toml").write_text(
        '[store.embedder]\nrevision = "' + "a" * 40 + '"\n', encoding="utf-8"
    )

    settings = read_settings(load_config(default_config_dir)["store"])

    # 덮어쓴 값만 바뀌고 같은 표의 다른 값은 기본값이 남는다
    assert settings.embedder.revision == "a" * 40
    assert settings.embedder.model_id == "BAAI/bge-m3"


def test_repo_config_loads_without_qdrant_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """QDRANT_URL이 없어도 설정을 읽을 수 있다(기본 pytest, CI check job)."""
    monkeypatch.delenv("QDRANT_URL", raising=False)

    settings = read_settings(load_config()["store"])

    assert settings.qdrant.url_env == "QDRANT_URL"


def test_load_config_without_store_table_is_empty(tmp_path: Path) -> None:
    (tmp_path / "default.toml").write_text('[llm]\nmodel = ""\n', encoding="utf-8")

    assert load_config(tmp_path) == {"store": {}}


def test_config_dir_points_at_repo_config() -> None:
    assert (store_config.CONFIG_DIR / "default.toml").exists()


@pytest.mark.parametrize(
    "store",
    [
        pytest.param({}, id="표 없음"),
        pytest.param(_table(qdrant={}), id="url_env 없음"),
        pytest.param(_table(qdrant={"url_env": ""}), id="url_env 빈 값"),
        pytest.param(_table(qdrant={"url_env": "2BAD"}), id="숫자로 시작하는 환경변수 이름"),
        pytest.param(_table(qdrant={"url_env": "QDRANT URL"}), id="공백이 있는 환경변수 이름"),
        pytest.param(_table(qdrant={"url_env": "QDRANT-URL"}), id="붙임표가 있는 환경변수 이름"),
        pytest.param(_table(qdrant={"url_env": "http://localhost:6333"}), id="이름 자리에 주소"),
        pytest.param(_table(embedder={"revision": REVISION}), id="model_id 없음"),
        pytest.param(_table(embedder={"model_id": "", "revision": REVISION}), id="model_id 빈 값"),
        pytest.param(_table(embedder={"model_id": "BAAI/bge-m3"}), id="revision 없음"),
        pytest.param(
            _table(embedder={"model_id": "BAAI/bge-m3", "revision": "main"}),
            id="revision이 커밋 해시가 아님",
        ),
        pytest.param(
            _table(embedder={"model_id": "BAAI/bge-m3", "revision": REVISION.upper()}),
            id="revision 대문자",
        ),
        pytest.param(
            _table(embedder={"model_id": "BAAI/bge-m3", "revision": REVISION[:39]}),
            id="revision 39자",
        ),
        pytest.param(
            _table(embedder={"model_id": "BAAI/bge-m3", "revision": REVISION + "0"}),
            id="revision 41자",
        ),
        pytest.param(_table(qdrant={"url_env": 1}), id="url_env가 문자열이 아님"),
        pytest.param(_table(embedder="bge"), id="embedder가 표가 아님"),
    ],
)
def test_read_settings_rejects_bad_values(store: dict[str, object]) -> None:
    with pytest.raises(ConfigError):
        read_settings(store)


def test_read_settings_does_not_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """설정을 읽을 때는 환경변수 값을 보지 않는다. 값이 틀려도 통과해야 한다."""
    monkeypatch.setenv("QDRANT_URL", "엉뚱한 값")

    assert read_settings(_table()).qdrant.url_env == "QDRANT_URL"


def test_create_client_without_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QDRANT_URL", raising=False)

    with pytest.raises(StoreError) as caught:
        create_client(QdrantSettings(url_env="QDRANT_URL"))

    assert "QDRANT_URL" in str(caught.value)


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("   ", id="공백만"),
        pytest.param("localhost:6333", id="scheme 없음"),
        pytest.param("ftp://localhost:6333", id="http가 아닌 scheme"),
        pytest.param("file:///etc/passwd", id="파일 주소"),
        pytest.param("http://", id="호스트 없음"),
    ],
)
def test_create_client_rejects_bad_url(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QDRANT_URL", url)

    with pytest.raises(StoreError):
        create_client(QdrantSettings(url_env="QDRANT_URL"))


def test_client_error_does_not_leak_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """오류에는 환경변수 이름만 남고 주소 값은 들어가지 않는다."""
    secret = "ftp://soc-reader:s3cret@vector.example.invalid:6333"
    monkeypatch.setenv("QDRANT_URL", secret)

    with pytest.raises(StoreError) as caught:
        create_client(QdrantSettings(url_env="QDRANT_URL"))

    message = str(caught.value)
    assert "QDRANT_URL" in message
    for part in (secret, "s3cret", "vector.example.invalid", "6333"):
        assert part not in message
