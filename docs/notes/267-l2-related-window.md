---
issue: 267
date: 2026-11-11
owner: Juhyeok0603
plan: 267-l2-related-window.md
supersedes: [261-l2-incident-analysis.md]
---

# L2 주변 기록 구간과 분포를 넓힌다

## 한 일

Incident 문맥 Alert·Event의 가장 이른 시각에서 3일 앞부터 주변 기록을 읽고, 둘 다 없으면
Ticket 생성 시각을 쓴다. 최근 연결 Ticket의 엔티티를 먼저 조회한다. 4개 시간 버킷과
Alert·Event 종류에 차례로 선택 기회를 주고, 빈 몫을 다른 곳에 양도한다. 엔티티당 20건과
중복 제거 뒤 전체 80건 상한을 적용한다. 모델에는 간결한 `related` 레코드와 도구의 1회
조회 한도를 보내고, Alert·Event 시간 인덱스를 새 마이그레이션에 추가했다.

## 계획과 달라진 점

없음.

## 다음 사람이 알아야 할 것

- `0006_related_time_indexes.sql`은 수집을 멈춘 상태에서 적용한다. 일반 `CREATE INDEX`는 빌드 동안 해당 테이블 쓰기를 기다리게 한다.
- 주변 기록의 전체 80건 상한은 글자 수 상한이 아니다. 제목·요약·엔티티 값과 나머지 문맥이 크면 기존 `budget_exceeded` 경로로 끝난다.
- 임시 PostgreSQL 18 DB에서 `generate_series`로 Alert·Event를 각 30,000건 만들고, 한 엔티티가 각 테이블의 30,000건과 일치하는 넓은 구간 조회를 `EXPLAIN ANALYZE`로 확인했다. 두 테이블 모두 시간 인덱스 대신 순차 스캔과 외부 병합 정렬을 골랐다. Alert는 약 107ms·정렬 디스크 약 5.4MB, Event는 약 88ms·약 5.2MB였다. 한 엔티티당 두 쿼리이고 최대 10개 엔티티이므로 이런 분포에서는 그만큼 누적된다. 합성 행과 측정 SQL은 커밋하지 않는다.
- Windows의 기존 `test_name_ending_in_newline_is_not_a_migration`은 줄바꿈 파일명을 만들지 못해 실패한다. Linux 전체 테스트에서 통과했다.
- DB 접속이 실패하면 pytest의 상세 traceback이 연결 문자열을 출력할 수 있다. `.env` 비밀번호가 이 작업의 도구 출력에 한 번 노출됐으므로 해당 비밀번호는 교체해야 한다. 이후 DB 검사는 비밀이 없는 임시 DB를 사용했다.

## 확인 방법

- `uv run pytest tests/test_l2_analyze.py tests/test_l2_config.py tests/test_l2_worker.py -q`: 32건 통과.
- 임시 PostgreSQL DB에서 `uv run pytest -m db tests/test_l2_branch_db.py tests/test_lab_cycle_db.py tests/test_db_tables.py -q`: 첫 실행 132건 통과. 이후 폴백·전체 상한 테스트 2건을 더했고 각각 통과했다.
- 임시 PostgreSQL DB의 합성 Alert·Event 각 30,000건에 `EXPLAIN ANALYZE`: 위 실행 계획과 시간 확인.
- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- Linux Python 3.13에서 `uv run pytest`: 1,485건 통과, 기본 제외 표식 456건. 기존 SSH fake server의 종료 시 pending task 경고가 출력됐으나 종료 코드는 0이었다.
