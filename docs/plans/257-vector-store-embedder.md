---
issue: 257
date: 2026-11-05
owner: Juhyeok0603
supersedes: []
---

# 벡터 저장소와 BGE-M3 임베딩 계층 만들기

## 목표

L2·L3가 함께 쓸 일반적인 벡터 저장 계층을 `src/soc/store/`에 만든다.
BGE-M3 dense ONNX 임베더와 작은 가짜 임베더를 제공하고, 실제 Qdrant에서
컬렉션 생성·적재·검색·필터·삭제가 동작하도록 한다.

Ticket·Incident·Case 같은 업무 개념과 L2 분류 로직은 넣지 않는다.

## 방법

### 의존성과 결정

`pyproject.toml`에 아래 버전을 직접 고정하고 `uv.lock`을 갱신한다.

- `qdrant-client==1.20.0`
- `onnxruntime==1.31.1`
- `huggingface-hub==2.4.0`
- `tokenizers==0.23.3`
- `numpy==2.5.4`

코드가 NumPy를 ONNX 입력과 벡터 정규화에 직접 사용하므로 전이 의존성에
기대지 않고 직접 선언한다. Python 3.13에서 기존 의존성과 함께 설치할 수
있어야 하며 `torch`는 설치되지 않아야 한다.

`docs/decisions.md`의 저장 절에 D-044를 추가한다.

> D-044 | 벡터 DB 클라이언트와 임베딩 실행은
> `qdrant-client==1.20.0`, `onnxruntime==1.31.1`,
> `huggingface-hub==2.4.0`, `tokenizers==0.23.3`,
> `numpy==2.5.4`. FastEmbed는 bge-m3를 공식 지원하지 않아 쓰지 않고,
> torch를 끌어오는 경로도 쓰지 않는다 | 2GB가 넘는 torch를 `uv sync`와
> CI에 올리지 않기 위해서다. bge-m3 ONNX는 외부 데이터 방식이라
> `model.onnx`와 함께 약 2.27GB의 `model.onnx_data`를 요구하고,
> tokenizer 파일도 같은 revision에서 받는다. 모델 ID와 revision은 설정
> 값이다(D-031).

D-031 메모에는 “실행 라이브러리는 D-044”를 추가한다. 「기록」 맨 위에는
#257에서 D-044를 확정한 내용을 남긴다. 구체적인 Hugging Face 파일 경로와
revision 문자열은 결정에 넣지 않는다.

### 설정

`src/soc/store/config.py`에서 `[store]`만 읽고 기본 설정 위에
`config/local.toml`을 덮어쓴다.

```toml
[store.qdrant]
url_env = "QDRANT_URL"

[store.embedder]
model_id = "BAAI/bge-m3"
revision = "5617a9f61b028005a4858fdac845db406aefb181"
```

설정 로더는 TOML 값만 읽고 검증한다.

- `url_env`는 올바른 환경변수 이름이어야 한다.
- `model_id`는 빈 문자열이 아니어야 한다.
- `revision`은 40자 소문자 16진수여야 한다.
- 설정을 읽을 때 `QDRANT_URL` 환경변수 값은 확인하지 않는다.

Qdrant 클라이언트를 만드는 시점에만 `url_env`가 가리키는 환경변수를 읽는다.

- 값이 없거나 HTTP(S) Qdrant 주소가 아니면 `StoreError`를 낸다.
- 오류에는 환경변수 이름만 넣고 URL 값과 접속 주소는 넣지 않는다.
- 기본 pytest와 CI `check` job은 `QDRANT_URL` 없이 설정을 읽을 수 있어야 한다.

`.env.example`에는 `QDRANT_URL` 이름만 추가한다. Hugging Face 기본 캐시와
ONNX Runtime 기본 CPU provider·스레드 설정을 사용하며 별도 설정은 만들지
않는다.

### 모델 파일 확인

구현 첫 단계에서 고정 revision의 실제 파일 목록과 크기를 확인하고
`docs/notes/`에 기록한다. 사용할 예정인 파일은 다음과 같다.

