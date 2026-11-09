---
issue: 273
date: 2026-11-09
owner: Juhyeok0603
supersedes: []
---

# 출력 계약의 중첩 스키마를 프롬프트에 넣는다

## 목표

`compose_instructions()`의 자동 층에 기존 최상위 필드 요약과 완전히 해소한 JSON Schema를 함께
넣는다. 모델이 `incident_findings`·`incident_analysis` 등의 중첩 객체·배열 모양을 추측하지
않고 출력 계약을 맞추게 한다. 같은 계약은 항상 같은 지시문과 `prompt_version`을 만든다.

## 방법

- `src/soc/agent/compose.py`의 5층 자동 지시에 다음 순서로 넣는다.
  1. 최대 턴 문장
  2. 기존 `_contract_summary()`의 최상위 필드 요약
  3. 고정 제목 아래 완전히 해소한 출력 계약 JSON Schema
  4. `decided_at` 안내(해당 계약만)
- 기존 `_resolve()`의 `파일#/JSON 포인터` 참조 해소 규칙을 재사용하되, `properties`만이 아니라
  스키마 전체의 dict·list를 재귀로 순회한다. `anyOf`, `allOf`, `if/then/else`, `items` 안의
  `$ref`도 모두 해소한다.
- 재귀 깊이는 100으로 제한해 향후 순환 참조나 비정상적으로 깊은 스키마가 재귀 오류로 이어지지
  않게 한다. 현재 계약에는 순환 `$ref`가 없다.
- 해소한 스키마는 `json.dumps(..., ensure_ascii=False, sort_keys=True)`로 compact JSON 문자열로
  만들고 계약별로 캐시한다. `description`은 모델에 필드 의미를 알려 주므로 제거하지 않는다.
- 실측한 해소 스키마 길이는 운영 출력 계약 중 `incident_findings` 2,230자가 가장 크고, 등록된
  전체 계약 중에서는 `hunt` 4,541자가 가장 크다. 운영 L2 작업 지시문은 스키마를 더하면
  `l2_investigate` 약 3,585자, `l2_report` 약 3,308자다. `max_input_chars`는 지시문과 데이터의
  합계이므로, 이 변경은 데이터 여유를 스키마 크기만큼 줄인다. 기존 예산 필터는 그대로 둔다.
- 테스트는 `tests/fixtures/contracts/valid/`의 기존 손으로 만든 샘플을 재사용한다.
  - `CONTRACT_NAMES` 전체 20개를 `compose_instructions()`로 합성해 예외가 없는지 확인한다.
  - 자동 층의 JSON Schema 블록을 다시 파싱하고, `$ref`가 남지 않았는지와 기존 유효 샘플이
    그 스키마를 통과하는지 확인한다. `common/types.schema.json`은 참조 전용이라 직접
    `output_contract`가 될 수 없고, 다른 계약의 `$ref` 해소로 확인한다.
  - `incident_findings`의 `timeline[]`·`entities[]` 중첩 필드(`time`, `summary`, `evidence_ids`,
    `entity`)가 출력 스키마에 있는지 확인한다.
  - 결정성 테스트는 새로 만들지 않고 기존
    `test_same_input_same_hash_and_one_char_differs`, `test_hash_does_not_change_between_calls`,
    `test_domain_order_does_not_change_hash`가 계속 통과하는지 본다.
  - 기존 `decided_at` 단언 테스트 두 개도 유지한다. `entity`·`hunt` 스키마에는
    `decided_at`이 없기 때문에 해소본을 넣어도 단언이 통과해야 한다.

## 바꿀 곳

- `src/soc/agent/compose.py`: 스키마 전체의 `$ref`를 해소하고 안정적인 JSON Schema 블록을 5층에 추가
- `tests/test_agent_prompts.py`: 전체 등록 계약, 기존 fixture, 중첩 필드, 깊이 제한 회귀 테스트
- `docs/notes/273-output-contract-schema.md`: 개발 결과와 스키마 길이·실제 모델 확인 결과

## 다른 코드와 맞물리는 곳

- `src/soc/agent/runner.py`는 합성된 지시문의 SHA-256을 `prompt_version`으로 쓴다. 이 변경 후 새 run의
  `prompt_version`이 바뀌는 것은 의도한 동작이다.
- 같은 파일의 입력 예산 필터는 지시문과 동적 데이터의 합계를 계속 검사한다. 설정 키와 상한은
  바꾸지 않는다.
