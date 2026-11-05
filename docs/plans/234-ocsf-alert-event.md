---
issue: 234
date: 2026-11-05
owner: 미정 (이슈 담당자 확인 필요)
supersedes: []
---

# W02 — OCSF Alert/Event 정규화 구현

> 상태: 확정 계획. P01(#208), P05(#219), W01(#218), P06(#241)은 이슈 상태상 열려 있지만, 사용자가 현재 방향을 W02의 확정 가정으로 보고 진행하라고 지시했다(2026-11-05). 조직 ELK에서 확인하지 않은 필드는 계속 미확인으로 둔다. 선행 이슈의 결정이 다르면 이 계획과 구현을 다시 맞춘다.

## 목표

`raw_records`의 원본을 OCSF 1.9.0으로 정규화해 결과를 DB에 저장한다. `kind=alert` 원본은 `alerts`(Detection Finding 2004)에, `kind=event` 원본은 웹·클라우드 소스이면 `events`(HTTP Activity 4002 또는 API Activity 6003)에, 그 밖이면 `events`(Base Event 0)에 원본 한 건당 결과 한 건을 저장한다. 같은 원본을 다시 처리해도 결과가 중복되지 않고, 실패한 건은 그 건만 실패로 기록된다.

## 방법

### 입력과 대상

- 입력: `raw_records`의 `kind=alert`와 `kind=event` 원본. ELK hit의 `_source`를 읽으며, ECS 필드는 평평한 점 키를 먼저 찾고 없으면 중첩 경로를 읽는다.
- 대상 선택: 정규화 상태 테이블에서 성공하지 않았고 임대가 없거나 만료된 `raw_id`만 고른다(가정 P05-2).
- Endpoint 인덱스(`logs-endpoint.*`)의 Event는 이번 범위가 아니다. 이 계획은 W01이 수집한 5개 Event 소스(nginx, apache, CloudTrail, Azure, GCP)만 다룬다.

### 변환

**Alert (`kind=alert`) → Detection Finding 2004 → `alerts` 한 건**

| OCSF | 원본 (점 키) | 비고 |
|---|---|---|
| `time` | `kibana.alert.original_time` | 없으면 `@timestamp`(U-03) |
| `severity_id` | `kibana.alert.severity` | low→2, medium→3, high→4, critical→5. 알 수 없는 값은 0(Unknown) |
| `finding_info.title` | `kibana.alert.rule.name` | |
| `finding_info.uid` | 원본 `_id` | |
| `rule_id` (`alerts`) | `kibana.alert.rule.rule_id` | 없으면 null. 룰 ID 비교는 U-04 |
| `entities` | 확인된 엔티티 필드(아래 표) | |

**Event 웹 (`logs-nginx.*`, `logs-apache.*`) → HTTP Activity 4002 → `events` 한 건**

| OCSF | 원본 (ECS) |
|---|---|
| `time` | `@timestamp` |
| `src_endpoint.ip` | `source.ip` |
| `http_request.http_method` | `http.request.method` |
| `http_request.url.path` | `url.path` |
| `http_request.url.url_string` | `url.original` |
| `http_request.url.hostname` | `url.domain` |
| `http_request.user_agent` | `user_agent.original` |
| `http_response.code` | `http.response.status_code` |
| `activity_id` | `http.request.method`에서 아래 표로 고른다 |

- `http_request` 또는 `http_response` 중 하나는 있어야 한다(HTTP Activity의 `at_least_one`). 둘 다 없으면 실패다.
- `activity_id` 표: CONNECT 1, DELETE 2, GET 3, HEAD 4, OPTIONS 5, POST 6, PUT 7, TRACE 8, PATCH 9. 표에 없는 메서드는 99(Unspecified), 값이 없으면 0(Unknown)을 쓴다.

**Event 클라우드 (`logs-aws.cloudtrail.*`, `logs-azure.activitylogs.*`, `logs-gcp.audit.*`) → API Activity 6003 → `events` 한 건**

| OCSF | 원본 (ECS) | 비고 |
|---|---|---|
| `time` | `@timestamp` | |
| `api.operation` | `event.action` | 필수 |
| `api.service.name` | `event.provider` | 선택 속성 |
| `actor.user.name` | `user.name` | 필수. CloudTrail에서는 IAM 역할 이름이다 |
| `actor.user.uid` | `user.entity.id` | |
| `src_endpoint.ip` | `source.ip` | 필수. CloudTrail의 `source.ip`는 문서 미확인(U-06). 없으면 실패 |
| `cloud.provider` | `cloud.provider` | |
| `cloud.region` | `cloud.region` | |
| `cloud.account.uid` | `cloud.account.id` | |
| `activity_id` | `event.action`의 동사에서 아래 표로 고른다 | |

- `activity_id` 표(동사 접두사 기준): Create·Run·Start·Launch·Add는 1, Get·List·Describe·Head는 2, Update·Modify는 3, Delete·Remove는 4. 표에 없는 동사는 99(Unspecified), 값이 없으면 0(Unknown)이다. 표는 샘플로 검증한다.
- Azure·GCP는 같은 클래스로 매핑하되, 위 필드 대응은 CloudTrail 기준이다. 소스별 필드가 다르면 필수 필드 누락으로 실패한다(U-07).

**Event 그 밖 → Base Event 0 → `events` 한 건**: `time`과 `metadata`를 채우고, 요약은 `event.dataset` 또는 `event`를 쓴다. OCSF에 해당 필드가 없어 원본 `kind`는 넣지 않는다.

**엔티티(`entities`)**: 확인된 엔티티 필드만 쓴다. `source.ip` → `ip`, `host.name` → `host`, `user.name` → `user`, `url.domain` → `domain`, `url.original` → `url`. `process`와 `file_hash`는 현재 5개 소스에서 얻을 수 없으므로 비운다. `role`은 `src`(`source.ip`), `actor`(`user.name`)처럼 쓰고, 모르면 null이다.

### 검증

- 결과마다 `validate_contract()`와 OCSF 1.9.0 공식 클래스·객체 정의 기반 검증을 함께 통과해야 한다(D-007). 정의는 `src/soc/normalize/ocsf/`에 둔다(2004, 4002, 6003, 0).
- 한쪽이라도 실패하면 그 건은 `validation_failed` 또는 `schema_failed`로 실패 처리한다.

### 자산 조회 (P06 계획 적용)

- 정규화 중 확인된 엔티티마다 `asset_lookup`을 묶음 500개 단위로 한 번씩 호출한다(P06 바뀐 점).
- `asset_lookup_failed`는 그 건을 실패로 넘긴다. 빈 `assets`로 저장하지 않는다.
- 자산 테이블이 비어 있으면 성공한 no-match로 두고 계속한다(P06 바뀐 점).
- 자산 조회는 결과 저장과 같은 `DATABASE_URL` 연결을 쓴다(아래 바뀐 점).

### 저장과 상태 (가정 P05)

- 상태 테이블 `normalize_status`(마이그레이션 `0103`): `raw_id text PRIMARY KEY REFERENCES raw_records(id)`, `status text CHECK (status IN ('pending','succeeded','failed'))`, `error_code text NULL`, `attempts integer NOT NULL DEFAULT 0`, `last_attempt_at timestamptz NULL`, `lease_owner text NULL`, `lease_expires_at timestamptz NULL`, `result_kind text NULL CHECK (result_kind IN ('alert','event'))`, `result_id text NULL UNIQUE`.
- 임대: 작업자는 대상 행을 `UPDATE ... SET lease_owner, lease_expires_at = now() + 10분 ... RETURNING`으로 잡는다. 다른 작업자가 잡고 있고 임대가 만료되지 않았으면 건너뛴다.
- 결과 저장: 한 트랜잭션에서 (1) `normalize_status` 행을 `FOR UPDATE`로 잠그고 `lease_owner`가 자기 것인지, 임대가 만료되지 않았는지 확인, (2) `alerts` 또는 `events`에 결과 한 건 삽입, (3) 상태를 `succeeded`로 바꾸고 임대를 비움. 확인에 실패하면 아무것도 쓰지 않는다.
- 실패: 상태를 `failed`, `error_code`에 코드, `attempts`를 1 늘림, `last_attempt_at`을 기록한다. 원본 내용과 예외 메시지는 저장하지 않는다.
- 중복 방지: 상태 행의 기본 키와 잠금으로 막는다. 결과 위치(`result_kind`, `result_id`)는 상태 행에 적고, `result_id`에 유일 제약을 둔다. `alerts`와 `events`에는 제약을 추가하지 않는다. 별도 매핑 테이블은 두지 않는다.

### 실행기와 설정

- 실행: `uv run python -m soc.normalize`. 한 번 실행하고 끝난다. 주기 실행은 cron이 맡는다. 실패가 하나라도 있으면 종료 코드 1이다. W01 `soc.ingest`와 같은 형태다.
- 설정 `config/default.toml`의 `[normalize]`: `batch_size = 200`, `lease_seconds = 600`. 새 환경변수는 없다.

## 바꿀 곳

- `src/soc/normalize/`(새로 만듦): `alert.py`, `event_web.py`, `event_cloud.py`, `base.py`, `entities.py`, `store.py`, `__main__.py`
- `src/soc/db/migrations/0103_normalize_status.sql`(새로 만듦): 상태 테이블만(결과 위치 열 포함). `alerts`와 `events`는 바꾸지 않는다.
- `contracts/ocsf/`(새로 만듦): OCSF 1.9.0 공식 JSON Schema 4개(2004, 4002, 6003, 0). 파일마다 출처 버전을 적는다.
- `config/default.toml`: `[normalize]` 절
- `tests/fixtures/normalize/`(새로 만듦): 손으로 만든 샘플 원본과 기대 결과
- `tests/normalize/`(새로 만듦): 단위 테스트와 `-m db` 테스트
- `docs/notes/234-ocsf-alert-event.md`(개발 단계에서 만듦)

## 다른 코드와 맞물리는 곳

- W01(#218, PR #232): `raw_records`에 `kind=alert`와 `kind=event`를 모두 저장한다. 이 계획은 그 계약에 기댄다.
- P06(#241): `src/soc/asset_lookup.py`와 `0004_asset_lookup.sql`을 쓴다. 이 이슈가 만들지는 않는다.
- L2: `src/soc/entities.py::normalize_entity_value()`를 공용으로 쓴다. 이 이슈에서 규칙을 바꾸지 않는다.
- 공통 테이블(`alerts`, `events`)은 바꾸지 않는다. 결과 중복 방지는 상태 테이블이 맡는다.
- `alerts`·`events`의 `assets`: 계약 변경 후 형태(`entity: {type, value}`)를 따른다(P06).

## 범위 밖

- Ticket 생성, Ticket 묶기, `[ticketing]` 설정, Ticket 재처리 중복 방지. W04에서 구현한다(D-033 담당은 사람이 정한다).
- 로컬 룰 매칭으로 Event에서 Alert 만들기. Alert는 ELK가 룰로 만든 것만 `kind=alert`로 가져온다(아키텍처 원칙 6, #208 외부 전제).
- 알럿↔이벤트 연결 추출 코드와 `run.py` 호출. 후속 이슈다. `raw_links`와 `link_by_refs`는 W01 PR에 남는다.
- `logs-endpoint.*` Event 소스.
- 자산 데이터 입력·갱신(P06 범위 밖).
- L1 판정, Incident 묶음(L2), API 실행과 실시간 전달.

## 완료 기준

- [x] #208(P01), #219(P05), #218(W01), #241(P06)의 이슈 상태는 열림이다. 사용자의 2026-11-05 지시에 따라 현재 방향을 W02의 확정 가정으로 적용했다. 병합 전에 선행 이슈의 최종 결정과 다시 대조한다.
- [x] `kind=alert` 샘플은 `alerts` 한 건, 웹 샘플은 `events` 한 건(클래스 4002), 클라우드 샘플은 `events` 한 건(클래스 6003), 지원 밖 샘플은 Base Event 0 한 건이다.
- [x] 모든 결과가 `validate_contract()`와 해당 클래스의 OCSF 1.9.0 공식 클래스·객체 정의 검사를 통과한다.
- [x] `activity_id` 표가 샘플 메서드·동사에 맞게 적용된다. 표에 없는 값은 99, 값이 없으면 0이다.
- [x] 같은 원본을 두 번 처리해도 결과가 한 건만 남는다.
- [x] 샘플 한 건을 실패하게 하면 그 건만 `failed`로 기록되고, 나머지는 성공한다. 다음 실행에서 실패 건만 다시 고른다.
- [x] 결과 저장과 상태 갱신 사이에서 중단해도 중복 결과가 없다(트랜잭션 테스트).
- [x] 임대가 만료된 작업자의 늦은 결과는 저장되지 않는다(테스트).
- [x] `asset_lookup_failed`는 실패로 처리되고, 빈 `assets`로 저장되지 않는다.
- [x] CloudTrail에 `source.ip`가 없는 샘플은 OCSF 필수 속성 누락으로 `schema_failed` 처리한다.
- [x] 실패 기록에 원본 내용과 예외 메시지가 없다.
- [x] 원본(`raw_records.original`)이 처리 전후 같다(해시 비교).
- [x] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m db`가 통과한다. DB 테스트를 건너뛰면 완료 보고에 적는다.
- [x] `docs/notes/234-ocsf-alert-event.md`가 있다. U 항목의 현재 상태와 이 브랜치의 코드 `UNVERIFIED(U-NN)` 태그 목록(없음)을 적는다.

## 토론으로 정한 것

- 입력은 `raw_records.original`이다. 결과는 원본 한 건당 한 건이며, `kind`에 따라 `alerts` 또는 `events`로 간다(2026-11-05).
- 형식은 OCSF 1.9.0이고 라이브러리 없이 직접 구현한다(D-007).
- Alert는 ELK가 룰로 만든 것만 가져온다. 프로젝트는 `kind=event`에서 Alert를 만들지 않는다(2026-11-05).
- 룰에 걸린 이벤트는 양쪽(원본 이벤트 `events`, 알럿 원본 `alerts`)에 모두 저장한다(2026-11-05). 두 결과는 따로 정규화한다.
- 최초 Event 범위는 웹·클라우드다. `logs-endpoint.*`는 이번 범위가 아니다(2026-11-05).
- Ticket 생성과 묶기는 이 이슈 범위가 아니다. W04에서 한다(2026-11-05).
- 자산 Lookup은 P06 계획을 따른다. 결과는 정규화 시점의 스냅샷으로 저장한다(2026-11-05).
- 알럿↔이벤트 연결 추출은 후속 이슈다. `raw_link`는 공통 계약이 아니며 내부 테이블이다(2026-11-05).
- 연결 필드는 `kibana.alert.ancestors`다. `type`이 `event`인 항목의 `index`·`id`로 `siem_ref`를 만든다. `signal`은 연결하지 않는다(2026-11-05).
- Event 커서는 `event.ingested` 방향이다. 기본값은 조직 ELK에서 필드를 확인한 뒤 바꾼다(U-02).
- 개발·테스트 기준 데이터셋은 `TocharianOU/secops-es-benchmark`다(CC-BY-4.0 데이터, Apache-2.0 코드). 원본은 `data/`에만 두고 커밋하지 않는다. 확정은 `docs/decisions.md` 안건으로 올린다.
- 정규화 실패는 건별로 기록하고, 나머지는 계속 처리한다. 실패 건은 다음 실행에서 다시 고른다.

### 확정 전 가정 (P01·P05 — 이슈 결정과 다르면 이 계획을 고친다)

| 번호 | 가정 | 확인할 이슈 |
|---|---|---|
| P01-1 | 최초 Event 클래스는 웹 4002, 클라우드 6003, 그 밖 0이다 | #208 |
| P01-2 | 위 변환 표(필드 대응, `activity_id` 표)가 P01 입력 매핑이다 | #208 |
| P01-3 | 조회 대상은 W01 설정의 5개 Event 소스와 Alert 별칭이다 | #208 |
| P05-1 | 정규화 상태 테이블은 `normalize_status`이고 열은 위와 같다 | #219 |
| P05-2 | 임대 시간은 10분이고, 만료 후 다음 실행이 다시 잡는다 | #219 |
| P05-3 | 결과 저장 때 상태 행을 잠그고 임대 소유를 확인한다 | #219 |
| P05-4 | 마이그레이션 번호는 `0103`이다 | #219 |
| P05-5 | 상태 테이블이 원본 한 건당 결과 한 건을 보장한다. `alerts`·`events`에는 유일 제약을 추가하지 않는다 | #219 |
| P05-6 | 실행 간 재시도는 횟수 제한 없이 이어지고, 실패 건은 다음 실행에서 다시 고른다 | #219 |

### 미확인 항목 (필드 확인 후 한 번에 고침)

조직 ELK에서 아직 확인하지 못한 필드다. 확인되면 "임시 처리"를 "확정 값"으로 바꾸고 "고칠 곳"의 코드와 설정을 함께 고친다. U 번호는 이 표를 기준으로 하며, 코드 주석 태그는 추적에 필요한 경우에만 둔다.

| ID | 무엇을 모르는가 | 임시 처리 | 확인 방법 | 고칠 곳 |
|---|---|---|---|---|
| U-01 | 알럿이 가리키는 원본 이벤트의 키. 연결 필드는 `kibana.alert.ancestors`다. 기준 데이터셋에서 알럿 52건 모두 이 필드를 가지고, `event` 항목 54개의 `index`는 전부 `logs-endpoint.*`다 | 연결하지 않는다. 연결 추출은 후속 이슈 | 조직 ELK 알럿 한 건의 `ancestors` 모양과, 그 `index`가 Event 조회 대상에 드는지 확인 | 연결 추출 코드(후속), `raw_links`(#218) |
| U-02 | 이벤트 커서 `event.ingested`가 실제 색인에 자동으로 들어가는지 | 커서는 `@timestamp` | `_search?size=1&filter_path=hits.hits._source.event.ingested` | `config`의 `time_field`(#218) |
| U-03 | 모든 룰 종류에서 `kibana.alert.original_time`이 채워지는지 | 없으면 `@timestamp` | 룰 종류별 알럿 문서 확인 | Alert `time` 매핑 |
| U-04 | `kibana.alert.rule.rule_id`가 사용자가 정한 룰 ID인지 | `rule_id`로 쓴다 | 룰 생성 후 값 비교 | Alert `rule_id` |
| U-05 | 알럿에 `event.category`·`event.type`이 복사되는 룰 종류 | 없으면 비운다 | 룰 종류별 확인 | Alert 정규화 |
| U-06 | CloudTrail에 `source.ip`가 있는지 | 없으면 OCSF 필수 속성 누락으로 실패(`schema_failed`) | 실제 CloudTrail 문서 확인 | 클라우드 변환 |
| U-07 | Azure·GCP의 ECS 필드 대응 | CloudTrail 기준 대응을 쓰고, 빠지면 실패 | 소스별 통합 문서 확인 | 클라우드 변환 |
| U-08 | 알럿 별칭과 Event 대상 키. ELK 기본 별칭은 `.alerts-security.alerts-default`, 개발 데이터셋 별칭은 `benchmark-alerts-security`; Event 키는 W01 설정의 5개 패턴이다 | `config` 기본값 | #208 확정 값과 맞춘다 | `config`(#218) |
| U-09 | 조직의 Elastic 버전(7.x는 `signal.*`, 8.x는 `kibana.alert.*`) | 8.x 이후 이름 | 클러스터 버전 확인 | 필드 이름 전체 |

## 바뀐 점

- 2026-11-05 · P01·P05·W01·P06 이슈가 열린 상태여도 현재 방향을 확정 가정으로 보고 진행하라는 사용자 지시에 따라 W02 구현을 진행한다. 이슈가 닫혔거나 병합됐다는 뜻은 아니며, 병합 전 최종 선행 결정을 대조한다.
- 2026-11-05 · 자산 조회는 읽기 계정(`AGENT_DATABASE_URL`)이 아니라 정규화가 쓰는 `DATABASE_URL` 연결로 한다(사람 결정, P06 계획 바뀐 점의 읽기 계정 결정을 바꿈). 그래서 `0004`에 `GRANT`가 없고 `docs/security.md`는 바꾸지 않으며, `[asset_lookup]`에는 `statement_timeout_ms`만 둔다(문장 시간 상한은 조회 트랜잭션에만 적용).
- 2026-11-05 · OCSF 검증은 공식 클래스별 JSON Schema 대신 OCSF 서버의 1.9.0 클래스·객체 정의로 한다(D-007 해석 변경, 사람 승인 B안). OCSF가 클래스별 JSON Schema 파일을 배포하지 않아서다. 정의 파일은 `contracts/ocsf/`가 아니라 `src/soc/normalize/ocsf/`에 둔다(`tests/test_contracts.py`가 `contracts/` 아래 모든 `*.schema.json`을 계약으로 세기 때문). 출처와 만든 방법은 `ocsf/SOURCE.md`.
- 2026-11-05 · P06(#241)이 인계한 산출물을 이 이슈에서 만든다: `src/soc/entities.py`, `src/soc/asset_lookup.py`, `0004_asset_lookup.sql`, Asset 계약 변경(`entity: {type, value}`), `[asset_lookup]` 설정. 위 "다른 코드와 맞물리는 곳"의 "이 이슈가 만들지는 않는다"를 고친다.
- 2026-11-05 · 파일 구성은 `mapping.py` 하나로 시작했다(`alert.py`, `event_web.py`, `event_cloud.py`로 나누지 않음).
- 2026-11-05 · `cloud` 프로필 속성(`cloud.provider`, `cloud.region`, `cloud.account.uid`)은 매핑하지 않는다. 프로필을 켜면 `cloud`가 필수가 되어 검증 조건이 달라진다.
- 2026-11-05 · 클라우드 이벤트의 `api.service.name`은 필수가 아니다(OCSF에서 선택). `src_endpoint`가 없으면 `validation_failed`가 아니라 `schema_failed`로 실패한다.
- 2026-11-05 · `http_method`는 `activity_id` 표에 있는 메서드만 내보낸다. 표에 없는 메서드·동사는 `activity_id` 99, 값이 없으면 0이다. Alert 심각도를 모르면 `severity` 0이다.
- 2026-11-05 · 이벤트 원본 필드는 평평한 점 키를 먼저, 없으면 중첩 경로를 읽는다(알럿의 `kibana.alert.*`는 평평한 키, ECS 이벤트 필드는 중첩 객체인 실제 입력에 맞춤).
- 2026-11-05 · Base Event(0)는 원본 `kind`를 담지 않는다(OCSF에 해당 속성이 없다). 엔티티의 `url`은 `url.original`만 쓰고, 웹 이벤트는 `url.original`을 `http_request.url.url_string`에도 담는다.
- 2026-11-05 · 임대는 원본 한 건이 아니라 한 묶음에 건다(`lease_seconds`). 쓰기 DB 접속 시간 상한 `[normalize] connect_timeout_seconds`를 더했다. `validate_ocsf`는 `class_uid`를 받지 않고 객체의 `class_uid`를 쓴다.
- 2026-11-05 · 한 번 실행은 배치 한 번만 처리한다. 대상은 시도한 지 오래된 순서이고, 아직 시도하지 않은 원본이 먼저다.
- 2026-11-05 · `alerts.raw_id`·`events.raw_id` 유일 제약(P05-5)을 빼고, 결과 중복 방지를 상태 테이블(`normalize_status`)의 기본 키·잠금과 `result_id` 유일 제약으로 바꿨다. 공통 테이블은 바꾸지 않으므로 승인이 필요 없다. 별도 매핑 테이블은 두지 않는다.
