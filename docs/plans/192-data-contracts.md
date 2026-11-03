---
issue: 192
date: 2026-11-03
owner: Pandyo
supersedes: []
---

# 공통 데이터 계약과 DB 테이블 만들기

## 목표

L1·L2·L3 병렬 개발을 시작하기 전에 공통 기반을 만들어 머지한다. 대상은 단계끼리 주고받는 데이터 7가지(RawRecord, Alert, Event, Ticket, Incident, Case, Agent Log)와 공통 조각 3개(Entity, Asset, Verdict)다. 이들의 계약(JSON Schema), Python 생성 코드, 검증·ID·시각 변환 함수, PostgreSQL 테이블과 마이그레이션 실행기, CI 검사를 만든다.

이 이슈는 "그릇"만 만든다. 테이블을 읽고 쓰는 코드, Ticket 생성 모드의 동작, 판정·분석 로직은 각 단계 이슈가 만든다.

## 방법

### 1. 공통 규칙

| 항목 | 규칙 |
|---|---|
| ID | 접두사 + UUIDv7 문자열(소문자 16진수). 만든 순서대로 정렬된다. 접두사: `raw_`(원본), `alt_`(Alert), `evt_`(Event), `tkt_`(Ticket), `inc_`(Incident), `cas_`(Case), `agl_`(Agent Log), `run_`(Agent Log의 작업 묶음). 예: `tkt_0192f3c5-7b2e-7a10-9c3d-1f2e3a4b5c6d` |
| 시각 | UTC epoch 밀리초 정수(OCSF 시각과 같은 단위). 예: `1793678580123`. DB 컬럼은 `timestamptz`이고, 변환은 공통 함수(`to_datetime`, `to_epoch_ms`)로 한다 |
| 심각도 | OCSF severity_id 정수 0~6. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal |
| 엔티티 | `{type, value, role}` 객체 목록(아래 Entity) |
| 추가 필드 | 계약이 정한 객체는 최상위와 안쪽(Entity, Asset, Verdict, Triage) 모두 정의하지 않은 필드를 거부한다(`additionalProperties: false`). 모양을 정하지 않는 자유 객체는 `details`, `original`, `ocsf`, `input`, `output`뿐이다. 계약에 없는 값은 `details`에만 넣고, 다른 단계는 남의 `details`를 읽지 않는다 |
| 필드 이름 | snake_case |

### 2. 공통 조각 (`contracts/common/`)

**Entity** (`entity.schema.json`)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `type` | 목록 값 | 예 | `ip`, `host`, `user`, `domain`, `url`, `file_hash`, `process` |
| `value` | 문자열(빈 값 불가) | 예 | 엔티티 값 |
| `role` | 목록 값 또는 null | 예 | `src`, `dst`, `actor`, `target`, null(역할 모름) |

**Asset** (`asset.schema.json`, Lookup으로 붙인 자산 정보)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `entity_value` | 문자열 | 예 | 어느 엔티티의 자산 정보인지 |
| `name` | 문자열 또는 null | 예 | 자산 이름 |
| `criticality` | 정수 1~5 또는 null | 예 | 중요도(5가 가장 중요). 범위를 바꾸려면 공통 계약 변경 절차를 따른다 |
| `owner` | 문자열 또는 null | 예 | 담당 부서·사람 |

**Verdict** (`verdict.schema.json`, L1 판정. Alert의 1차 판정과 Ticket 판정이 같은 모양을 쓴다)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `decision` | 목록 값 | 예 | `benign`, `malicious`, `undetermined` |
| `confidence` | 숫자 0~1 | 예 | |
| `reason` | 문자열 | 예 | 판정 이유 |
| `evidence_ids` | ID 목록 | 예 | 판정 근거. Alert·Event ID(`alt_`, `evt_`)와 도구 호출 기록 ID(`agl_`). 그 밖의 접두사는 거부한다 |
| `decided_at` | 시각 | 예 | |

### 3. Ticket 생성 모드 (필드와 설정 키만)

교수님 답변(2026-11-03)은 다음과 같다. 기업마다 다르지만, 금융당국이 요구하는 감사·증적용 알럿은 강제로 Ticket을 만들고, 나머지(헌팅, 저수준 위협)는 그렇지 않다. 강제로 Ticket을 만들 알럿은 알럿(룰) ID 기반으로 정적으로 설정한다.

그런 구조가 없는 기업도 쓸 수 있게, 기본은 모든 알럿을 Ticket으로 만들고 시나리오 기반 승격은 설정으로 켠다.

**기본 모드 `auto`** (`[ticketing] mode = "auto"`, 기본값)

```
정규화된 Alert (전부) ──▶ Ticket(origin=auto, status=new) ──▶ L1 Ticket 판정 ──▶ closed | held | escalated
```

**시나리오 모드 `scenario`** (`[ticketing] mode = "scenario"`, `scenario_rule_ids = ["...", ...]`)

```
정규화된 Alert
 ├─ rule_id가 scenario_rule_ids에 있음
 │    ──▶ Ticket(origin=scenario, status=new) ──▶ L1 Ticket 판정 ──▶ closed | held | escalated
 └─ 없음 (rule_id가 null이어도 여기)
      ──▶ Alert.triage = {status: pending}
      ──▶ L1 1차 판정
           ├─ 승격 ──▶ triage.status = promoted, Ticket(origin=l1, status=new) ──▶ L1 Ticket 판정
           └─ 보류 ──▶ triage.status = held (Ticket을 만들지 않음. 오탐을 확신해도 held)
```

- 시나리오 일치 Ticket도 L1 Ticket 판정을 거친다. 핵심은 감사·증적용 알럿에 "Ticket이 반드시 남는 것"이다.
- 시나리오 설정은 룰 ID 목록만 둔다(목적 구분 없음).
- 설정 키: `[ticketing] mode`(`auto` | `scenario`, 기본 `auto`), `[ticketing] scenario_rule_ids`(문자열 목록, 기본 빈 목록).
- 이 이슈는 필드(`Alert.rule_id`, `Alert.triage`, `Ticket.origin` 값)와 설정 키 이름만 정한다. 모드 동작(설정 읽기, 일치 판단, Ticket 생성, `config/default.toml`에 키 넣기)은 수집·정규화 이슈가, L1 1차 판정은 L1 이슈가 만든다.