- 운영에서 `AgentTask.output_contract`로 쓰는 계약은 `verdict`, `branch_decision`,
  `incident_findings`, `incident_analysis`, `hunt_hypotheses`, `hunt_verification` 여섯 개다.
  `compose_instructions()`는 테스트나 후속 코드에서 다른 등록 계약으로도 불릴 수 있으므로 전체를
  지원한다.
- 공개 함수, 데이터 계약, DB, 설정 키는 바뀌지 않는다.

## 범위 밖

- OpenAI structured outputs(`output_type`) 도입. 구조화 출력을 쓰지 않는 것은 D-022에 이미 확정됐다.
- `[llm] strict_mode`, 형식 오류 재요청 횟수, `max_input_chars` 기본값 변경
- JSON Schema의 필드·제약·설명 변경, `description` 제거
- 작업별 도구 허용 목록. 현재 `l2_report`도 L2 단계 도구를 등록받는 문제는 별도 이슈로 다룬다.
- 시연 서버의 수정된 `runner.py`에 기대는 `l2_report` 전체 저장 E2E. 이 이슈에서는 깨끗한
  체크아웃으로 `l2_investigate`가 중첩 계약을 통과하는 것까지 실제 모델로 확인한다.

## 완료 기준

- [ ] 기존 최상위 필드 요약 아래에 compact JSON Schema 블록이 들어간다.
- [ ] `incident_findings`의 `timeline[]`·`entities[]` 필수 필드 `time`, `summary`, `evidence_ids`,
      `entity`가 해소된 스키마에 있다.
- [ ] dict·list 전체를 순회해 `properties`, `items`, `anyOf`, `allOf`, `if/then/else` 안의 `$ref`를
      해소하고, 합성된 스키마에 `$ref`가 남지 않는다.
- [ ] 스키마 재귀 깊이가 100을 넘으면 명확한 예외로 합성을 멈춘다.
- [ ] `CONTRACT_NAMES` 전체 20개가 예외 없이 합성되고, 합성된 스키마가 기존 유효 fixture를 통과시킨다.
- [ ] 결정성을 위한 새 테스트를 추가하지 않고, 기존 해시·도메인 순서 회귀 테스트 3개가 계속
      통과한다.
- [ ] `entity`·`hunt`의 `decided_at` 비포함 회귀 테스트 2개가 계속 통과한다.
- [ ] 스키마는 `ensure_ascii=False`, `sort_keys=True`로 직렬화되고 `description`을 유지한다.
- [ ] 실측 길이와 지시문 증가량을 개발 기록에 남기고, 입력 예산이 지시문+데이터 합계라는 점을
      함께 적는다.
- [ ] 깨끗한 시연 서버 체크아웃에서 해당 Incident의 라운드를 되돌린 뒤 `l2_investigate`를 한 번
      실행해 `incident_findings` 계약을 통과하는지 본다. 실제 문자열은 기록하지 않는다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과한다.
- [ ] `docs/plans/273-output-contract-schema.md`와 `docs/notes/273-output-contract-schema.md`가 있다.

## 토론으로 정한 것

- 이슈 초안의 "`properties`를 재귀로 훑다"는 부족하다. `branch_decision`의 `anyOf`와
  `allOf/else`에도 `$ref`가 있어 dict·list 전체를 순회한다.
- 초안의 "가장 큰 계약은 `incident_analysis`"는 틀렸다. 운영 출력 계약 중에서는
  `incident_findings` 2,230자가 가장 크고, 등록된 전체 계약 중에서는 `hunt` 4,541자가
  가장 크다. 여유가 추가로 필요하지 않아 `description`은 빼지 않는다.
- structured outputs로 가지 않는 것은 새 결정이 아니다. D-022가 `output_type`을 쓰지 않도록 이미
  확정했고, D-009와 #224 기록에 Foundry strict 빈 응답이 있다. `docs/decisions.md`는 바꾸지 않는다.
- 결정성은 기존 테스트 3개가 이미 검증하므로 중복 테스트를 만들지 않는다.
- 합성은 현재 운영에서 쓰는 여섯 계약만이 아니라 `CONTRACT_NAMES` 전체를 지원한다.
- 시연 서버의 `l2_report` 도구 제거는 로컬 손수정이고 이 이슈의 깃 변경이 아니다. 재현 가능한 수동
  확인 범위를 `l2_investigate`의 `incident_findings` 계약 통과까지로 줄이고, 작업별 도구 허용은 별도
  이슈에서 다룬다.

## 바뀐 점
