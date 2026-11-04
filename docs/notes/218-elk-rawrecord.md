---
issue: 218
date: 2026-11-04
owner: uptime-zero
plan: 218-elk-rawrecord.md
supersedes: []
---

# 한 번 실행하는 ELK 수집 명령이 RawRecord와 체크포인트를 함께 저장한다

## 한 일

- `uv run python -m soc.ingest`가 설정(`[ingest]`)의 조회 대상(Alert alias 1개, 웹·클라우드 Event 5개)을 차례로 ELK에서 읽어 `raw_records`에 저장한다. 스케줄러는 없고 cron이 호출한다.
- 조회는 실행 안에서 PIT와 `search_after`로 페이지를 넘기고, 실행 사이에는 체크포인트 시각부터 `gte`로 다시 읽는다. 겹친 문서는 `(siem_profile, siem_ref)` 유일 제약으로 건너뛴다.
- 페이지의 원본과 체크포인트는 `store.save_page`의 한 트랜잭션으로 저장한다. 실패하면 그 대상은 재시도·건너뛰기 없이 멈추고, 종류 코드(`timeout`, `auth`, `contract_rejected`, `db_error` 등)를 stderr와 체크포인트의 `last_error`에 남긴다. 다른 대상은 계속하고 종료 코드는 1이다.
- 새 계약 `ingest_checkpoint`와 테이블 `ingest_checkpoints`(마이그레이션 `0100`)를 추가했다.

## 계획과 달라진 점

- 첫 조회(체크포인트 없음)는 `exists: time_field` 조건을 붙인다. 시각 필드가 없는 문서는 커서를 만들 수 없다.
- `deadline_seconds`·`max_bytes`는 대상 전체가 아니라 응답 하나마다 적용한다. 큰 catch-up이 매번 timeout으로 끝나는 것을 막으려는 선택이다. D-039의 "출처별 마감"과 다르므로 확인이 필요하다.
- 첫 페이지부터 실패하면 빈 cursor(`{}`)로 체크포인트 행을 만들어 `last_error`를 남긴다. 빈 cursor는 "성공한 페이지 없음"이라 처음부터 조회한다.
- `last_error`는 소문자 코드 모양(`^[a-z][a-z0-9_]*$`)만 받는다. 원문이 들어가지 않게 계약과 CHECK로 막았다.
- `ELK_URL`은 http도 받는다(로컬 ELK). 사용자 정보가 든 URL은 거부한다.

## 다음 사람이 알아야 할 것

- Event의 `time_field`는 아직 `@timestamp`다. `@timestamp`를 커서로 쓰면 색인이 늦게 끝난 문서를 놓친다. 로컬 ES에서 확인했다(`.local/elk/late_arrival.py`): `@timestamp` 커서는 늦은 문서 0건, `event.ingested` 커서는 1건을 잡았다. `event.ingested`로 바꾸려면 실제 ELK에 필드가 있는지 먼저 확인한다. 없으면 `exists` 필터가 문서를 조용히 건너뛰어 실행이 성공처럼 보인다. 확인 명령은 `config/default.toml` 주석에 있다. 색인 지연이 커서보다 길어지면 이 방법도 놓칠 수 있으므로, 겹침 구간(lookback)을 두는 방안을 따로 정한다.
- `date_nanos` 필드면 나노초가 커서에 들어가므로 정렬에 `numeric_type: "date"`가 필요하다.
- 같은 밀리초에 한 페이지보다 많은 문서가 있으면 매 실행 다시 읽는다. 결과는 맞지만 낭비다.
- 자체 서명 인증서용 CA 설정이 없다.
- Event 대상 이름(`logs-nginx.access-*` 등)과 Alert alias는 #208 확정 전의 기본값이다. 실제 space와 데이터 스트림으로 바꾼다.
- 실제 ELK에서는 아직 확인하지 않았다. 합성 fixture와 `httpx.MockTransport`로만 검증했다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`(602 통과), `uv run pytest -m db`(129 통과), `uv run python scripts/generate_contracts.py --check`.
- DB 테스트는 로컬 Postgres(`DATABASE_URL`)에서 `uv run pytest -m db`로 129개 통과했다.
- 로컬 ELK(`.local/elk/`, 합성 데이터만)에서 손으로 확인: 600건 2페이지, 같은 `_id` 두 인덱스, 실패 후 재개(`network` 기록 뒤 새 문서 1건 저장, `last_error` 비움), 늦은 문서 커서 비교.
- 주요 테스트: `tests/test_ingest_store_db.py`(원자성·롤백·중복), `tests/test_ingest_run_db.py`(실패 후 재개), `tests/test_ingest_elk.py`(페이징·오류 종류), `tests/test_ingest_run.py`.