```text
onnx/model.onnx
onnx/model.onnx_data
onnx/tokenizer.json
```

세 파일은 모두 같은 `model_id`와 revision에서 받는다. 구현에 들어가기 전에
고정 revision에 세 경로가 실제로 존재하는지 다시 확인한다.

`onnx/model.onnx`는 코드 상수로 고정하며 설정으로 받지 않는다.

### 임베더

프로덕션 코드에는 최소 인터페이스만 둔다.

```text
dimension -> int
embed(text: str) -> list[float]
```

실제 BGE-M3 임베더는 다음 순서로 동작한다.

1. `huggingface-hub`로 고정 파일 세 개를 내려받아 기본 캐시에 둔다.
2. tokenizer가 특수 토큰을 포함해 최대 8192토큰으로 자른다.
3. ONNX Runtime 세션의 출력 이름과 shape를 먼저 확인한다.
4. 출력이 `[batch, sequence, 1024]`의 hidden state이면 `[:, 0, :]`를
   CLS dense 벡터로 사용한다.
5. 출력이 `[batch, 1024]`의 pooled 벡터이면 그 값을 그대로 사용한다.
6. 선택한 벡터를 NumPy로 L2 정규화하고 `list[float]`로 반환한다.

출력이 pooled된 2차원 값으로 확인되면 그 값을 정규화해 쓰도록 계획의
「바뀐 점」에 적고 계속한다. 차원이 1024가 아닐 때만 멈춘다.

실제 출력 이름과 shape, CLS 또는 pooled 중 사용한 경로는 개발 기록에
남긴다. sparse·multi-vector·batch embedding은 만들지 않는다.

`tests/fake_embedder.py`에는 `hashlib` 기반의 결정적인 작은 차원 임베더를
둔다. 실행마다 값이 달라지는 Python `hash()`는 사용하지 않는다.

### 컬렉션 이름

컬렉션 이름은 용도·모델·ONNX 파일에서 코드가 파생한다.

```text
<purpose>__<model-slug>__<digest>
```

- `purpose`는 호출자가 코드 상수로 주며 `[a-z0-9_]{1,64}`만 받는다.
- `model-slug`는 모델 ID의 마지막 구간을 소문자 안전 문자로 바꾸고
  64자까지 사용한다.
- digest는 아래 값의 SHA-256 앞 16자리다.

```text
sha256(model_id + "\0" + revision + "\0" + "onnx/model.onnx")[:16]
```

결과는 ASCII 안전 문자만 사용하고 Qdrant의 255바이트 한도를 넘지 않는다.
같은 입력은 같은 이름을 만들고 모델 ID·revision·ONNX 파일 이름 중 하나가
바뀌면 다른 이름을 만든다.

### Qdrant 저장소

동기 `qdrant-client`로 다음 일반 연산만 제공한다.

- 컬렉션 존재 확인
- 임베더 차원과 Cosine으로 컬렉션 생성
- UUID point 한 건 upsert
- 벡터와 `top_k`로 검색
- payload 필터 검색
- payload 키·값에 맞는 point 전체 삭제
- 현재 설정에서 파생한 컬렉션 삭제

검색 필터는 `dict[str, str | int | bool]`이며 모든 항목을 동등 조건 AND로
결합한다. 검색 결과에는 UUID point ID, 점수, payload를 담는다.

기존 컬렉션은 다음 조건을 모두 검사한다.

- 단일 unnamed vector를 사용한다.
- 벡터 차원이 현재 임베더의 `dimension`과 같다.
- 거리 방식이 Cosine이다.

차원이나 거리 방식이 다르면 컬렉션을 사용하지 않는다. upsert와 삭제는
Qdrant 처리가 완료될 때까지 기다린 뒤 반환한다.

공개 오류는 다음 세 종류로 제한한다.

- `CollectionMissing`: 컬렉션이 없음
- `CollectionMismatch`: 차원·거리 방식·vector 모양이 현재 설정과 다름
- `StoreError`: 환경변수·주소·접속 실패와 그 밖의 Qdrant 실패

