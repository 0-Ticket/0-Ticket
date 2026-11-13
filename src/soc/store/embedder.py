"""임베딩 계층과 컬렉션 이름 파생(#257, 임베딩 모델 D-031, 실행 라이브러리 D-044).

BGE-M3 dense 표현을 로컬 ONNX로 뽑는다. sparse·multi-vector·batch는 만들지 않는다.
모델 파일은 Hugging Face 기본 캐시에 받는다(별도 캐시 경로 설정을 두지 않는다). 첫 실행은
onnx/model.onnx_data 약 2.27GB를 내려받는다.
"""

import hashlib
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np

from soc.store.config import EmbedderSettings

# 쓰는 ONNX 파일. 설정으로 받지 않고 코드에 고정한다. 외부 데이터(model.onnx_data)와
# tokenizer도 같은 revision에서 받는다.
ONNX_FILE = "onnx/model.onnx"
ONNX_DATA_FILE = "onnx/model.onnx_data"
TOKENIZER_FILE = "onnx/tokenizer.json"
# 모델이 받는 토큰 수 상한. 특수 토큰을 포함해 이 길이로 자른다.
MAX_TOKENS = 8192
# 기본 벡터 차원(D-031). 모델 출력이 이 값이 아니면 멈춘다.
DIMENSION = 1024

# 컬렉션 이름에 쓰는 용도. 호출자가 코드 상수로 준다.
_PURPOSE = re.compile(r"[a-z0-9_]{1,64}")
_UNSAFE_SLUG = re.compile(r"[^a-z0-9_-]")


@runtime_checkable
class Embedder(Protocol):
    """벡터 저장소가 쓰는 최소 인터페이스. 가짜 임베더도 이 모양이면 된다."""

    @property
    def dimension(self) -> int:
        """만드는 벡터의 차원. 컬렉션을 만들 때 쓴다."""

    def embed(self, text: str) -> list[float]:
        """문장 하나를 L2 정규화된 dense 벡터로 바꾼다."""


@dataclass(frozen=True)
class OnnxOutput:
    """고른 ONNX 출력. 개발 기록과 embedder 테스트가 확인한다.

    필드:
        name: 출력 이름.
        shape: 모델이 알려 주는 출력 shape. 동적 차원은 문자열이다.
        takes_cls: hidden state라서 [:, 0, :]를 CLS로 쓰는지. pooled 출력이면 False다.
    """

    name: str
    shape: tuple[Any, ...]
    takes_cls: bool


def collection_name(purpose: str, settings: EmbedderSettings) -> str:
    """컬렉션 이름을 용도·모델·ONNX 파일에서 만든다.

    모양은 `<purpose>__<model-slug>__<digest>`다. 같은 입력은 같은 이름을 만들고, 모델 ID·
    revision·ONNX 파일 이름 중 하나만 달라도 다른 이름이 된다. 결과는 ASCII 안전 문자만
    쓰고 Qdrant의 255바이트 한도 안이다(최대 148자).

    인자:
        purpose: 용도. [a-z0-9_] 1~64자여야 한다.
        settings: 모델 ID와 revision.

    발생:
        ValueError: purpose의 모양이 맞지 않을 때(부르는 코드의 잘못이다).
    """
    if not _PURPOSE.fullmatch(purpose):
        raise ValueError("purpose는 [a-z0-9_] 1~64자여야 한다")
    slug = _UNSAFE_SLUG.sub("-", settings.model_id.rsplit("/", 1)[-1].lower())[:64]
    seed = "\0".join((settings.model_id, settings.revision, ONNX_FILE))
    digest = hashlib.sha256(seed.encode()).hexdigest()[:16]
    return f"{purpose}__{slug}__{digest}"


