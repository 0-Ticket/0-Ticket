"""컬렉션 이름 파생, 가짜 임베더, 실제 BGE-M3 임베더(#257).

실제 모델을 쓰는 테스트는 embedder 마커로 나눈다. 기본 pytest에서 빠지고
`uv run pytest -m embedder`로만 돈다(첫 실행은 약 2.27GB를 내려받는다).
"""

import math
import pathlib

import pytest
from fake_embedder import FakeEmbedder

from soc.store.config import EmbedderSettings
from soc.store.embedder import (
    DIMENSION,
    MAX_TOKENS,
    BgeM3Embedder,
    Embedder,
    OnnxOutput,
    collection_name,
)

REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
SETTINGS = EmbedderSettings(model_id="BAAI/bge-m3", revision=REVISION)
# Qdrant 컬렉션 이름 한도
MAX_NAME_BYTES = 255


def test_collection_name_is_deterministic() -> None:
    assert collection_name("l2_tickets", SETTINGS) == collection_name("l2_tickets", SETTINGS)


def test_collection_name_shape_and_safe_characters() -> None:
    name = collection_name("l2_tickets", SETTINGS)

    purpose, slug, digest = name.split("__")
    assert (purpose, slug) == ("l2_tickets", "bge-m3")
    assert len(digest) == 16
    assert name.isascii()
    assert set(name) <= set("abcdefghijklmnopqrstuvwxyz0123456789_-")


def test_collection_name_stays_within_qdrant_limit() -> None:
    name = collection_name(
        "p" * 64, EmbedderSettings(model_id="org/" + "m" * 200, revision=REVISION)
    )

    assert len(name.encode()) <= MAX_NAME_BYTES


@pytest.mark.parametrize(
    "settings",
    [
        pytest.param(
            EmbedderSettings(model_id="BAAI/bge-m3-other", revision=REVISION), id="모델 ID"
        ),
        pytest.param(EmbedderSettings(model_id="BAAI/bge-m3", revision="b" * 40), id="revision"),
    ],
)
def test_collection_name_changes_with_model_or_revision(settings: EmbedderSettings) -> None:
    assert collection_name("l2_tickets", settings) != collection_name("l2_tickets", SETTINGS)


def test_collection_name_changes_with_onnx_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """digest에 ONNX 파일 이름도 들어간다."""
    before = collection_name("l2_tickets", SETTINGS)
    monkeypatch.setattr("soc.store.embedder.ONNX_FILE", "onnx/model_quantized.onnx")

    assert collection_name("l2_tickets", SETTINGS) != before


def test_collection_name_differs_by_purpose() -> None:
    assert collection_name("l2_tickets", SETTINGS) != collection_name("l3_cases", SETTINGS)


def test_same_model_slug_from_different_org_still_differs() -> None:
    """slug가 같아도 모델 ID 전체가 digest에 들어가 이름이 갈린다."""
    other = EmbedderSettings(model_id="other/bge-m3", revision=REVISION)

    assert collection_name("l2_tickets", other) != collection_name("l2_tickets", SETTINGS)


@pytest.mark.parametrize(
    "purpose",
    [
        pytest.param("", id="빈 값"),
        pytest.param("L2_tickets", id="대문자"),
        pytest.param("l2-tickets", id="붙임표"),
        pytest.param("l2 tickets", id="공백"),
        pytest.param("p" * 65, id="65자"),
        pytest.param("티켓", id="한글"),
    ],
)
def test_collection_name_rejects_bad_purpose(purpose: str) -> None:
    with pytest.raises(ValueError):
        collection_name(purpose, SETTINGS)


def test_fake_embedder_is_deterministic_and_small() -> None:
    embedder = FakeEmbedder()
    first = embedder.embed("SSH 로그인 실패가 반복됐다")

    assert embedder.dimension == 8
    assert len(first) == embedder.dimension
    assert first == FakeEmbedder().embed("SSH 로그인 실패가 반복됐다")
    assert math.isclose(math.sqrt(sum(v * v for v in first)), 1.0, abs_tol=1e-9)


def test_fake_embedder_separates_different_text() -> None:
    embedder = FakeEmbedder()

    assert embedder.embed("가") != embedder.embed("나")


def test_fake_embedder_fits_the_interface() -> None:
    assert isinstance(FakeEmbedder(), Embedder)


@pytest.mark.embedder
def test_real_embedder_output_name_and_shape() -> None:
    embedder = BgeM3Embedder(SETTINGS)

    output = embedder.output

    assert output.shape[-1] == DIMENSION
    assert len(output.shape) == (3 if output.takes_cls else 2)
    assert embedder.dimension == DIMENSION


