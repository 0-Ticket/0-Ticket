---
issue: 217
date: 2026-11-04
owner: Pandyo
supersedes: [192-data-contracts.md]  # Ticket 계약·tickets 테이블에 hunt_id를 더하고, Agent Log의 hunt 대상 ID를 좁힌다. 나머지는 그대로다
---

# Hunt 계약과 Ticket의 Hunt 연결 추가

## 목표

L3 헌팅 결과인 Hunt의 공통 계약(JSON Schema)과 `hunts` 테이블을 만들고, Ticket이 자기를 만든 Hunt를 `hunt_id`로 가리키게 한다. L2가 L3 Ticket(`alert_ids`가 빌 수 있음)을 받는 코드를 짜기 전에 모양을 먼저 머지한다.

이 이슈는 "그릇"만 만든다. Hunt를 만들고 검증하는 코드는 L3 가설 헌팅 이슈가, 조회는 Hunt 조회 API 이슈가 만든다.

## 방법

### 1. ID 접두사

- `src/soc/ids.py`의 `PREFIXES`에 `hnt`(Hunt), `hrn`(헌팅 실행)을 더한다.
- `contracts/common/types.schema.json`에 정의 3개를 더한다: `hunt_id`(`^hnt_…$`), `hunt_run_id`(`^hrn_…$`), `hunt_subject_id`(`^(hnt|hrn)_…$`). 모두 기존 ID와 같은 UUIDv7 모양이다.
- `hrn_` ID는 테이블이 따로 없고 Hunt를 묶는 키로만 쓴다. Agent Log의 `run_id`(`run_`, 에이전트 실행 한 번)와 다른 ID다. 가설 생성 run은 `subject_type = hunt`, `subject_id = hrn_…`, 검증 run은 `subject_id = hnt_…`로 남는다.

### 2. Hunt (`contracts/hunt.schema.json`)

가설 하나와 그 검증 결과다. 최상위는 `additionalProperties: false`다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | `hnt_` ID | 예 | |
| `hunt_run_id` | `hrn_` ID | 예 | 같은 가설 생성 실행에서 나온 Hunt 묶음 |
| `status` | 목록 값 | 예 | 아래 상태 표 |
| `hypothesis` | 문자열(빈 값 불가) | 예 | 가설 문장. 뉴스 등 밖에서 온 문자열에서 나온 LLM 출력이라 공격자가 쓴 문장이 들어갈 수 있다(description에 적는다) |
| `attack_techniques` | 문자열 목록 | 예 | ATT&CK 기법 ID, pattern `^T[0-9]{4}(\.[0-9]{3})?$`(`T1190`, `T1059.004`). 중복 없음, 빈 목록 가능 |
| `confidence` | 숫자 0~1 또는 null | 예 | 검증 결과 확신도 |
| `reason` | 문자열(빈 값 불가) 또는 null | 예 | 검증 결과 이유. `hypothesis`와 같이 공격자가 쓴 문장이 들어갈 수 있다 |
| `evidence_ids` | `evidence_id` 목록 | 예 | `alt_`, `evt_`, `agl_`. 중복 없음 |
| `entities` | Entity 목록 | 예 | 검증에서 확인한 엔티티 |
| `attempts` | 정수 0~2147483647 | 예 | 검증 run 시도 횟수 |
| `verified_at` | epoch_ms 또는 null | 예 | 검증 결과가 정해진 시각 |
| `created_at` | epoch_ms | 예 | |
| `updated_at` | epoch_ms | 예 | |
| `details` | 객체(자유) | 예 | 가설 출처(뉴스·Case 참조) 등 L3 내부 값. 다른 단계는 읽지 않는다 |

**상태** (바꾸는 쪽은 모두 L3)

| 상태 | 뜻 |
|---|---|
| `pending` | 검증 대기(재시도 대기 포함) |
| `confirmed` | 위협 발견. L3 Ticket을 만든다 |
| `rejected` | 가설 기각 |
| `inconclusive` | 근거 부족 |
| `failed` | 검증 run이 재시도 한도까지 실패 |

**조건부 규칙** (schema `allOf` if/then)