### 4. 데이터별 계약

#### 4-1. 원본 RawRecord (`contracts/raw_record.schema.json`)

SIEM에서 가져온 Alert·Event를 바꾸지 않고 그대로 보관한다. Alert와 Event가 같은 모양을 쓴다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | `raw_` ID | 예 | |
| `kind` | 목록 값 | 예 | `alert`, `event` |
| `siem_profile` | 문자열 | 예 | 가져온 SIEM 연결 프로필 이름 |
| `siem_ref` | 문자열 | 예 | SIEM 안에서 문서 하나를 가리키는 값. ELK는 `<_index>/<_id>`(ELK `_id`는 인덱스 안에서만 유일하다) |
| `fetched_at` | 시각 | 예 | 가져온 시각 |
| `original` | 객체 | 예 | SIEM이 준 JSON 그대로 |

#### 4-2. Alert (`contracts/alert.schema.json`)

들어오는 즉시 OCSF 1.9.0 Detection Finding(class_uid 2004)으로 정규화한다. OCSF 전체는 `ocsf`에 두고, 단계들이 자주 읽는 값은 바깥 필드로 꺼내 둔다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | `alt_` ID | 예 | |
| `raw_id` | `raw_` ID | 예 | 원본 |
| `time` | 시각 | 예 | 알럿 발생 시각 |
| `severity` | 심각도 0~6 | 예 | |
| `title` | 문자열 | 예 | 한 줄 요약(룰 이름 등) |
| `rule_id` | 문자열 또는 null | 예 | 알럿을 만든 SIEM 탐지 룰 ID. 시나리오 모드의 일치 판단에 쓴다. 룰 ID가 없는 알럿은 null |
| `entities` | Entity 목록 | 예 | 빈 목록 가능 |
| `assets` | Asset 목록 | 예 | 빈 목록 가능 |
| `triage` | Triage 또는 null | 예 | 시나리오 모드에서 일치하지 않은 알럿의 L1 1차 판정. 기본 모드와 시나리오 일치 알럿은 null |
| `ocsf` | 객체 | 예 | Detection Finding 전체. `class_uid`는 2004여야 한다(schema `const`로 검사) |
| `details` | 객체 | 예 | 빈 객체 가능 |

**Triage** (`alert.schema.json` 안에 정의)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `status` | 목록 값 | 예 | `pending`(L1 1차 판정 대기), `promoted`(Ticket으로 승격), `held`(보류, Ticket 없음) |
| `verdict` | Verdict 또는 null | 예 | L1 1차 판정 결과 |

- `status`와 `verdict`의 짝(schema if/then으로 검사): `pending`이면 verdict는 null, `promoted`이면 verdict 필수, `held`이면 verdict 없어도 된다(판정 실패).
- L1은 `triage.status = pending`인 Alert만 1차 판정한다.

예시 (기본 모드, ELK SQL 인젝션 알럿을 정규화한 결과)

```json
{
  "id": "alt_0192f3c4-7b2e-7a10-9c3d-1f2e3a4b5c6d",
  "raw_id": "raw_0192f3c4-7b2e-7a10-9c3d-1f2e3a4b5c6c",
  "time": 1793678578000,
  "severity": 4,
  "title": "SQL Injection Attempt",
  "rule_id": "9f1e2d3c-4b5a-6789-0abc-def012345678",
  "entities": [
    {"type": "ip", "value": "203.0.113.10", "role": "src"},
    {"type": "ip", "value": "198.51.100.5", "role": "dst"},
    {"type": "host", "value": "web-01", "role": "dst"}
  ],
  "assets": [
    {"entity_value": "web-01", "name": "웹서버", "criticality": 5, "owner": null}
  ],
  "triage": null,
  "ocsf": {
    "class_uid": 2004,
    "severity_id": 4,
    "time": 1793678578000,
    "finding_info": {"title": "SQL Injection Attempt", "uid": "9f1e2d3c-4b5a-6789-0abc-def012345678"},
    "src_endpoint": {"ip": "203.0.113.10"},
    "dst_endpoint": {"ip": "198.51.100.5", "hostname": "web-01"}
  },
  "details": {}
}
```

#### 4-3. Event (`contracts/event.schema.json`)

들어오는 즉시 OCSF 1.9.0으로 정규화한다. 맞는 이벤트 클래스(예: HTTP Activity 4002)로 매핑하고, 맞는 클래스가 없으면 Base Event(class_uid 0)로 매핑한다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | `evt_` ID | 예 | |
| `raw_id` | `raw_` ID | 예 | |
| `time` | 시각 | 예 | 이벤트 발생 시각 |
| `ocsf_class` | 정수 | 예 | OCSF class_uid. 맞는 클래스가 없으면 0 |
| `summary` | 문자열 | 예 | 한 줄 요약 |
| `entities` | Entity 목록 | 예 | |
| `assets` | Asset 목록 | 예 | |
| `ocsf` | 객체 | 예 | 매핑한 클래스 전체. `class_uid`는 `ocsf_class`와 같아야 한다(schema로 쓸 수 없어 `validate_contract()`의 추가 검사로 확인) |
| `details` | 객체 | 예 | |

정규화가 실패했을 때의 처리는 정규화 담당자가 그 단계 이슈에서 정한다. 이 계약은 정규화에 성공한 결과의 모양만 정한다.

#### 4-4. Ticket (`contracts/ticket.schema.json`)

