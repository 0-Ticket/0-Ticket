---
issue: 305
date: 2026-11-13
owner: Juhyeok0603
plan: 305-related-entity-normalize.md
supersedes: []
---

# L2 주변 기록의 엔티티 값 비교를 맞춘다

## 한 일

`_related`가 저장 엔티티 원본을 타입별로 trim·소문자 비교해, 혼용 대소문자와 흔한
공백이 붙은 Alert·Event도 찾는다. 비교 식 선택은 `soc.entities._LOWER_TYPES`를
공유하고, 저장 데이터·조회 상한·출력 형식은 유지한다. 손 작성 샘플로 실제 DB의
양성·음성 매칭을 확인했다.

## 계획과 달라진 점

없음.

## 다음 사람이 알아야 할 것

- `src/soc/normalize/mapping.py`의 `_text()`는 원본 문자열을 유지한다. 조회 쪽만 비교용으로 바꾼다.
- `uv run pytest`는 `db` 표식 테스트를 실행하지 않는다. CI의 db job은 이미 PostgreSQL에서 실행한다.
- `entity_value_sql()`의 식은 `jsonb_array_elements(... ) item` 별칭에 맞춰져 있다. SQL에서
  `E' \t\n\r\f\v'`가 지정한 공백만 trim하며, Unicode 공백 전체와 IP 표기 정규화는 다루지 않는다.

## 확인 방법

- `uv run pytest tests/test_l2_analyze.py -q --tb=short`: 9건 통과. 구현 전에 새 함수 부재로
  1건 실패하는 것을 확인했다.
- 비밀번호 없는 일회용 PostgreSQL 17.6 컨테이너에서
  `uv run pytest -m db tests/test_l2_branch_db.py -q --tb=short`: 43건 통과.
- `uv run ruff format --check .`: 348개 파일 통과. `uv run ruff check .`: 통과.
- Windows `uv run pytest -q --tb=short`: 1,602건 통과, 1건 실패. 기존
  `test_name_ending_in_newline_is_not_a_migration`이 Windows에서 줄바꿈 파일명을 만들지 못한
  오류이며 #267 기록에도 같은 제한이 있다.
- Linux Python 3.13 일회용 컨테이너에서 `uv run pytest -q --tb=short`:
  1,603건 통과. 읽기 전용 마운트여서 pytest 캐시 쓰기 경고 2건과 기존 FakeSshServer의
  종료 시 pending-task 경고가 출력됐으나 종료 코드는 0이다.
