---
issue: 257
date: 2026-11-05
owner: Juhyeok0603
plan: 257-vector-store-embedder.md
supersedes: []
---

# 벡터 저장소와 BGE-M3 임베딩 계층을 만들었다

## 한 일

- `src/soc/store/`에 L2·L3가 함께 쓰는 벡터 계층을 만들었다. 업무 개념(Ticket·Incident·Case)은
  넣지 않고, 설정 로더·임베더·컬렉션 이름 파생·Qdrant 연산만 둔다.
- `[store.qdrant] url_env`와 `[store.embedder] model_id·revision`을 읽는다. 설정을 읽을 때는
  환경변수 값을 보지 않고, `create_client()`가 `QDRANT_URL`을 읽어 http(s)인지 확인한다.
- `BgeM3Embedder`가 고정 revision의 ONNX 파일 세 개를 Hugging Face 기본 캐시에 받아 dense
  벡터(1024차원, L2 정규화)를 만든다. tokenizer는 특수 토큰을 포함해 8192토큰으로 자른다.
- `VectorStore`가 컬렉션 존재 확인·생성·upsert·검색·payload AND 필터·payload 전체 삭제·
  컬렉션 삭제를 한다. 공개 오류는 `CollectionMissing`·`CollectionMismatch`·`StoreError`다.
- CI `db` job에 Qdrant 서비스와 `/readyz` 대기를 넣고 `uv run pytest -m "db or qdrant"`로 바꿨다.

## 확인한 모델 파일

`BAAI/bge-m3` revision `5617a9f61b028005a4858fdac845db406aefb181`의 `onnx/` 실제 목록이다
(Hugging Face `api/models/.../tree` 응답).

| 파일 | 크기 | 쓰는지 |
|---|---|---|
| `onnx/model.onnx` | 724,923 B (708 KiB) | 쓴다. 코드 상수 `ONNX_FILE` |
| `onnx/model.onnx_data` | 2,266,820,608 B (2.11 GiB ≈ 2.27 GB) | 쓴다. 외부 데이터 |
| `onnx/tokenizer.json` | 17,082,821 B (16.3 MiB) | 쓴다 |
| `onnx/Constant_7_attr__value` | 65,552 B | 쓰지 않는다 |
| `onnx/config.json` | 698 B | 쓰지 않는다 |
| `onnx/sentencepiece.bpe.model` | 5,069,051 B | 쓰지 않는다 |
| `onnx/special_tokens_map.json` | 964 B | 쓰지 않는다 |
| `onnx/tokenizer_config.json` | 1,173 B | 쓰지 않는다 |

`onnx/Constant_7_attr__value`는 외부 데이터처럼 보이지만 `model.onnx`가 참조하지 않는다.
받은 `model.onnx`의 외부 데이터 참조는 `model.onnx_data` 하나뿐이어서 세 파일만 받는다.

## 확인한 ONNX 출력

| | 이름 | 형식 | shape |
|---|---|---|---|
| 입력 | `input_ids` | int64 | `[batch_size, sequence_length]` |
| 입력 | `attention_mask` | int64 | `[batch_size, sequence_length]` |
| 출력 | `token_embeddings` | float32 | `[batch_size, sequence_length, 1024]` |
| 출력 | `sentence_embedding` | float32 | `[batch_size, 1024]` |

**쓰는 경로는 `token_embeddings`의 CLS(`[:, 0, :]`)다.** 계획의 4번(hidden state면 CLS)에
그대로 해당해서 pooled 경로로 바꾸지 않았다. 둘이 같은 벡터인지도 확인했다.

- `sentence_embedding`의 L2 norm은 1.0이고, 정규화한 CLS와 Cosine 유사도가 1.0이다.
  즉 `sentence_embedding`은 이미 정규화된 CLS다.
- 평균 풀링과는 Cosine 0.828이라 다른 값이다. pooled 출력이 CLS 풀링인 것은 확인됐다.

측정값(Windows 11, CPU provider, 캐시가 이미 있는 상태):