L1 Ticket 판정의 단위다. 여러 Alert를 한 Ticket에 묶을 수 있다(같은 공격이 반복되는 경우). 묶는 기준은 수집·정규화·L1 담당자가 정한다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | `tkt_` ID | 예 | |
| `origin` | 목록 값 | 예 | `auto`(기본 모드), `scenario`(시나리오 일치), `l1`(L1 1차 판정으로 승격), `l3`(L3 헌팅 발견) |
| `status` | 목록 값 | 예 | 아래 상태 표 |
| `alert_ids` | `alt_` ID 목록 | 예 | `origin`이 `auto`, `scenario`, `l1`이면 1개 이상. `l3`이면 빈 목록 가능(schema if/then) |
| `entities` | Entity 목록 | 예 | 소속 Alert 엔티티를 모은 것 |
| `verdict` | Verdict 또는 null | 예 | L1 Ticket 판정. `status = new`이면 null(schema if/then) |
| `created_at` | 시각 | 예 | |
| `updated_at` | 시각 | 예 | |
| `details` | 객체 | 예 | |

**상태와 바꾸는 쪽**

| 상태 | 뜻 | 누가 이 상태로 바꾸나 |
|---|---|---|
| `new` | L1 Ticket 판정 대기 | 수집·정규화(`auto`, `scenario` Ticket 생성 시), L1(`l1` Ticket 생성 시) |
| `closed` | 오탐으로 종결 | L1 |
| `held` | 보류(확신 부족, 판정 실패) | L1 |
| `escalated` | L2 대기 | L1. L3는 Ticket을 처음부터 이 상태로 만든다 |
| `linked` | Incident에 붙음 | L2 |

L1은 `new`인 Ticket만, L2는 `escalated`인 Ticket만 가져간다. 출처 값 추가는 공통 계약 변경이라 L1·L2·L3 담당자 전원의 승인이 필요하다(Ticket 출처, D-026).

#### 4-5. Incident (`contracts/incident.schema.json`)

같은 공격으로 보이는 Ticket들의 묶음이다. L2 분석과 사람 검토의 단위다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | `inc_` ID | 예 | |
| `title` | 문자열 | 예 | L2가 정함 |
| `summary` | 문자열 또는 null | 예 | 분석 요약. L2가 채운다. 분석 전 null |
| `status` | 목록 값 | 예 | 아래 상태 표 |
| `ticket_ids` | `tkt_` ID 목록 | 예 | 1개 이상 |
| `entities` | Entity 목록 | 예 | 소속 Ticket 엔티티를 모은 것 |
| `severity` | 심각도 0~6 | 예 | 소속 Alert 심각도 중 최대. 코드가 계산한다. 소속 Alert가 없으면(L3 Ticket만 있으면) 0 |
| `assessed_severity` | 심각도 0~6 또는 null | 예 | L2 분석이 판단한 심각도. 분석 전 null |
| `analysis_round` | 정수 0 이상 | 예 | L2 분석 횟수 |
| `review_round` | 정수 0 이상 | 예 | 사람 검토 횟수 |
| `created_at` | 시각 | 예 | |
| `updated_at` | 시각 | 예 | |
| `details` | 객체 | 예 | |

**상태와 바꾸는 쪽**

| 상태 | 뜻 | 누가 이 상태로 바꾸나 |
|---|---|---|
| `analyzing` | L2 분석 필요·중 | L2(생성할 때, 재분석이 필요할 때), 사람(화면에서 반려 사유를 붙여 재분석을 요청할 때) |
| `awaiting_review` | 사람 검토 대기 | L2(분석 완료) |
| `confirmed` | 사람이 승인. Case 생성 | 사람(화면) |
| `human_handling` | 반려 한도에 도달해 사람이 직접 처리 | 사람(화면) |
| `dismissed` | 위협이 아니라고 판단해 종결 | L2(위협이 아니라고 판단할 때), 사람(화면. `awaiting_review`에서 위협이 아니라고 판단할 때, `human_handling`을 끝낼 때) |

- Case로 가는 승인(`confirmed`)은 사람만 한다.
- 재분석 한도, 반려 한도, 새 Ticket이 붙었을 때 다시 분석할지는 L2 담당자가 설정으로 정한다.

#### 4-6. Case (`contracts/case.schema.json`)

사람이 확정한 Incident다. 승인 시점의 내용을 복사해 둔다. 이후 Incident가 바뀌어도 Case는 확정 당시 내용을 유지한다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | `cas_` ID | 예 | |
| `incident_id` | `inc_` ID | 예 | Incident 하나에 Case 하나 |
| `title` | 문자열 | 예 | 승인 시점 Incident 제목 |
| `summary` | 문자열 또는 null | 예 | 승인 시점 Incident `summary`를 그대로 복사 |
| `severity` | 심각도 0~6 | 예 | 승인 시점 `assessed_severity`, 없으면 `severity` |
| `entities` | Entity 목록 | 예 | 승인 시점 엔티티 |
| `confirmed_by` | 문자열 | 예 | 승인한 사람. 사용자 계정(D-020)이 생기기 전에는 이름 문자열 |
| `confirmed_at` | 시각 | 예 | |
| `status` | 목록 값 | 예 | `open` → `in_progress` → `resolved`. 사람이 화면에서 바꾼다 |
| `assignee` | 문자열 또는 null | 예 | 담당 분석가 |
| `resolved_at` | 시각 또는 null | 예 | `status = resolved`이면 필수, 그 밖에는 null(schema if/then) |
| `details` | 객체 | 예 | |

#### 4-7. Agent Log (`contracts/agent_log.schema.json`)

