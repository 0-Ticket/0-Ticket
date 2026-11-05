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
- 페이지의 원본과 체크포인트는 `store.save_page`의 한 트랜잭션으로 저장한다. 실패하면 그 대상은 재시도·건너뛰기 없이 멈추고, 종류 코드(`timeout`, `auth`, `contract_rejected`, `db_error` 등)를 stderr에 남긴다. 다른 대상은 계속하고 종료 코드는 1이다.
- 새 계약 `ingest_checkpoint`와 테이블 `ingest_checkpoints`(마이그레이션 `0100`)를 추가했다. 체크포인트는 재개 위치(`cursor`)와 `updated_at`만 가진다.
- 새 계약 `ingest_run`과 테이블 `ingest_runs`(마이그레이션 `0101`)를 추가했다. 대상마다 실행이 끝나면(성공·실패·0건 모두) `store.record_run`이 한 행을 쌓는다. `outcome`은 성공이면 `ok`, 실패면 종류 코드다. 이력 쓰기는 원본·체크포인트와 다른 트랜잭션이고, DB 오류가 나면 무시한다(stderr 줄은 남는다).
- 알럿과 원본 이벤트의 연결 테이블 `raw_links`(마이그레이션 `0102`)와 `store.link_by_refs`를 추가했다. `<_index>/<_id>` 형식의 `siem_ref` 쌍을 받아 두 원본이 모두 저장돼 있으면 연결하고, 한쪽이 없으면 연결하지 않고 보류 목록으로 돌려준다. 같은 쌍은 다시 넣어도 무시한다. 연결 행에는 식별자만 넣는다.

## 계획과 달라진 점

- 첫 조회(체크포인트 없음)는 `exists: time_field` 조건을 붙인다. 시각 필드가 없는 문서는 커서를 만들 수 없다.
- `deadline_seconds`·`max_bytes`는 대상 전체가 아니라 응답 하나마다 적용한다. 큰 catch-up이 매번 timeout으로 끝나는 것을 막으려는 선택이다. D-039의 "출처별 마감"과 다르므로 확인이 필요하다.
- 실패 원인은 처음에 체크포인트의 `last_error`에 두었다가, 사람 확정(계획 "바뀐 점" 실행 이력 테이블)에 따라 `ingest_runs`로 옮겼다. 같은 성공인데 hit이 있으면 `last_error`가 지워지고 0건이면 남는 불일치가 있었고, 이력이 DB에 남지 않았기 때문이다. 이미 적용된 `0100`은 고치지 않고 `0101`에서 `last_error` 열을 지웠다.
- 첫 페이지부터 실패하면 체크포인트 행은 만들지 않고 이력 행만 남는다. 체크포인트가 없으면 다음 실행은 처음부터 조회한다.
- `outcome`은 소문자 코드 모양(`^[a-z][a-z0-9_]*$`)만 받는다. 원문이 들어가지 않게 계약과 CHECK로 막았다. `finished_at >= started_at`은 DB CHECK와 같은 규칙을 `validate_contract`의 추가 검사(`not_before_started_at`)로도 둔다.
- `ELK_URL`은 http도 받는다(로컬 ELK). 사용자 정보가 든 URL은 거부한다.

## 다음 사람이 알아야 할 것

- `link_by_refs`를 부르는 곳이 아직 없다. 알럿 문서가 원본 이벤트를 가리키는 필드는 공개 데이터셋(Kibana 8.17.3 알럿)에서 `kibana.alert.ancestors`로 확인했다(`type`이 `event`인 항목의 `index`·`id`가 이벤트의 `siem_ref`). `kibana.alert.original_event.*`는 연결 키가 아니다. 조직 ELK에서 다시 확인하지 않았고, 알럿에서 쌍을 뽑는 코드와 `run.py`의 호출, 보류한 쌍을 다음 실행에서 다시 넘기는 코드는 후속 이슈로 분리했다(계획 218 "바뀐 점" 2026-11-05). 지금은 실행해도 `raw_links`에 행이 생기지 않는다.
- 이벤트 소스 5곳의 ECS 필드를 공식 통합 문서로 확인했다. 시각(`@timestamp`)과 웹 로그의 IP·URL, 클라우드 로그의 행위자·동작·리소스는 매핑할 수 있다. `file_hash`·`process`는 어떤 소스도 주지 않고, `domain`과 CloudTrail·Azure의 `source.ip`는 문서로 확인하지 못했다. 정규화 이슈에서 실제 문서로 다시 확인한다.