- 첫 모델 로딩(`InferenceSession` 만들기): 3.4초
- 짧은 입력 한 건(11토큰) 추론: 0.07초
- `uv run pytest -m embedder`: 5개 34.66초. 테스트마다 세션을 새로 만들어 건당 약 5초다
- 첫 내려받기: `tokenizer.json` 4.4초, `model.onnx` 1.9초, `model.onnx_data` 35.6초

설치 결과에 `torch`·`nvidia-*`·`triton`은 없다. `uv add`로 늘어난 것은 17개
(`numpy`, `onnxruntime`, `qdrant-client`, `huggingface-hub`, `tokenizers`와 그 전이 의존성
`filelock`, `flatbuffers`, `fsspec`, `grpcio`, `h2`, `hf-xet`, `hpack`, `hyperframe`,
`portalocker`, `protobuf`, `tqdm`)다.

## 계획과 달라진 점

계획의 목표·범위·완료 기준은 그대로다. 파일 나누기와 이름만 정했다.

- 설정 파일 검증 오류는 다른 설정 로더와 같게 `ConfigError`(ValueError)로 뒀다. 계획의
  "공개 오류 세 종류"는 Qdrant 연산의 오류라 그대로다. 환경변수·주소 오류는 `StoreError`다.
- 부르는 쪽 잘못(`purpose` 모양, 벡터 길이, `top_k`, 필터 값 종류)은 `ValueError`로 낸다.
  Qdrant 실패가 아니라서 세 종류에 넣지 않았다.
- "벡터와 top_k로 검색"과 "payload 필터 검색"을 `search(vector, top_k, filters=None)` 하나로
  합쳤다. 필터는 `build_filter()`가 따로 만들어 기본 pytest에서 검증한다.
- 모델 내려받기와 ONNX 세션 만들기는 `dimension`·`embed()`를 처음 쓸 때 한다. 설정만 읽는
  코드가 2.27GB를 받지 않게 하려고 `__init__`에서는 아무것도 하지 않는다.
- 개발 기록과 `embedder` 테스트가 확인할 값으로 `BgeM3Embedder.output`(고른 출력 이름·shape·
  CLS 여부)과 `token_count(text)`를 뒀다. 저장소가 쓰는 인터페이스는 계획대로
  `dimension`·`embed()` 둘이다(`Embedder` Protocol).
- 파일은 `config.py`·`embedder.py`·`qdrant.py` 셋이고 컬렉션 이름 파생은 `ONNX_FILE` 상수가
  있는 `embedder.py`에 뒀다.

## 다음 사람이 알아야 할 것

- **컬렉션 이름**은 `<purpose>__<model-slug>__<digest>`이고 digest는
  `sha256(model_id + "\0" + revision + "\0" + "onnx/model.onnx")[:16]`이다. 모델 ID·revision·
  ONNX 파일 이름 중 하나만 바뀌어도 다른 컬렉션이 된다. 쓰지 않게 된 옛 컬렉션은 사람이
  Qdrant에서 직접 지운다(자동으로 찾거나 지우는 명령은 만들지 않았다).
- `purpose`는 호출자가 코드 상수로 준다. 사람 입력이나 밖에서 온 문자열을 넣지 않는다.
- 저장소는 임베딩을 하지 않는다. 부르는 쪽이 `embedder.embed(text)`로 벡터를 만들어
  `upsert`·`search`에 넘긴다. batch upsert·batch embedding은 없다.
- `CollectionMissing` 판별은 qdrant-client 오류 **본문**(`collection ... doesn't exist`,
  `not found` + 컬렉션 이름)으로 한다. 예외 종류가 HTTP·gRPC와 버전마다 달라서다.
  qdrant-client를 올릴 때 `-m qdrant`의 `test_missing_collection_raises_collection_missing`이
  먼저 깨지므로 그 테스트를 확인한다.
