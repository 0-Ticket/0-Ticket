---
issue: 273
date: 2026-11-09
owner: Juhyeok0603
plan: 273-output-contract-schema.md
supersedes: []
---

# 출력 계약의 중첩 스키마를 프롬프트에 넣는다

## 한 일

`compose_instructions()`의 자동 층에 기존 최상위 요약과 함께 완전히 해소한 JSON Schema를 넣었다.
dict·list 전체를 순회해 `anyOf`·`allOf`·`items` 안의 `$ref`까지 해소하고, 현재 해소
경로의 참조 홉 수를 100으로 제한했다. 해소본은 키 순서를 고정한 compact JSON으로 캐시한다.
등록 계약 20개의 기존 유효 fixture를 프롬프트에서 다시 파싱한 스키마로 검증했고,
`incident_findings` 중첩 필드·100홉 경계·기존 해시 결정성을 회귀 테스트로 확인했다.

## 계획과 달라진 점

없음.

## 다음 사람이 알아야 할 것

- 기존 계약 fixture가 등록 계약 20개의 유효 샘플을 이미 갖고 있어 새 fixture 파일을 만들지
  않고 프롬프트에서 다시 파싱한 해소 스키마로 같은 샘플을 검증한다.
- Draft-07 검증은 `$ref` 형제를 무시하지만 기존 `_resolve()`는 형제를 병합한다. 현재 형제는
  `case`·`incident`의 `description`뿐이라 검증 제약은 달라지지 않는다.
- 해소 스키마는 `alert` 6,701자가 전체 최대고, 운영 출력 계약은 `incident_findings`
  2,230자가 최대다. 빈 데이터로 합성한 L2 지시문은 `l2_investigate` 3,585자,
  `l2_report` 3,308자다. 실제 입력 예산은 이 지시문과 동적 데이터의 합계다.
- 시연 서버의 Incident 라운드 변경과 실제 모델 `l2_investigate`는 이 개발 세션에서 확인하지
  않았다. 실제 문자열을 다루지 않고 사람이 시연 서버에서 계약 통과 여부만 확인해야 한다.

## 확인 방법

- 테스트 먼저: `uv run pytest tests/test_agent_prompts.py -q` — 구현 전 22건 실패, 구현 후 61건 통과
- `uv run ruff format --check .` — 293개 파일 통과
- `uv run ruff check .` — 통과
- `uv run pytest` — 1,309건 통과, 1건 실패. 실패는 Windows가 줄바꿈이 든 파일명을 만들지 못해
  나는 기존 `tests/test_migrate.py::test_name_ending_in_newline_is_not_a_migration`이고, `origin/main`에서도
  같은 제한이다.
- 길이 실측 — 해소 스키마 `alert` 6,701자·`incident_findings` 2,230자, L2 지시문
  `l2_investigate` 3,585자·`l2_report` 3,308자