에이전트의 모델 호출·도구 호출 한 번이 한 줄이다. 같은 작업(판정 한 번, 분석 한 번)의 호출들은 `run_id`로 묶고 `seq`로 순서를 둔다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | `agl_` ID | 예 | |
| `run_id` | `run_` ID | 예 | 같은 작업의 호출을 묶는 ID. `new_id("run")`으로 만든다 |
| `stage` | 목록 값 | 예 | `l1`, `l2`, `l3` |
| `subject_type` | 목록 값 | 예 | `alert`(L1 1차 판정), `ticket`, `incident`, `hunt` |
| `subject_id` | 문자열 | 예 | 대상 ID |
| `seq` | 정수 1 이상 | 예 | 작업 안 순번. `(run_id, seq)`는 유일 |
| `kind` | 목록 값 | 예 | `model`, `tool` |
| `name` | 문자열 | 예 | 모델 이름 또는 도구 이름 |
| `input` | JSON 값 | 예 | 입력 전체 |
| `output` | JSON 값 또는 null | 예 | 출력 전체. 실패해 출력이 없으면 null |
| `outcome` | 목록 값 | 예 | `ok`, `error` |
| `tokens_in` | 정수 0 이상 또는 null | 예 | 모델 호출만. 도구 호출은 null |
| `tokens_out` | 정수 0 이상 또는 null | 예 | 모델 호출만 |
| `started_at` | 시각 | 예 | |
| `duration_ms` | 정수 0 이상 | 예 | |
| `details` | 객체 | 예 | |

- 입출력은 전부 PostgreSQL에 저장한다. 성능 문제가 생기면 NoSQL을 다시 논의한다(Agent Log 저장, D-036).
- 입출력에는 로그 원문과 공격자가 쓴 문자열이 들어간다. 화면에서는 텍스트로만 표시한다(`docs/security.md` "화면").
- 비밀 값(API 키, 비밀번호)은 입출력에 넣지 않는다.

### 5. 계약 파일과 생성 코드

```
contracts/
  common/
    entity.schema.json
    asset.schema.json
    verdict.schema.json
  raw_record.schema.json
  alert.schema.json          ← Triage는 이 파일 안에 정의
  event.schema.json
  ticket.schema.json
  incident.schema.json
  case.schema.json
  agent_log.schema.json
src/soc/contracts/generated/ ← Python(Pydantic v2). 직접 수정 금지
```

- JSON Schema draft-07로 쓰고, 파일마다 `$id`를 둔다. 파일 사이는 `$ref`로 가리킨다.
- if/then으로 쓸 수 있는 규칙(`alert_ids` 개수, 상태와 짝 필드)은 schema에 쓴다.
- `scripts/generate_contracts.py` 하나로 Python 코드를 만든다.
  - datamodel-code-generator로 Pydantic v2 모델을 만든다. `--disable-timestamp`로 머리말에 생성 시각을 넣지 않고, 도구 버전은 `uv.lock`으로 고정한다.
  - 생성 직후 프로젝트 ruff로 `format`과 `check --fix`를 돌려, 생성 결과가 저장소 검사를 그대로 통과하게 한다.
  - `--check`를 주면 임시 폴더에 다시 생성해 커밋된 코드와 차이가 있는지만 검사한다.
- `pyproject.toml`의 `per-file-ignores`로 `src/soc/contracts/generated/`에서만 E501을 끈다(생성 코드 린트 예외, D-038). 포맷 검사와 나머지 린트는 그대로다.
- TypeScript 생성(json-schema-to-typescript)은 Node 설정, CI와 함께 첫 화면 이슈에서 붙인다.

### 6. 검증·ID·시각 함수

**`soc.contracts.validate_contract(name, data)`**

- `name`은 schema 파일 이름(확장자 앞)이다: `raw_record`, `alert`, `event`, `ticket`, `incident`, `case`, `agent_log`, `entity`, `asset`, `verdict`.
- 순서: ① 원본 JSON Schema로 검사(if/then 포함) → ② schema로 쓸 수 없는 규칙 검사(Event `ocsf_class`와 `ocsf.class_uid` 비교) → ③ 생성된 Pydantic 모델로 바꿔 돌려준다.
- 실패하면 `ContractError`를 낸다. 예외에는 틀린 필드의 경로와 어긴 규칙만 담고, 입력 값은 담지 않는다(공격자 문자열이나 큰 원본이 로그로 흘러가지 않게).
- schema 파일은 레포 루트의 `contracts/`에서 읽는다(`uv sync`로 설치한 개발 환경 기준). 배포 형태가 정해지면 그때 바꾼다.

**`soc.ids.new_id(prefix)`**

- `prefix`는 `raw`, `alt`, `evt`, `tkt`, `inc`, `cas`, `agl`, `run` 중 하나다. 그 밖은 `ValueError`.
- UUIDv7(RFC 9562)은 라이브러리 없이 직접 구현한다. 같은 밀리초 안에서도 만든 순서가 지켜지게 카운터를 둔다(ID 생성, D-034).
- 순서 보장은 한 프로세스 안에서만이다. 프로세스끼리는 밀리초 단위까지만 맞는다.

**시각 변환 (`soc.contracts`)**

- `to_datetime(ms)`: epoch 밀리초 정수 → UTC 시간대가 붙은 `datetime`.
- `to_epoch_ms(dt)`: 시간대가 붙은 `datetime` → epoch 밀리초 정수. 시간대가 없는 `datetime`은 거부하고, 밀리초 아래 자리는 버린다.

### 7. DB

**마이그레이션** (마이그레이션 방식, D-035)

- `src/soc/db/migrations/`에 순번 SQL 파일을 두고 `uv run python -m soc.db.migrate`로 적용한다. 이 이슈는 `0001_common_tables.sql`.
- 번호 대역: 0001~0099 공통, 0100~0199 수집·정규화·L1, 0200~0299 L2, 0300~0399 L3.
- 적용한 번호를 `schema_migrations` 테이블에 기록하고, 아직 적용하지 않은 파일만 번호 순서대로 실행한다.
- 파일 하나를 트랜잭션 하나로 실행하고, `schema_migrations` 기록도 같은 트랜잭션에 넣는다. 실패하면 그 파일만 되돌리고, 뒤 파일은 실행하지 않고, 0이 아닌 코드로 끝낸다.
- 같은 번호의 파일이 둘이면 아무것도 실행하지 않고 실패한다.
- 이미 적용한 파일은 고치지 않고 새 번호를 만든다. 파일은 자기보다 작은 번호의 파일이 만든 테이블만 참조한다(빈 DB에서는 번호 순서로 실행되므로).
- 연결 주소는 환경변수 `DATABASE_URL`(`.env.example`에 이미 있음). 실행기는 주소를 인자로 받는 함수와, 환경변수를 읽어 그 함수를 부르는 `python -m` 진입점으로 나눈다.
- `DATABASE_URL`이 없으면 변수 이름만 알리고 끝낸다. 주소(비밀번호 포함)는 출력·로그·예외 메시지에 넣지 않는다.