- `CollectionMismatch`는 설정 오류라 fallback 대상이 아니다(#248). 후속 L2-A-2는
  `CollectionMissing`을 `collection_missing`, `StoreError`를 `query_failed`로 기록한다.
- `uv run pytest -m embedder`는 첫 실행에서 약 2.27GB를 받는다. CI는 돌리지 않으니 모델 쪽을
  고치면 손으로 돌려야 한다. 테스트마다 세션을 새로 만들어 건당 약 5초다.
- 8192토큰 전체를 실제로 추론하지는 않았다. 긴 입력은 `token_count()`로 절단만 확인한다.
- ONNX Runtime은 CPU provider와 기본 스레드 설정을 쓴다. 별도 캐시 경로·스레드 설정은 없다.
- Windows의 Hugging Face 캐시는 심링크를 못 써서 "degraded" 경고가 뜬다. 동작에는 문제가
  없지만 디스크를 더 쓴다.
- CI `db` job이 PostgreSQL과 Qdrant를 함께 띄운다. Qdrant 이미지에 `curl`·셸이 없어
  컨테이너 healthcheck 대신 러너의 `curl`로 `/readyz`를 기다린다.
- **`config/default.toml`에서 `[store.*]`는 `[l3.intel]` 앞에 둬야 한다.**
  `tests/test_l3_config.py::test_default_config_reads_into_settings`가 `[l3`부터 **파일 끝까지**를
  잘라 `_env`가 없다고 본다. 그래서 `url_env`가 있는 절을 파일 끝에 붙이면 L3 테스트가 깨진다.
  처음에는 끝에 붙였다가 이 테스트가 깨져서 `[l2.branch]` 다음으로 옮겼다. L3 담당이 그 slice를
  l3 절 끝까지로 좁히면 위치 제약이 없어진다(남의 이슈 테스트라 이번에 고치지 않았다).
- **Windows에서는 `QDRANT_URL`에 `localhost` 대신 `127.0.0.1`을 쓴다.** `localhost`가 IPv6
  (`::1`)로 먼저 풀려 요청마다 수백 밀리초가 붙는다. 같은 `-m qdrant` 21개가
  `http://localhost:6333`에서 258초, `http://127.0.0.1:6333`에서 27초였다. 코드 문제가
  아니라 이름 풀이 문제이고, CI(Ubuntu)는 `localhost`로도 빠르다.

- **이 이슈의 테스트는 구현보다 나중에 썼다.** 절차(`prompts/dev.md` 5번, AGENTS.md 원칙 3)는
  테스트를 먼저 쓰고 실패를 확인하라고 하는데, 설정·임베더·저장소를 먼저 쓰고 테스트를
  나중에 썼다. 처음 실행에서 전부 통과해서 **빨간 상태를 한 번도 보지 않았다.** 그래서 이
  테스트들이 실제로 깨질 수 있는지는 확인되지 않았다. 이 코드를 고치는 사람은 고치기 전에
  해당 테스트가 먼저 실패하는지 확인하는 편이 안전하다.
- `-m db`는 이 컴퓨터에서 돌리지 못했다. 5432를 compose가 아닌 다른 PostgreSQL이 쓰고 있어
  `.env`의 계정으로는 붙지 않는다. `-m "db or qdrant"`의 db 쪽은 CI에서 처음 돈다.

## 확인 방법

- `uv run ruff format --check .`: 통과
- `uv run ruff check .`: 통과
- `uv run pytest`: 1,197개 통과, 1개 실패(store 기본 테스트 54개 포함). 실패는 기존
  `test_name_ending_in_newline_is_not_a_migration`으로, 테스트 자체가 Linux·macOS에서만
  만들 수 있는 파일 이름을 쓴다(#248 기록과 같다). CI는 Ubuntu라 통과한다
- `uv run pytest -m "db or qdrant" --collect-only`: 350개 선택(db 329 + qdrant 21).
  CI 명령이 새 테스트를 빠뜨리지 않는지 확인했다
- `QDRANT_URL=http://127.0.0.1:6333 uv run pytest -m qdrant`: 21개 통과, 27.09초
  (compose의 `qdrant/qdrant:v1.19.2`, `/readyz` 확인 뒤 실행).
  `http://localhost:6333`으로도 21개 통과, 258.03초
- `uv run pytest -m embedder`: 5개 통과, 34.66초
- 손으로 확인: 고정 revision의 `onnx/` 파일 8개 목록과 크기, `model.onnx`의 외부 데이터
  참조 1개, ONNX 입력 2개·출력 2개의 이름과 shape, `sentence_embedding`과 정규화 CLS의
  Cosine 1.0, 설치 목록에 `torch` 없음