후속 L2-A-2는 `CollectionMissing`을 `collection_missing`,
`StoreError`를 `query_failed`로 기록한다. `CollectionMismatch`는 설정
오류이므로 직접 조회로 fallback하지 않고 오류로 끝낸다.

### 테스트 샘플과 격리

`tests/fixtures/store/`에 손으로 만든 작은 텍스트·UUID·payload 샘플을 둔다.
실제 기업 데이터나 공개 데이터셋 원본은 사용하지 않는다.

Qdrant 통합 테스트는 테스트마다 고유한 `purpose`를 사용한다. 테스트가
성공하거나 실패해도 `finally`에서 자신이 만든 컬렉션만 삭제한다.

### 테스트 구분

기본 pytest:

- 설정 기본값과 `config/local.toml` 덮어쓰기
- `url_env` 이름·모델 ID·revision 검증
- `QDRANT_URL` 없이 설정을 읽을 수 있음
- 클라이언트 생성 시 환경변수 없음·잘못된 URL을 `StoreError`로 처리
- 오류에 URL 값이 노출되지 않음
- 컬렉션 이름의 결정성·안전 문자·길이
- 모델 ID·revision·ONNX 파일 이름 변경 시 다른 이름
- 가짜 임베더의 결정성과 차원
- payload 필터 변환과 입력 검증

`qdrant` 마커:

- 컬렉션 생성과 존재 확인
- 같은 설정으로 컬렉션 생성 재호출
- 다른 차원·거리 방식·named vector의 `CollectionMismatch`
- upsert 후 search
- payload 동등 조건 AND 필터
- 같은 payload 키·값을 가진 point 전체 삭제
- `CollectionMissing`과 `StoreError`
- 컬렉션 삭제 후 재생성
- 테스트 성공·실패 후 고유 컬렉션 정리

`embedder` 마커:

- 실제 tokenizer가 최대 8192토큰으로 자름
- ONNX 실행 직전 토큰 수가 8192 이하임
- 짧은 입력 한 건을 실제 BGE-M3로 추론
- 실제 출력 이름과 shape 확인
- CLS 또는 pooled 경로에서 차원 1024와 L2 norm 1 확인

8192토큰 전체를 실제 ONNX로 추론하지 않는다. `pyproject.toml`에
`embedder` 마커를 추가하고 기본 `addopts`에 `and not embedder`를 더해
일반 `uv run pytest`가 모델을 내려받지 않게 한다.

### CI

기존 CI `db` job에 `qdrant/qdrant:v1.19.2` 서비스와 6333 포트를 추가한다.
job 환경에는 다음 값을 둔다.

```text
QDRANT_URL=http://localhost:6333
```

Qdrant 이미지 내부 healthcheck는 사용하지 않는다. 서비스 준비는 Ubuntu
러너의 `curl`로 기다린다.

```yaml
- name: Wait for Qdrant
  run: |
    for i in $(seq 1 30); do
      curl -sf http://localhost:6333/readyz && exit 0
      sleep 2
    done
    exit 1
```

기존 DB 테스트 명령은 다음으로 바꾼다.

```text
uv run pytest -m "db or qdrant"
```

실제 BGE-M3 모델은 CI에서 다운로드하지 않는다. `compose.yaml`은 바꾸지
않는다.

### 개발 안내와 기록

`CONTRIBUTING.md`에는 `uv run pytest -m embedder`가 첫 실행 때 약 2.27GB의
모델 데이터를 내려받는다고 적는다.

실제 확인한 다음 내용은 `docs/notes/257-vector-store-embedder.md`에 남긴다.

- 고정 revision의 실제 파일 목록과 크기
- ONNX 출력 이름과 shape
- CLS 또는 pooled 중 사용한 출력 경로
- 첫 모델 로딩 시간
- 짧은 입력 한 건의 추론 시간
- 실제 설치 결과에 `torch`가 없는지

## 바꿀 곳