**테이블**

- `raw_records`, `alerts`, `events`, `tickets`, `incidents`, `cases`, `agent_logs`, `schema_migrations`.
- 컬럼 이름은 계약 최상위 필드 이름과 같다.
- 시각 필드는 `timestamptz`.
- `original`, `ocsf`, `entities`, `assets`, `triage`, `verdict`, `details`, `input`, `output`은 `jsonb`.
- `alert_ids`, `ticket_ids`는 `text[]`.
- 계약에서 null이 될 수 없는 필드는 `NOT NULL`.

**제약과 인덱스**

- `raw_records(siem_profile, siem_ref)` 유일: 같은 SIEM 문서를 두 번 저장하지 않는다.
- `alerts.raw_id`, `events.raw_id` → `raw_records.id` 외래 키. 삭제 동작은 기본(삭제를 막음)으로 둔다. 원본 보관 기간(D-008)이 지나 지우는 기능을 만드는 이슈가 이 동작을 정한다.
- `cases.incident_id` → `incidents.id` 외래 키, 유일.
- 상태 인덱스: `tickets(status)`, `incidents(status)`, `alerts`의 `triage->>'status'` 식 인덱스.
- `alerts(rule_id)` 인덱스.
- `tickets(alert_ids)`, `incidents(ticket_ids)` GIN 인덱스.
- `agent_logs(subject_type, subject_id)` 인덱스, `agent_logs(run_id, seq)` 유일 인덱스.
- CHECK 제약: 최상위 컬럼의 목록 값(상태, 출처, `kind`, `stage`, `subject_type`, `outcome`), 숫자 범위(심각도 0~6, `seq` 1 이상, 횟수·시간·토큰 0 이상), `triage->>'status'`. `jsonb` 안쪽(`entities[].type`, `verdict.decision` 등)은 `validate_contract()`만 검사한다.

### 8. 테스트

- `tests/fixtures/contracts/`에 데이터마다 손으로 만든 올바른 샘플과 틀린 샘플을 둔다. IP는 문서용 대역, 도메인은 `example.com`, 계정은 가짜 이름.
- DB가 필요한 테스트는 `db` 마커를 붙인다. 테스트는 `DATABASE_URL`로 접속해 임시 DB(`soc_test_<랜덤>`)를 만들고, 끝나면 지운다. 개발 DB의 테이블은 건드리지 않는다.
- `DATABASE_URL` 없이 `uv run pytest -m db`를 실행하면 건너뛰지 않고 실패한다.

### 9. CI (`.github/workflows/ci.yml`)

- 기존 job에 `uv run python scripts/generate_contracts.py --check` 단계를 추가한다(`uv sync --locked`가 개발용 생성 도구까지 설치한다).
- `db` 마커 테스트를 처음 쓰므로 `db` job을 추가한다.
  - PostgreSQL 서비스 컨테이너: compose와 같은 `postgres:17.6`. `POSTGRES_HOST_AUTH_METHOD: trust`로 띄워 워크플로에 비밀번호를 적지 않는다.
  - 환경변수 `DATABASE_URL`을 그 컨테이너 주소로 두고 `uv run pytest -m db`를 실행한다.

### 10. 문서 (개발 중 이 PR에서)

- `docs/architecture.md` "단계끼리 주고받는 데이터"
  - RawRecord 행을 추가한다: SIEM에서 가져온 원본. 바꾸지 않는다.
  - Alert·Event 설명을 "원본을 OCSF로 정규화한 알럿과 이벤트"로 바꾼다.
  - 절 제목 괄호에 RawRecord를 추가한다.
  - 표 아래에 "필드는 `contracts/`가 기준이다"를 적는다.
- `docs/architecture.md` "큰 흐름"
  - L1 설명에 한 줄을 적는다: "Ticket 생성 모드: 기본은 모든 알럿을 Ticket으로, 설정으로 시나리오 모드를 켜면 시나리오 일치 알럿만 바로 Ticket, 나머지는 L1 1차 판정".
  - 그림에 L2에서 "위협 아님"으로 종결되는 화살표를 추가하고, L2 표의 결과 칸을 "사람 검토. 위협이 아니면 종결"로 고친다. 사람도 검토 중 위협이 아니라고 판단하면 종결할 수 있다.
  - 원칙 1("되돌릴 수 없는 결정(사고 확정)은 사람")은 Case 확정을 뜻하므로 그대로 둔다.
- `docs/architecture.md` "변경 이력"에 한 줄을 남긴다.
- `docs/decisions.md`는 이 계획을 확정할 때 함께 고쳤다(D-003 메모, D-026, D-033~D-038).

## 바꿀 곳

- `contracts/`: JSON Schema 10개(새로)
- `src/soc/contracts/`: `validate_contract`, `ContractError`, 시각 변환 함수, `generated/`(생성 코드)
- `src/soc/ids.py`: `new_id`, UUIDv7 구현
- `src/soc/db/`: 마이그레이션 실행기(`migrate.py`), `migrations/0001_common_tables.sql`
- `scripts/generate_contracts.py`: Python 생성과 `--check`
- `tests/`: 계약·ID·시각 변환 테스트, `db` 마커 테스트, `tests/fixtures/contracts/`
- `pyproject.toml`, `uv.lock`: 의존성(psycopg 3, jsonschema, pydantic v2, 개발용 datamodel-code-generator), 생성 폴더 E501 예외
- `.github/workflows/ci.yml`: 생성 차이 검사, `db` job
- `docs/architecture.md`: 위 "문서"대로

## 다른 코드와 맞물리는 곳

모두 새로 만든다. 이후 각 단계가 그대로 쓴다.

