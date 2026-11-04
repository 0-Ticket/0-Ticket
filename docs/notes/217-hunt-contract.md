---
issue: 217
date: 2026-11-04
owner: Pandyo
plan: 217-hunt-contract.md
supersedes: [192-data-contracts.md, 209-agent-core.md]  # Ticket hunt_id, Agent Log·AgentTask hunt 대상 ID
---

# Hunt 계약과 hunts 테이블을 만들고 Ticket이 Hunt를 가리키게 했다

## 한 일

L3가 찾은 위협을 L2가 받아 분석할 수 있게, L3 헌팅 결과(Hunt)를 담을 그릇을 만들었다.

- `contracts/hunt.schema.json`: 가설 하나와 그 검증 결과. 상태는 `pending`, `confirmed`, `rejected`, `inconclusive`, `failed` 다섯 가지이고, 상태에 따라 `confidence`·`reason`·`verified_at`의 null 여부, 근거(`evidence_ids`) 개수, `attempts` 하한이 정해진다(계획 "조건부 규칙").
- Ticket에 필수 필드 `hunt_id`를 더했다. `origin = l3`이면 Hunt ID, 그 밖에는 null이다. L3 Ticket은 `alert_ids`가 빌 수 있으므로 L2는 이 필드로 Hunt를 찾는다.
- ID 접두사 `hnt_`(Hunt), `hrn_`(가설 생성 실행)을 더했다. Agent Log에서 `subject_type = hunt`이면 `subject_id`는 이 둘 중 하나여야 한다(전에는 빈 문자열만 거부했다).
- 마이그레이션 `0002_hunts.sql`: `hunts` 테이블을 만들고 `tickets.hunt_id`(외래 키, UNIQUE, `origin` ↔ `hunt_id` CHECK)를 더했다.
- `validate_contract("hunt", data)`가 동작한다. 생성 모델은 `soc.contracts.generated.hunt_schema.Hunt`다.
- `AgentTask`(#216)도 hunt 대상 `subject_id`를 같은 패턴으로 검사한다. 틀리면 작업을 만들 때 `ValueError`다.

## 계획과 달라진 점

- `tests/test_ids.py`의 `test_unknown_prefix_is_rejected`도 `"hnt"`를 모르는 접두사의 예로 쓰고 있어 다른 값(`"hun"`)으로 바꿨다. 계획의 "기존 테스트의 기대값 수정" 목록에 없던 곳이다.
- `test_migrate_twice_does_not_reapply`의 `schema_migrations` 행 수 기대값도 1에서 2로 바꿨다. 이것도 목록에 없던 곳이다.
- 계획에 없던 테스트를 몇 개 더했다: Ticket이 가리키는 Hunt는 지울 수 없음, `hunt_id`가 NULL인 Ticket 여러 개가 함께 들어감, `hunts` 인덱스 2개. 틀린 샘플도 계획 목록보다 몇 개 더 있다(기법 ID 끝 `\n`, 중복 근거 ID, `run_` 접두사 `hunt_run_id`, `attempts` float, 추가 필드, `hunt_id` 끝 `\n`).
- **`src/soc/agent/types.py`의 `_SUBJECT_ID`에 hunt 패턴을 더했다(계획 "바뀐 점").** 계획에서는 범위 밖으로 두고 담당자에게 알리기로 했다. 개발 중 #216이 main에 머지돼 확인해 보니, 틀린 hunt ID(`dns-beaconing-review`, `tkt_…`)로 만든 작업이 그대로 만들어지고, 가짜 모델로 돌리면 모델을 2번 부른 뒤 `log_error`(`Agent Log를 쓰지 못했다(ContractError)`)로 끝났다. 그 실행의 Agent Log는 하나도 남지 않는다. L1 처리처럼 `log_error`를 재시도하면 재시도마다 LLM 호출이 낭비된다. 이 PR이 Agent Log 계약을 좁혀서 생긴 문제라 사람이 여기서 고치기로 정했다. `tests/test_agent_core.py`에 틀린 hunt ID 3개(임의 문자열, `tkt_`, 끝 `\n`)와 `hrn_`·`hnt_` 작업이 끝까지 도는 테스트를 더했다.
- `tickets`의 새 CHECK에는 이름(`tickets_origin_hunt_id_check`)을 붙였다. 0001의 이름 없는 CHECK(`tickets_check` 등)와 달리 오류 메시지에서 무엇이 걸렸는지 바로 보이게 하려는 것이다.

## 다음 사람이 알아야 할 것

- **Ticket을 만드는 코드와 샘플은 `hunt_id`를 넣어야 한다.** 필수 필드라 빠지면 `hunt_id: required`로 거부된다. L3가 아닌 Ticket은 `"hunt_id": null`이다. 생성 모델 `Ticket`도 `hunt_id`를 요구한다.
- **L3 Ticket은 Hunt를 먼저 저장한 뒤 만든다.** `tickets.hunt_id`는 `hunts.id` 외래 키라 Hunt가 없으면 `ForeignKeyViolation`이 난다. 같은 Hunt로 두 번 만들면 `UniqueViolation`(`tickets_hunt_id_key`)이 난다. L3 코드는 이것을 "이미 Ticket을 만든 Hunt"로 다룰 수 있다. Ticket이 가리키는 Hunt는 지울 수 없다(삭제 동작은 기본).
- **`origin = l3`인 Ticket이 이미 있는 DB에서는 `0002`가 실패한다.** `0002_hunts.sql 적용 실패(그 파일은 되돌렸다): check constraint "tickets_origin_hunt_id_check" ...`로 멈추고, `hunts`도 만들지 않은 채 0001까지만 남는다(손으로 확인). 그런 개발 DB는 다시 만든다.
- **Hunt 상태 규칙은 DB가 막지 않는다.** `pending`인데 `confidence`가 있거나 `confirmed`인데 Alert·Event 근거가 없는 행도 DB에는 들어간다. 쓰기 전에 `validate_contract("hunt", ...)`를 거친다. DB는 목록 값, 범위, NULL 원소, jsonb 모양, `origin` ↔ `hunt_id`만 본다(`0002` 헤더 주석).
- **계약이 확인하지 못하는 것이 있다.** L3 Ticket이 가리키는 Hunt가 실제로 `confirmed`인지, 근거 ID가 실제로 있는지는 다른 행을 봐야 알 수 있어 L3 코드가 확인한다.
- **`hunt_run_id`(`hrn_`)와 Agent Log `run_id`(`run_`)는 다른 ID다.** `run_id`는 에이전트 실행 한 번이고, `hunt_run_id`는 가설 생성 실행 하나에서 나온 Hunt 묶음이다. 가설 생성 run의 Agent Log는 `run_id = run_…`, `subject_id = hrn_…`이다.
- **`hypothesis`와 `reason`은 밖에서 온 문자열로 다룬다.** 뉴스 등에서 나온 LLM 출력이다. L2가 에이전트 입력에 넣을 때는 구분자로 감싸고, 화면에서는 텍스트로만 보인다(`docs/security.md`).
- **`reason`은 빈 문자열을 받지 않지만 Verdict의 `reason`은 받는다.** Hunt만 막았다(#217 토론). Verdict를 바꾸려면 따로 공통 계약 변경으로 한다.
- **`confidence`는 DB에서 `double precision`이다.** 계약에 `1`(int)로 넣어도 읽으면 `1.0`이다. Python에서 `1 == 1.0`이라 비교 테스트는 통과한다.
- **`AgentTask`의 hunt 대상 검사는 `docs/notes/209-agent-core.md`와 다르다.** 그 기록의 "`hunt`는 빈 문자열만 거부한다"는 이제 맞지 않는다. `hrn_`(가설 생성 run) 또는 `hnt_`(검증 run) + UUIDv7이어야 한다. 패턴은 `src/soc/agent/types.py`와 `contracts/common/types.schema.json`의 `hunt_subject_id` 두 곳에 있으므로 바꿀 때 함께 바꾼다.
- **ATT&CK 기법 ID는 모양만 본다.** `^T[0-9]{4}(\.[0-9]{3})?$`라서 없는 기법 번호(`T9999`)도 통과한다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run python scripts/generate_contracts.py --check`: 통과
- `uv run pytest`: 382개 통과
- `DATABASE_URL=… uv run pytest -m db`(임시 `postgres:17.6` 컨테이너, trust 인증): 95개 통과
- 테스트를 먼저 쓰고 구현 전에 실패하는지 봤다: 일반 75개, `db` 24개 실패
- 주요 테스트
  - `test_valid_samples_pass_without_losing_fields`, `test_invalid_samples_are_rejected`: Hunt 올바른 샘플 6, 틀린 샘플 16, Ticket 틀린 샘플 5개 추가, Agent Log 올바른 샘플 1·틀린 샘플 2개 추가
  - `test_new_id_matches_contract_pattern[hnt|hrn]`
  - `test_one_ticket_per_hunt`, `test_ticket_origin_must_match_hunt_id`, `test_ticket_hunt_must_exist`, `test_hunt_with_ticket_cannot_be_deleted`, `test_tickets_from_different_hunts_and_other_origins_coexist`, `test_hunt_lookup_columns_are_indexed`
  - `test_valid_samples_fit_tables_and_read_back`, `test_table_columns_match_contract_fields[hunt-hunts]`, `test_check_constraints_reject_values_outside_contract[hunt-…]`, `test_id_arrays_reject_null_ids_and_missing_ids[hunt_…]`
- 손으로 확인(임시 DB): 0001만 적용하고 `origin = l3` Ticket 1건을 넣은 뒤 실행기를 돌리면 `MigrationError`로 멈추고 `schema_migrations`에 1행, `hunts` 테이블 없음