| 조건 | 규칙 |
|---|---|
| `pending`, `failed` | `confidence`, `reason`, `verified_at`이 null |
| `confirmed`, `rejected`, `inconclusive` | `confidence`, `reason`, `verified_at`이 null이 아님 |
| `confirmed` | `evidence_ids`에 `alt_` 또는 `evt_`가 1개 이상(`contains`) |
| `rejected` | `evidence_ids` 1개 이상(`agl_`도 인정) |
| `pending`이 아님 | `attempts` 1 이상 |

`inconclusive`의 `evidence_ids`는 빈 목록이어도 된다.

### 3. Ticket 변경 (`contracts/ticket.schema.json`)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `hunt_id` | `hnt_` ID 또는 null | 예 | 이 Ticket을 만든 Hunt. `origin = l3`이면 값이 있고, 그 밖에는 null(if/then/else) |

### 4. Agent Log 변경 (`contracts/agent_log.schema.json`)

- `subject_type = hunt`이면 `subject_id`는 `hunt_subject_id`(`^(hnt|hrn)_…$`)다. 지금의 `minLength: 1`을 바꾼다(#192에서 L3 이슈로 미룬 것).
- `subject_id` description의 "hunt는 Hunt ID 형식이 정해지기 전까지 빈 문자열만 거부한다"를 고친다.

### 5. DB (`src/soc/db/migrations/0002_hunts.sql`)

공통 대역(0001~0099, 마이그레이션 D-035)의 다음 번호. Hunt는 공통 계약이고 공통 테이블(`tickets`)이 참조하므로 공통 대역에 둔다.

- `hunts` 테이블. 컬럼 이름은 계약 필드와 같다.
  - `evidence_ids`, `attack_techniques`: `text[]` + `array_position(..., NULL) IS NULL` CHECK(0001의 최상위 ID 목록과 같은 모양)
  - `entities`: jsonb + `jsonb_typeof = 'array'`, `details`: jsonb + `jsonb_typeof = 'object'`
  - 시각: `timestamptz`(`verified_at`만 null 가능)
  - `status`: 목록 값 CHECK, `attempts`: integer + `>= 0` CHECK, `confidence`: double precision + `BETWEEN 0 AND 1` CHECK
- 인덱스: `hunts(status)`, `hunts(hunt_run_id)`
- `tickets.hunt_id text`를 더한다. `REFERENCES hunts (id)`(삭제 동작은 기본: 삭제를 막음, `alerts.raw_id`와 같음), `UNIQUE`(한 Hunt에서 Ticket 하나. PostgreSQL UNIQUE는 NULL끼리 겹쳐도 막지 않으므로 부분 유일 인덱스와 같다), `CHECK ((origin = 'l3') = (hunt_id IS NOT NULL))`
- DB CHECK 기준은 0001과 같다(행 하나만 봐도 깨진 레코드인지 알 수 있는 것). Hunt 상태와 `confidence`·`reason`·`verified_at`·`evidence_ids`·`attempts`의 짝은 DB에 두지 않고 `validate_contract()`만 검사한다. `origin` ↔ `hunt_id`는 `origin` ↔ `alert_ids`처럼 DB에서도 막는다. 0001 헤더 주석은 고칠 수 없으므로(적용한 파일의 해시) 이 기준을 0002 헤더에 적는다.

### 6. 검증·생성 코드와 문서

- `src/soc/contracts/validate.py`의 계약 목록에 `hunt`를 더한다.
- `uv run python scripts/generate_contracts.py`로 Python 생성 코드를 다시 만든다. TypeScript 생성은 첫 화면 이슈에서 붙이므로(데이터 계약, D-003) 하지 않는다.
- `docs/decisions.md` "기록"에 한 줄.

### 순서

샘플(`tests/fixtures/contracts/`) → 테스트 → schema·생성 코드 → `validate.py`·`ids.py` → 마이그레이션.

## 바꿀 곳

- `src/soc/ids.py`: 접두사 `hnt`, `hrn`
- `contracts/common/types.schema.json`: `hunt_id`, `hunt_run_id`, `hunt_subject_id`
- `contracts/hunt.schema.json`: 새 파일
- `contracts/ticket.schema.json`: `hunt_id`와 if/then/else
- `contracts/agent_log.schema.json`: hunt 대상 `subject_id` 패턴과 description
- `src/soc/contracts/generated/`: 다시 생성
- `src/soc/contracts/validate.py`: `hunt` 계약 등록
- `src/soc/db/migrations/0002_hunts.sql`: 새 파일
- `tests/fixtures/contracts/valid|invalid/hunt.json`: 새 샘플
- `tests/fixtures/contracts/valid|invalid/ticket.json`: 모든 샘플에 `hunt_id`, 새 샘플
- `tests/fixtures/contracts/valid|invalid/agent_log.json`: hunt 대상 샘플
- `tests/contract_samples.py`: `CONTRACT_NAMES`에 `hunt`
- `tests/test_contracts.py`, `tests/test_db_tables.py`, `tests/test_ids.py`: 새 테스트, 기존 테스트의 기대값 수정(아래)
- `docs/decisions.md`: 기록 한 줄
- `docs/notes/217-hunt-contract.md`: 개발 기록

기존 테스트는 지우거나 건너뛰지 않고 기대값만 고친다.

- `test_unknown_contract_name_is_rejected`: 모르는 이름의 예 `"hunt"`를 다른 값으로
- `test_migrate_creates_all_tables_on_empty_db`: 적용 목록에 `0002_hunts.sql`, 테이블 목록에 `hunts`
- jsonb 컬럼 수: `19` → `21`, 객체·목록 칸 `34` → `38`
- `TABLES` 순서에서 Hunt를 Ticket 앞에 두고, `ensure_parents`가 Ticket의 Hunt를 먼저 넣는다. Hunt 없이 L3 Ticket을 넣던 테스트(`test_id_arrays_take_values_the_contract_allows`의 l3 두 가지)도 Hunt를 먼저 넣는다
- L3 Ticket 샘플이 여러 개면 서로 다른 Hunt를 가리킨다(UNIQUE)
- Agent Log 빈 문자열 hunt 대상 틀린 샘플의 규칙: `minLength` → `pattern`. 올바른 샘플 `l3_hunt_tool_call`의 `subject_id`는 `hrn_` ID

## 다른 코드와 맞물리는 곳

- **Ticket 계약에 필수 필드 `hunt_id`가 늘어난다.** 생성 모델 `Ticket`도 `hunt_id`를 요구한다. 계획 시점에 main에는 Ticket을 만드는 코드가 없다. Ticket 샘플이나 코드를 가진 다른 브랜치는 rebase 후 `hunt_id: null`(L3면 Hunt ID)을 넣어야 한다. PR 본문에 알린다.
- **`tickets` 테이블에 `hunt_id` 컬럼, 외래 키, UNIQUE, CHECK가 늘어난다.** `origin = l3`인 Ticket이 이미 있는 로컬 DB에서는 0002의 CHECK 추가가 실패한다. 그런 DB는 다시 만든다.
- **Agent Log hunt 대상 `subject_id`가 좁아진다.** #216(머지됨)의 `src/soc/agent/types.py` `_SUBJECT_ID`에는 hunt 갈래가 없어, 틀린 hunt ID는 `AgentTask`를 만들 때가 아니라 로그를 쓸 때(`validate_contract`) 걸려 `log_error`가 된다. 깨지지는 않는다. 이 PR에서 그 코드는 고치지 않고 담당자에게 hunt 패턴을 더하라고 알린다.
- **`validate_contract()`가 받는 계약 이름에 `hunt`가 늘어난다.** `soc.contracts.CONTRACT_NAMES`를 쓰는 #216의 `output_contract` 검사에도 `hunt`가 들어간다.
- **`soc.ids.PREFIXES`에 `hnt`, `hrn`이 늘어난다.**
- **마이그레이션 번호 `0002`.** 다른 PR이 공통 대역에서 같은 번호를 쓰면 실행기가 멈춘다. 머지 직전에 확인한다.

## 범위 밖

- Hunt를 만들고 검증하는 코드(L3 가설 헌팅 이슈), Hunt 조회 API
- L3 Ticket이 가리키는 Hunt가 실제로 `confirmed`인지, 근거 ID가 실제로 있는지 확인하는 것(다른 행을 봐야 해서 L3 코드가 한다)
- Verdict `reason`의 빈 문자열 거부
- `src/soc/agent/types.py`의 `_SUBJECT_ID` 수정
- TypeScript 생성 코드

## 완료 기준

- [ ] Hunt JSON Schema가 `contracts/`에 있고 필드·타입·필수·목록 값·조건부 규칙이 위 표와 같다
- [ ] 올바른 샘플이 통과한다: 상태 5가지 Hunt(`inconclusive`는 근거 빈 목록), `origin = l3`·`hunt_id` 있음·`alert_ids` 빈 목록 Ticket, `hunt_id = null`인 다른 출처 Ticket, `hrn_`·`hnt_` 대상 Agent Log
- [ ] 틀린 샘플이 거부된다
  - Hunt: `pending`인데 `confidence` 있음, `failed`인데 `confidence` 있음, `inconclusive`인데 `confidence` null, `confirmed`인데 `alt_`·`evt_` 근거 없음, `rejected`인데 근거 빈 목록, `confirmed`인데 `attempts = 0`, `reason` 빈 문자열, `hypothesis` 빈 문자열, 기법 ID 형식 오류, 기법 ID 중복, 목록에 없는 상태
  - Ticket: `origin = l3`인데 `hunt_id = null`, `origin = auto`인데 `hunt_id` 있음, 접두사가 틀린 `hunt_id`, `hunt_id` 없음
  - Agent Log: hunt 대상이 `tkt_` ID, 임의 문자열, 빈 문자열
- [ ] `new_id("hnt")`, `new_id("hrn")`이 동작하고 계약의 ID 패턴에 맞는다
- [ ] 마이그레이션 뒤(`db` 마커): Hunt·Ticket 샘플이 테이블에 들어가고 그대로 읽힌다, 같은 `hunt_id`로 Ticket을 두 번 넣으면 거부된다, `origin = l3`인데 `hunt_id`가 NULL이거나 `origin = auto`인데 `hunt_id`가 있으면 CHECK가 거부한다, 없는 Hunt를 가리키면 외래 키가 거부한다, `hunts` 컬럼이 계약 필드와 같다, `hunts`의 목록 값·범위·NULL 원소·jsonb 모양 CHECK가 동작한다
- [ ] 생성 코드 차이 검사(`--check`)가 통과한다
- [ ] 공통 계약 변경이므로 L1·L2·L3 담당자 전원이 승인한다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

1. **Agent Log hunt 대상 `subject_id`를 `(hnt|hrn)` 패턴으로 좁힌다.** 이슈는 "Agent Log 계약은 바꾸지 않는다"였지만, #192 계획·기록이 Hunt ID를 정할 때 바꾸기로 미뤄 두었다. 어차피 공통 계약 변경이라 같은 승인으로 끝난다. 위반 규칙 이름이 `pattern` 하나로 나오게 `anyOf` 대신 정의 하나(`hunt_subject_id`)로 둔다.
2. **`hunts.evidence_ids`, `attack_techniques`는 `text[]`다.** 이슈는 jsonb였다. 0001이 최상위 ID 목록을 `text[]`로 두므로 같은 모양으로 맞췄다.
3. **`failed`는 `confidence`, `reason`, `verified_at`이 모두 null이다.** 이슈에 규칙이 없었다. 검증 결과가 없는 상태이고, 끝난 시각은 `updated_at`에 남는다.
4. **`rejected`는 근거 1개 이상(`agl_` 인정), `inconclusive`는 빈 목록 가능.** 이슈에는 `confirmed` 규칙만 있었다. 기각도 판정이므로 Verdict(benign·malicious는 근거 필요)와 같은 기준을 둔다(원칙 3).
5. **`origin` ↔ `hunt_id`를 DB CHECK로도 막는다.** 0001의 `origin` ↔ `alert_ids` CHECK와 같은 기준이다.
6. **`pending`이 아닌 Hunt는 `attempts` 1 이상.** 한 번도 검증하지 않고 결과가 난 Hunt를 막는다.
7. **Hunt `reason`은 빈 문자열을 받지 않는다(`minLength: 1`).** 결과 상태에서 null 대신 `""`로 규칙을 피하는 것을 막는다. Verdict는 이 이슈에서 바꾸지 않는다.
8. **TypeScript 생성은 하지 않는다.** 이슈는 Python·TypeScript 생성을 적었지만 TypeScript 생성은 첫 화면 이슈에서 붙인다(데이터 계약, D-003).
9. **부분 유일 인덱스 대신 `UNIQUE (hunt_id)`.** 동작이 같고 `cases.incident_id UNIQUE`와 모양이 맞는다.
10. 시각 필드는 기존 계약처럼 epoch_ms 정수다(DB는 `timestamptz`).

## 바뀐 점