- 계약 10개(`contracts/`)와 생성 모델(`soc.contracts.generated`)
- 함수: `soc.contracts.validate_contract`, `soc.contracts.ContractError`, `soc.contracts.to_datetime`, `soc.contracts.to_epoch_ms`, `soc.ids.new_id`
- 테이블: `raw_records`, `alerts`, `events`, `tickets`, `incidents`, `cases`, `agent_logs`, `schema_migrations`
- 마이그레이션 번호 대역과 규칙
- 설정 키 이름: `[ticketing] mode`, `[ticketing] scenario_rule_ids`(값을 읽는 코드와 `config/default.toml`은 수집·정규화 이슈)
- 다른 단계가 지킬 규칙
  - DB에 쓰기 전에 `validate_contract()`를 거친다. 생성된 Pydantic 모델은 if/then 규칙과 schema 밖 검사를 모르므로, 모델을 직접 만들어 쓰면 계약을 건너뛴다.
  - 남의 `details`를 읽지 않는다.
  - 가져가는 상태: L1은 `new` Ticket과 `triage.status = pending` Alert, L2는 `escalated` Ticket.
  - 상태를 바꾸는 쪽은 4절의 상태 표를 따른다.
  - verdict가 가리키는 `agl_` 기록은 판정을 저장하기 전에 `agent_logs`에 있어야 한다(근거 ID 존재 확인을 위해).
  - 공통 계약 변경(값 추가 포함)은 L1·L2·L3 담당자 전원이 승인한다.

## 범위 밖

- 각 테이블을 읽고 쓰는 코드(각 단계 이슈)
- 수집, 정규화, Lookup 로직(수집·정규화 이슈). 정규화 실패 처리 포함
- Ticket 생성 모드의 동작: `[ticketing]` 설정 읽기, 시나리오 일치 판단, Ticket 생성(수집·정규화 이슈)
- L1 1차 판정과 Ticket 판정(L1 이슈)
- 시나리오 모드에서 보류된 알럿(`triage.status = held`)을 L3가 쓸지(L3 이슈)
- Incident 분석 결과, 탐지 룰 제안, 사람 검토 기록(L2 이슈), Hunt(L3 이슈)
- L3 Ticket이 Hunt를 가리키는 필드(L3 이슈에서 공통 계약 변경으로 추가)
- TypeScript 생성, Node 설정, 그 CI(첫 화면 이슈)
- 원본 보관 기간 삭제와 그때의 외래 키 동작(보관 기간 이슈)
- 화면(첫 화면 이슈)

## 완료 기준

- [ ] 7개 데이터와 공통 조각 3개의 JSON Schema가 `contracts/`에 있고, 필드·타입·필수·목록 값이 이 계획과 같다
- [ ] 데이터마다 손으로 만든 올바른 샘플과 틀린 샘플이 `tests/fixtures/contracts/`에 있다(IP는 문서용 대역, 도메인은 example.com)
- [ ] `validate_contract()`가 아래 틀린 샘플을 거부하는 테스트가 있다
  - 필수 필드 누락, 목록에 없는 상태·출처 값, 정의하지 않은 추가 필드(최상위와 안쪽 객체), 접두사가 틀린 ID, 범위 밖 심각도
  - `origin`이 `auto`, `scenario`, `l1`인데 `alert_ids`가 빈 Ticket
  - `ocsf_class`와 `ocsf.class_uid`가 다른 Event, `ocsf.class_uid`가 2004가 아닌 Alert
  - `triage.status`가 목록에 없는 값인 Alert, `pending`인데 verdict가 있는 Alert, `promoted`인데 verdict가 없는 Alert
  - `status = new`인데 verdict가 있는 Ticket
  - `status = resolved`인데 `resolved_at`이 없는 Case
  - `evidence_ids`에 `alt_`, `evt_`, `agl_`가 아닌 접두사(예: `tkt_`)가 있는 Verdict
- [ ] 아래 올바른 샘플이 통과한다
  - 기본 모드 Alert(`triage = null`)와 `origin = auto` Ticket
  - 시나리오 모드: 일치 Alert(`triage = null`)와 `origin = scenario` Ticket, 1차 판정 대기 Alert(`pending`, `verdict = null`), 승격된 Alert(`promoted`, verdict 있음)와 `origin = l1` Ticket, 보류된 Alert(`held`, verdict 있음과 없음)
  - `rule_id = null`인 Alert
  - L3 Ticket(`origin = l3`, `status = escalated`, `alert_ids` 빈 목록)
  - `evidence_ids`에 `agl_`가 있는 Verdict
  - `summary`가 null인 Incident와 값이 있는 Incident, `dismissed` Incident
  - `summary`가 null인 Case
  - `subject_type = alert`인 Agent Log