@pytest.mark.embedder
def test_real_embedder_makes_unit_vector() -> None:
    vector = BgeM3Embedder(SETTINGS).embed("같은 계정으로 SSH 로그인 실패가 반복됐다")

    assert len(vector) == DIMENSION
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-5)


@pytest.mark.embedder
def test_real_embedder_is_deterministic() -> None:
    embedder = BgeM3Embedder(SETTINGS)
    text = "내부 호스트가 외부로 큰 파일을 올렸다"

    assert embedder.embed(text) == embedder.embed(text)


@pytest.mark.embedder
def test_real_embedder_separates_unrelated_text() -> None:
    embedder = BgeM3Embedder(SETTINGS)

    brute = embedder.embed("같은 계정으로 SSH 로그인 실패가 반복됐다")
    similar = embedder.embed("관리자 계정 로그인 실패가 계속됐다")
    other = embedder.embed("점심 메뉴를 고르는 회의를 열었다")

    close = sum(a * b for a, b in zip(brute, similar, strict=True))
    far = sum(a * b for a, b in zip(brute, other, strict=True))
    assert close > far


@pytest.mark.embedder
def test_tokenizer_truncates_to_max_tokens() -> None:
    """긴 입력은 ONNX에 넣기 전에 8192토큰으로 잘린다. 긴 입력을 실제 추론하지는 않는다."""
    embedder = BgeM3Embedder(SETTINGS)
    long_text = "로그인 실패 " * 20_000

    assert embedder.token_count(long_text) == MAX_TOKENS
    assert embedder.token_count("짧은 문장") <= MAX_TOKENS


def test_embedder_loads_the_model_once_even_when_threads_call_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """여러 단계 스레드가 첫 호출을 겹쳐도 모델을 한 번만 올린다(#313)."""
    import sys
    import threading
    import time
    import types

    sessions: list[object] = []

    class FakeSession:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            time.sleep(0.05)  # 다른 스레드가 끼어들 틈
            sessions.append(self)

    class FakeTokenizer:
        @staticmethod
        def from_file(_path: str) -> "FakeTokenizer":
            return FakeTokenizer()

        def enable_truncation(self, **_kwargs: object) -> None:
            pass

    modules = {
        "onnxruntime": types.SimpleNamespace(InferenceSession=FakeSession),
        "huggingface_hub": types.SimpleNamespace(hf_hub_download=lambda *a, **k: "x"),
        "tokenizers": types.SimpleNamespace(Tokenizer=FakeTokenizer),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(
        "soc.store.embedder._pick_output", lambda _s: OnnxOutput("o", (1, 1024), False)
    )

    embedder = BgeM3Embedder(
        EmbedderSettings(
            model_id="BAAI/bge-m3", revision="5617a9f61b028005a4858fdac845db406aefb181"
        )
    )
    start = threading.Barrier(6)

    def call() -> None:
        start.wait()
        assert embedder.dimension == DIMENSION

    threads = [threading.Thread(target=call) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(sessions) == 1


def test_model_files_are_downloaded_as_real_files_into_one_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: "pathlib.Path"
) -> None:
    """심링크 캐시로는 onnxruntime이 외부 데이터(model.onnx_data)를 거부한다(macOS, #313).

    세 파일을 같은 local_dir에 실제 파일로 받아야 한다. 폴더는 HF_HOME 아래라 설정 키가 없다.
    """
    import sys
    import types

    calls: list[dict[str, object]] = []

    def fake_download(repo: str, name: str, **kwargs: object) -> str:
        calls.append({"repo": repo, "name": name, **kwargs})
        return str(tmp_path / "wherever" / name)

    class FakeTokenizer:
        @staticmethod
        def from_file(_path: str) -> "FakeTokenizer":
            return FakeTokenizer()

        def enable_truncation(self, **_kwargs: object) -> None:
            pass

    modules = {
        "onnxruntime": types.SimpleNamespace(InferenceSession=lambda *a, **k: object()),
        "huggingface_hub": types.SimpleNamespace(hf_hub_download=fake_download),
        "tokenizers": types.SimpleNamespace(Tokenizer=FakeTokenizer),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(
        "soc.store.embedder._pick_output", lambda _s: OnnxOutput("o", (1, 1024), False)
    )
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))

    BgeM3Embedder(SETTINGS)._load()

    expected = str(tmp_path / "hf" / "soc-onnx" / "BAAI--bge-m3" / REVISION)
    assert [c["name"] for c in calls] == [
        "onnx/model.onnx",
        "onnx/model.onnx_data",
        "onnx/tokenizer.json",
    ]
    assert {c["local_dir"] for c in calls} == {expected}
    assert {c["revision"] for c in calls} == {REVISION}