- `pyproject.toml`: 의존성 다섯 개, `embedder` 마커와 기본 제외 조건
- `uv.lock`: 새 의존성 고정
- `src/soc/store/config.py`: store 설정 로더와 검증
- `src/soc/store/`: 임베더 인터페이스·구현, 이름 파생, Qdrant 저장소
- `config/default.toml`: `[store.qdrant]`, `[store.embedder]`
- `.env.example`: `QDRANT_URL` 이름
- `.github/workflows/ci.yml`: Qdrant 서비스·준비 대기·환경변수·테스트 명령
- `tests/fake_embedder.py`: 작은 결정적 가짜 임베더
- `tests/fixtures/store/`: 손으로 만든 point 샘플
- `tests/test_store_config.py`: 설정과 환경변수 검증
- `tests/test_store_embedder.py`: 이름·가짜 임베더·실제 임베더
- `tests/test_store_qdrant.py`: 실제 Qdrant 연산
- `docs/decisions.md`: D-044, D-031 참조, 결정 기록
- `CONTRIBUTING.md`: `embedder` 테스트 다운로드 비용
- `docs/plans/257-vector-store-embedder.md`: 확정 계획
- `docs/notes/257-vector-store-embedder.md`: 개발 기록

`compose.yaml`, DB 마이그레이션, 데이터 계약은 바꾸지 않는다.

## 다른 코드와 맞물리는 곳

- `src/soc/store/`는 L2·L3가 함께 쓰는 공통 계층이다. 공개 인터페이스에
  Ticket·Incident·Case를 넣지 않는다.
- 후속 L2-A-2는 이 저장소와 `tests/fake_embedder.py`를 사용한다.
- 후속 L2-A-2는 `CollectionMissing`과 `StoreError`만 fallback 사유로
  사용하며 `CollectionMismatch`는 오류로 끝낸다.
- CI `db` job은 PostgreSQL과 Qdrant를 함께 실행하지만 기존 `db` 테스트의
  동작은 바꾸지 않는다.