- Event의 `time_field`는 아직 `@timestamp`다. `@timestamp`를 커서로 쓰면 색인이 늦게 끝난 문서를 놓친다. 로컬 ES에서 확인했다(`.local/elk/late_arrival.py`): `@timestamp` 커서는 늦은 문서 0건, `event.ingested` 커서는 1건을 잡았다. `event.ingested`로 바꾸려면 실제 ELK에 필드가 있는지 먼저 확인한다. 없으면 `exists` 필터가 문서를 조용히 건너뛰어 실행이 성공처럼 보인다. 확인 명령은 `config/default.toml` 주석에 있다. 색인 지연이 커서보다 길어지면 이 방법도 놓칠 수 있으므로, 겹침 구간(lookback)을 두는 방안을 따로 정한다.
- `date_nanos` 필드면 나노초가 커서에 들어가므로 정렬에 `numeric_type: "date"`가 필요하다.
- 같은 밀리초에 한 페이지보다 많은 문서가 있으면 매 실행 다시 읽는다. 결과는 맞지만 낭비다.
- 자체 서명 인증서용 CA 설정이 없다.
- Event 대상 이름(`logs-nginx.access-*` 등)과 Alert alias는 #208 확정 전의 기본값이다. 실제 space와 데이터 스트림으로 바꾼다.
- 대상의 현재 상태(마지막 실행이 성공인지, 언제 돌았는지)는 `ingest_runs`에서 대상별 가장 최근 행(`started_at DESC`, 색인 있음)으로 읽는다. 체크포인트에는 실패 정보가 없다.
- 이력 보관 기간은 정하지 않았다. 행은 지우지 않고 계속 쌓인다(대상 6개 × cron 주기). 정리 방식은 따로 정한다.
- 시작·종료 시각은 벽시계(UTC)다. 실행 중 시계가 뒤로 가 `finished_at < started_at`이 되면 `record_run`이 `ContractError`를 내고 실행이 멈춘다(이력 쓰기는 `psycopg.Error`만 무시한다).
- 실제 ELK에서는 아직 확인하지 않았다. 합성 fixture와 `httpx.MockTransport`로만 검증했다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`(757 통과), `uv run pytest -m db`(183 통과; main의 #211·#212 테스트 포함), `uv run python scripts/generate_contracts.py --check`.
- DB 테스트는 로컬 Postgres(`DATABASE_URL`)에서 `uv run pytest -m db`로 183개 통과했다.
- 로컬 ELK(`.local/elk/`, 합성 데이터만)에서 손으로 확인: 600건 2페이지, 같은 `_id` 두 인덱스, 실패 후 재개(ELK 중지 → `ingest_runs`에 `network` 행 6개 기록, 재시작 후 `ok` 행과 새 문서 저장; `ingest_runs` 전환 뒤에 다시 확인했다), 늦은 문서 커서 비교.
- 연결: `tests/ingest/db/test_links_db.py`(1:N·N:1, 보류 후 연결, 프로필·kind 불일치, 롤백).
- 주요 테스트: `tests/ingest/db/test_store_db.py`(원자성·롤백·중복·이력), `tests/ingest/db/test_run_db.py`(실패 후 재개·이력), `tests/ingest/unit/test_elk.py`(페이징·오류 종류), `tests/ingest/unit/test_run.py`. 목록은 `tests/ingest/README.md`.