- [ ] `ContractError`에 틀린 필드 경로와 어긴 규칙이 있고, 입력 값은 들어 있지 않다
- [ ] `scripts/generate_contracts.py`로 Python 코드가 만들어지고, CI가 `--check`로 차이가 없는지 검사한다
- [ ] `new_id()`가 접두사별(`run` 포함) ID를 만들고, 같은 밀리초 안을 포함해 연달아 만든 ID가 만든 순서대로 정렬되며, 목록에 없는 접두사는 거부하는 테스트가 있다
- [ ] `to_datetime()`·`to_epoch_ms()` 왕복 값이 같고, 시간대 없는 `datetime`을 거부하는 테스트가 있다
- [ ] `python -m soc.db.migrate`가 빈 DB에 테이블을 모두 만들고, 두 번 실행해도 다시 적용하지 않는 테스트가 있다(`db` 마커, CI에서 실행)
- [ ] 실패하는 마이그레이션 파일은 그 파일만 되돌리고 멈추는 테스트가 있다(`db` 마커)
- [ ] 같은 `(siem_profile, siem_ref)` 원본을 두 번 넣으면 DB가 거부하는 테스트가 있다(`db` 마커)
- [ ] 올바른 샘플을 모두 해당 테이블에 넣을 수 있고, 각 테이블의 컬럼 이름이 계약 최상위 필드 이름과 같은 테스트가 있다(`db` 마커)
- [ ] `docs/architecture.md`가 위 "문서"대로 고쳐졌다
- [ ] 공통 계약을 새로 만드는 PR이므로 L1·L2·L3 담당자 전원이 승인한다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m db`가 통과한다

## 토론으로 정한 것

원래 이슈와 달라진 점과 이유.

1. **L2가 Incident를 바로 `dismissed`로 닫는 것을 유지하고 문서를 고친다.** 이슈 내용이 `docs/architecture.md` "큰 흐름"(L2 결과는 모두 사람 검토)과 부딪혔다. 원칙 1의 "사고 확정"은 Case 확정을 뜻하므로, 원칙은 두고 흐름 그림과 L2 표를 고친다. Case로 가는 승인은 사람만 한다.
2. **사람도 `dismissed`로 닫을 수 있다.** 그렇지 않으면 검토자가 위협이 아니라고 판단해도 닫을 수 없고, `human_handling`을 끝낼 상태가 없다.
3. **Incident에 `summary`(문자열 또는 null)를 추가하고, Case `summary`도 문자열 또는 null로 바꾼다.** 원래 Case는 "승인 시점 분석 요약"을 복사하는데, Incident에 그 필드가 없었다. 남의 `details`를 읽지 않는다는 규칙 때문에 가져올 곳이 없었다.
4. **TypeScript 생성은 첫 화면 이슈로 미룬다(도구는 json-schema-to-typescript로 확정).** `frontend/`가 아직 없다. 이 도구는 출력을 prettier로 정리하므로 lockfile 없이는 `--check` 결과가 흔들린다. 지금 계약을 쓰는 L1·L2·L3는 모두 Python이다.
5. **생성 폴더에서만 ruff E501을 끈다(D-038).** datamodel-code-generator 0.88.0으로 시험 생성해 보니, schema 설명 문장이 한 줄로 나와 100자를 넘었다. 생성 코드는 손으로 고칠 수 없다. `AGENTS.md` 금지 사항과 닿아 있어 사람이 승인하고 결정 목록에 남겼다.
6. **라이브러리 확정(D-037):** psycopg 3, jsonschema, pydantic v2, 개발용 datamodel-code-generator. psycopg 3는 동기·비동기를 모두 지원해 나중에 FastAPI(D-016)에도 쓸 수 있다.
7. **UUIDv7은 직접 구현하고, 같은 밀리초 안 카운터를 둔다(D-034).** 무작위 비트만 쓰면 같은 밀리초 안에서 순서가 뒤집혀 정렬 테스트가 가끔 실패한다.
8. **Triage는 이슈대로 `pending`/`promoted`/`held` 세 가지다.** `closed`를 더하자는 안은 받지 않았고, 1차 판정에서 오탐을 확신해도 `held`다.
9. **`evidence_ids`에 `agl_`도 허용한다.** SSH 출력이나 저장하지 않은 SIEM 조회 결과에는 `evt_` ID가 없다. 근거 없는 판정을 막는 원칙 3을 지키려면 도구 결과를 가리킬 ID가 필요하다.
10. **`siem_ref`를 "SIEM 안에서 문서 하나를 가리키는 값. ELK는 `<_index>/<_id>`"로 바꾼다.** ELK `_id`는 인덱스 안에서만 유일하다. `_id`만 쓰면 다른 인덱스에 있는 다른 문서를 중복으로 보고 버린다.
11. **`timestamptz`를 유지하고 변환 함수 두 개를 이 이슈에서 만든다.** 읽기·쓰기 코드가 이 이슈 밖이라, 그대로 두면 네 단계가 각자 변환을 만든다.
12. **`db` 테스트는 임시 DB를 만들어 쓰고 지운다.** 개발 DB 데이터를 지우지 않고, 새 환경변수도 필요 없다.
13. **`alert_ids`, `ticket_ids`는 `text[]` + GIN 인덱스다.** 행 하나가 계약 하나와 1:1이라 "컬럼 이름 = 계약 필드" 규칙이 유지된다. 대신 원소 외래 키와 "Alert는 Ticket 하나에만" 같은 유일성은 DB가 막지 않는다.
14. **`run_id`는 `run_` + UUIDv7이고, 접두사 목록에 `run_`을 추가한다.**
15. **Asset `criticality`는 이슈대로 1~5다.** 정규화 담당자가 바꾸고 싶으면 상의한 뒤 공통 계약 변경 절차로 바꾼다.
16. **이슈에 없던 기본값을 정했다.**
    - 안쪽 객체까지 추가 필드 거부
    - 상태와 짝 필드 검사(Triage, Ticket `new`, Case `resolved`)
    - Alert가 없는 Incident의 `severity`는 0
    - DB CHECK 범위
    - `(run_id, seq)` 유일
    - 마이그레이션의 트랜잭션·실패·중복 번호 처리
    - `DATABASE_URL` 비노출
    - 예외에 입력 값 넣지 않기
    - CI trust 인증
    - `validate_contract` 이름 목록과 schema 위치
    - 시각 함수 동작
    - `DATABASE_URL` 없을 때 `db` 테스트 실패
    - verdict가 가리키는 `agl_`의 저장 순서
    - 완료 기준 추가
17. **schema로 쓸 수 없는 규칙(Event `ocsf_class` 비교)은 `validate_contract()`의 추가 검사 단계에서 확인한다.** if/then으로 쓸 수 있는 규칙은 schema에 쓴다. 생성 모델이 이 규칙들을 모르므로, DB에 쓰기 전 `validate_contract()`를 거치는 것을 다른 단계의 규칙으로 둔다.
18. **datamodel-code-generator 기본 출력은 생성 시각을 넣어 `--check`가 늘 실패한다.** 그래서 `--disable-timestamp`, 버전 고정, 생성 후 ruff format을 쓴다.
19. **마이그레이션 번호 대역에 "자기보다 작은 번호의 테이블만 참조"를 더한다.** 빈 DB에서는 번호 순서로 실행되기 때문이다.
20. **Ticket 출처는 새 결정 번호를 만들지 않고, 결정 목록의 기존 D-026(담당자가 정함)을 확정으로 옮긴다.**
21. **`alerts.raw_id` 외래 키는 기본 동작으로 둔다.** 원본 보관 기간(D-008) 삭제와 부딪히는 문제는 보관 기간 이슈가 정한다.

## 바뀐 점

- 2026-11-03 · jsonb 컬럼에 JSON null을 거부하는 CHECK를 건다. null이 될 수 있는 `triage`, `verdict`, `output`은 SQL NULL만 받고, 같은 위험이 있는 NOT NULL 객체·목록 컬럼(`original`, `entities`, `assets`, `ocsf`, `details`)에도 건다. 계약상 JSON 값 전체(null 포함)를 받는 `agent_logs.input`은 뺀다. 머지 전이라 `0001_common_tables.sql`을 직접 고치고, JSON null 거부·SQL NULL 허용 `db` 테스트를 더한다.
- 2026-11-03 · OCSF 클래스별 검증은 정규화 이슈에서 한다. 이 계약은 `ocsf`를 자유 객체로 두고 Alert의 `class_uid = 2004`와 Event의 `ocsf_class = ocsf.class_uid`만 검사한다. 결정 목록 OCSF 정규화(D-007) 메모에 공식 OCSF 1.9.0 JSON Schema로 클래스별 검증을 정규화 이슈에서 반드시 한다고 덧붙인다.
- 2026-11-03 · (계약) Verdict의 `decision`이 `benign`·`malicious`이면 `evidence_ids`는 1개 이상이다(if/then). `undetermined`는 빈 목록을 허용한다.
- 2026-11-03 · (계약) DB `integer`(int32) 컬럼에 대응하는 정수 필드(`ocsf_class`, `analysis_round`, `review_round`, `seq`, `tokens_in`, `tokens_out`, `duration_ms`)에 `maximum: 2147483647`을 둔다.
- 2026-11-03 · (계약) 시각(`epoch_ms`)에 `maximum: 253402300799999`(9999-12-31T23:59:59.999Z)를 둔다. 마이크로초로 잘못 넣은 시각을 거부한다.
- 2026-11-03 · (계약) RawRecord의 `siem_profile`·`siem_ref`와 Asset의 `entity_value`는 빈 문자열을 거부한다(`minLength: 1`).
- 2026-11-03 · (DB) `alerts.raw_id`, `events.raw_id`에 인덱스를 둔다.
- 2026-11-03 · (마이그레이션 실행기) 이미 적용한 번호의 파일 이름이 `schema_migrations.name`과 다르면 아무것도 실행하지 않고 `MigrationError`로 멈춘다.
- 2026-11-03 · (계약) 시각(`epoch_ms`) 상한을 `253402214399999`(9999-12-30T23:59:59.999Z)로 당긴다. 가장 큰 시간대 오프셋(+14시간)으로 읽어도 10000년을 넘지 않게 하기 위해서다.
- 2026-11-03 · (DB, PR #193 리뷰) `alerts.triage`는 SQL NULL이거나, 객체이면서 `status`가 목록 값일 때만 받는다. `status`가 없거나 null이어도 거부되도록 비교를 `IS TRUE`로 감싸고, JSON null 거부 제약은 그대로 둔다. jsonb 칸의 모양도 확인한다: `original`·`ocsf`·`details`·`verdict`(SQL NULL 허용)는 객체, `entities`·`assets`는 목록이다. `agent_logs.input`·`output`은 모양 제약을 걸지 않는다. 안쪽 필드 검사는 지금처럼 `validate_contract()`가 맡는다.
- 2026-11-04 · (검증 함수, PR #193 리뷰) `validate_contract()`는 schema 검사 전에 `json.dumps(data)`를 시도하고, `TypeError`가 나면(자유 객체 안의 bytes·datetime·set 등) `(root): json` 위반으로 `ContractError`를 낸다. NaN·Infinity는 지금처럼 수집·정규화 이슈에서 정한다(`allow_nan` 기본값 유지).
- 2026-11-04 · (마이그레이션 실행기, PR #193 리뷰) `schema_migrations`에 기록된 번호의 파일이 없으면 아무것도 실행하지 않고 `MigrationError`로 멈춘다. 번호만 바꾼 파일이 새 번호로 다시 실행되는 것을 막는다.
- 2026-11-04 · (DB, PR #193 리뷰) `tickets.alert_ids`, `incidents.ticket_ids`는 NULL 원소를 거부한다(`array_position(..., NULL) IS NULL`). `ticket_ids`는 1개 이상, `alert_ids`는 계약과 같이 `origin`이 `l3`가 아니면 1개 이상이다(`origin = 'l3' OR cardinality(alert_ids) >= 1`).
- 2026-11-04 · (계약, PR #193 리뷰) Ticket `alert_ids`, Incident `ticket_ids`, Verdict `evidence_ids`는 중복 ID를 거부한다(`uniqueItems`).
- 2026-11-04 · (계약, PR #193 리뷰) Agent Log에서 `kind = tool`이면 `tokens_in`, `tokens_out`은 null이다(if/then).
- 2026-11-04 · (계약, PR #193 리뷰) Agent Log `subject_id`는 `subject_type`에 맞는 ID다(if/then): `alert` → `alt_`, `ticket` → `tkt_`, `incident` → `inc_`. `hunt`는 Hunt ID 형식이 아직 없어 빈 문자열만 거부하고(`minLength: 1`), L3 이슈에서 Hunt ID를 정할 때 바꾼다.
- 2026-11-04 · (검증 함수) `json.dumps`가 내는 `ValueError`(순환 참조)도 `TypeError`와 같이 `(root): json` 위반으로 `ContractError`를 낸다. NaN·Infinity는 `allow_nan` 기본값이라 오류가 나지 않으므로 지금처럼 수집·정규화 이슈에서 정한다.