- 새 환경변수는 `QDRANT_URL` 하나다.
- `docs/decisions.md`에 D-044가 늘고 D-031 메모가 한 줄 늘어난다.
  의존성 결정이므로 다른 담당자에게 PR로 알리고, 「기록」에는
  “L2 담당이 정함(#257)”으로 남긴다.
- 기존 함수·테이블·계약·설정 키는 바꾸지 않는다.

## 범위 밖

- Ticket 임베딩 텍스트 합성
- L2 후보 검색·fallback·에이전트 판정·Incident 저장
- PostgreSQL에서 Qdrant 색인을 재구축하는 명령
- L3 유사 사례용 Ticket·Case 컬렉션
- batch embedding과 batch upsert
- sparse·multi-vector·GPU provider
- 별도 모델 캐시 경로와 ONNX Runtime 스레드 설정
- ONNX 파일 선택 설정과 양자화 모델
- CI에서 실제 BGE-M3 다운로드
- `compose.yaml` 변경
- DB 마이그레이션과 데이터 계약 변경
- 모델 ID·revision을 바꾸 쓰지 않게 된 옛 컬렉션을 자동으로 찾거나 지우는 명령.
  필요하면 사람이 Qdrant에서 직접 지운다

## 완료 기준

- [ ] D-044와 D-031 참조·결정 기록이 `docs/decisions.md`에 있다
- [ ] 의존성 다섯 개가 합의한 버전으로 고정되고 torch가 설치되지 않는다
- [ ] `[store.qdrant]`·`[store.embedder]`와 `QDRANT_URL` 이름이 있다
- [ ] 설정 로더가 환경변수 값 없이 동작한다
- [ ] 클라이언트 생성 시 잘못된 환경변수 값을 `StoreError`로 처리한다
- [ ] URL 값과 접속 주소가 오류에 노출되지 않는다
- [ ] 고정 revision의 ONNX 외부 데이터와 tokenizer를 함께 내려받는다
- [ ] ONNX 출력 이름과 shape를 확인해 CLS 또는 pooled dense 벡터를 사용한다
- [ ] 임베더가 차원 1024의 L2 정규화 벡터를 만든다
- [ ] tokenizer가 ONNX 실행 전에 최대 8192토큰으로 자른다
- [ ] 가짜 임베더가 결정적이고 작은 차원으로 동작한다
- [ ] 컬렉션 이름이 용도·모델 ID·revision·ONNX 파일 이름을 반영한다
- [ ] 기존 컬렉션의 vector 모양·차원·거리 방식이 다르면 `CollectionMismatch`다
- [ ] upsert·search·payload AND 필터·전체 삭제·컬렉션 삭제가 실제 Qdrant에서 동작한다
- [ ] `CollectionMissing`과 그 밖의 `StoreError`가 구분된다
- [ ] Qdrant 테스트가 고유 컬렉션을 쓰고 실패해도 정리한다
- [ ] 기본 pytest에서 `embedder`·`qdrant` 테스트가 제외된다
- [ ] CI가 `/readyz` 성공을 기다린 뒤 Qdrant 테스트를 시작한다
- [ ] CI `db` job이 `uv run pytest -m "db or qdrant"`를 통과한다
- [ ] 실제 BGE-M3 짧은 입력 한 건의 파일·출력·시간 결과가 기록된다
- [ ] `CONTRIBUTING.md`에 약 2.27GB 다운로드 비용이 안내된다
- [ ] `uv run ruff format --check .`이 통과한다
- [ ] `uv run ruff check .`가 통과한다
- [ ] `uv run pytest`가 통과한다
- [ ] `uv run pytest -m "db or qdrant"`가 통과한다
- [ ] `uv run pytest -m embedder`가 통과한다
- [ ] 확정 계획과 개발 기록이 있다

## 토론으로 정한 것

1. 라이브러리 선택은 개발 기록에만 두지 않고 새 결정 D-044로 추가한다.
2. D-044는 다섯 직접 의존성의 정확한 버전을 고정한다.
3. D-031에는 구체 라이브러리를 반복하지 않고 D-044 참조만 추가한다.
4. D-044에는 Hugging Face 파일 경로와 revision 문자열을 넣지 않는다.
5. 실제 파일 경로는 계획과 개발 기록에 두고 구현 첫 단계에서 다시 확인한다.
6. ONNX 파일은 `onnx/model.onnx`, `onnx/model.onnx_data`,
   `onnx/tokenizer.json`을 사용할 예정이며 구현 첫 단계에서 실제 목록을 확인한다.
7. 컬렉션 이름 digest에는 모델 ID·revision은 물론 ONNX 파일 이름도 넣는다.
8. payload 필터는 문자열·정수·불리언 동등 조건의 AND만 지원한다.
9. 공개 오류는 `CollectionMissing`·`CollectionMismatch`·`StoreError` 세 종류다.
10. 접속 실패는 별도 오류로 나누지 않고 `StoreError`로 처리한다.
11. `CollectionMismatch`는 설정 오류이므로 fallback하지 않는다.
12. 설정 로더는 환경변수 값을 읽지 않고 클라이언트 생성 시점에 검증한다.
13. Hugging Face 캐시와 ONNX Runtime CPU provider·스레드는 기본값을 쓴다.
14. ONNX 출력이 hidden state이면 CLS를, pooled 2차원 값이면 그 값을 사용한다.
15. 출력 차원이 1024가 아닐 때만 중단한다.
16. 실제 모델 테스트는 새 `embedder` 마커로 분리한다.
17. 8192토큰 절단은 ONNX 입력 직전 길이로 확인하고 긴 입력을 실제 추론하지 않는다.
18. compose healthcheck와 `compose.yaml` 변경은 하지 않는다.
19. CI 러너가 `curl`로 Qdrant `/readyz`를 기다린다.
20. CI에 `QDRANT_URL`을 명시하고 기존 `db` job에서 Qdrant 테스트도 실행한다.
21. 손으로 만든 store fixture와 테스트별 고유 컬렉션 정리를 추가한다.
22. `CONTRIBUTING.md`에 첫 모델 다운로드 비용을 안내한다.
23. NumPy는 코드가 직접 사용하므로 직접 의존성으로 고정한다.
24. 모델이나 revision을 바꾸어 쓰지 않게 된 옛 컬렉션은 사람이 직접 지우며,
    이를 위한 명령은 만들지 않는다.

## 바뀐 점