class BgeM3Embedder:
    """고정 revision의 BGE-M3 ONNX로 dense 벡터를 만든다.

    모델 파일 내려받기와 ONNX 세션 만들기는 dimension·embed()를 처음 쓸 때 한 번만 한다.
    설정을 읽는 쪽이 모델을 내려받지 않게 하기 위해서다.
    """

    def __init__(self, settings: EmbedderSettings) -> None:
        """인자 settings는 검사를 통과한 [store.embedder] 값이다."""
        self._settings = settings
        self._session: Any = None
        self._tokenizer: Any = None
        self._output: OnnxOutput | None = None
        # 실행기의 여러 단계 스레드가 첫 호출에서 모델을 두 번 올리지 않게 한다(#313)
        self._load_lock = threading.Lock()

    @property
    def dimension(self) -> int:
        """모델 출력 차원. 1024가 아니면 _load()가 멈춘다."""
        self._load()
        return DIMENSION

    @property
    def output(self) -> OnnxOutput:
        """고른 ONNX 출력 이름·shape와 CLS 사용 여부."""
        self._load()
        assert self._output is not None
        return self._output

    def token_count(self, text: str) -> int:
        """ONNX에 넣기 직전의 토큰 수. 8192 절단을 확인할 때 쓴다."""
        self._load()
        return len(self._tokenizer.encode(text).ids)

    def embed(self, text: str) -> list[float]:
        """문장 하나를 L2 정규화된 1024차원 벡터로 바꾼다.

        인자:
            text: 임베딩할 문장. 최대 8192토큰으로 자른다.

        반환:
            길이 1024의 float 목록. L2 norm은 1이다.

        발생:
            ValueError: 모델이 영벡터를 냈을 때.
        """
        self._load()
        assert self._output is not None
        encoded = self._tokenizer.encode(text)
        feed = {
            "input_ids": np.asarray([encoded.ids], dtype=np.int64),
            "attention_mask": np.asarray([encoded.attention_mask], dtype=np.int64),
        }
        result = self._session.run([self._output.name], feed)[0]
        vector = result[0, 0, :] if self._output.takes_cls else result[0, :]
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            raise ValueError("임베딩 결과가 영벡터다")
        return (vector / norm).tolist()

    def _load(self) -> None:
        """모델 파일을 받고 ONNX 세션과 tokenizer를 만든다.

        두 번째 호출부터는 아무것도 하지 않는다. 여러 스레드가 동시에 불러도 한 번만 올린다.
        """
        if self._session is not None:
            return
        with self._load_lock:
            if self._session is None:
                self._load_once()

    def _load_once(self) -> None:
        # 무거운 의존성이라 설정만 읽는 코드가 끌어오지 않게 여기서 import한다.
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        # 기본 캐시는 심링크라 onnxruntime이 외부 데이터(model.onnx_data)를 모델 폴더 밖 경로로 보고
        # 거부한다(macOS·Linux, #313). 실제 파일을 한 폴더에 받는다. 이미 받았으면 다시 받지 않는다.
        model_dir = str(_model_dir(self._settings))

        def download(name: str) -> str:
            return hf_hub_download(
                self._settings.model_id,
                name,
                revision=self._settings.revision,
                local_dir=model_dir,
            )

        model_path = download(ONNX_FILE)
        # model.onnx가 외부 데이터로 참조하는 파일. 같은 폴더에 있어야 세션이 열린다.
        download(ONNX_DATA_FILE)
        tokenizer = Tokenizer.from_file(download(TOKENIZER_FILE))
        # 특수 토큰을 포함해 자른다(tokenizers의 기본 동작).
        tokenizer.enable_truncation(max_length=MAX_TOKENS)

        session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self._output = _pick_output(session)
        self._tokenizer = tokenizer
        # 잠금 밖의 빠른 확인(_session)이 나머지 값이 준비된 뒤에만 참이 되게 마지막에 쓴다
        self._session = session


def _model_dir(settings: EmbedderSettings) -> Path:
    """모델 파일을 받을 폴더: <HF_HOME>/soc-onnx/<모델 ID>/<revision>. 설정 키는 따로 없다."""
    home = os.environ.get("HF_HOME")
    if not home:
        cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
        home = str(Path(cache) / "huggingface")
    slug = re.sub(r"[^A-Za-z0-9._-]", "--", settings.model_id)
    return Path(home) / "soc-onnx" / slug / settings.revision


def _pick_output(session: Any) -> OnnxOutput:
    """세션의 출력 이름·shape를 보고 쓸 출력을 고른다.

    [batch, sequence, 1024] hidden state가 있으면 그 출력의 CLS를 쓰고, 없으면
    [batch, 1024] pooled 출력을 쓴다. 마지막 차원이 1024가 아니면 멈춘다(D-031).

    발생:
        ValueError: 마지막 차원이 1024가 아니거나 쓸 수 있는 출력이 없을 때.
    """
    outputs = session.get_outputs()
    for rank, takes_cls in ((3, True), (2, False)):
        for output in outputs:
            if len(output.shape) != rank:
                continue
            if output.shape[-1] != DIMENSION:
                raise ValueError(
                    f"ONNX 출력 차원이 {DIMENSION}이 아니다: {output.name} {output.shape}"
                )
            return OnnxOutput(output.name, tuple(output.shape), takes_cls)
    raise ValueError("ONNX 출력에서 dense 벡터를 찾지 못했다")
