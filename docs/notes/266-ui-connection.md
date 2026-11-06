---
issue: 266
date: 2026-11-06
owner: Pandyo
plan: 266-ui-connection.md
supersedes: []
---

# UI 연결 개발 기록

## 한 일

조회 API 11개와 서버 집계를 추가했다. RawRecord 기준 성공·실패·대기 목록과 계약 상세를 제공한다.
Ticket 위험도는 연결 Alert의 최댓값으로 계산하고 Case 대기는 Incident 상태로 조회한다.
API → 시드 → 화면 순서로 개발 중이다.

## 계획과 달라진 점

API 전용 모델과 SQL 읽기를 ui_models.py·ui_read.py로 분리했다. 기존 models.py의 Hunt 응답은 유지한다.

## 다음 사람이 알아야 할 것

시드 식별자는 dev-seed-ui다. 기존 dev-seed·dev-seed-l1과 details.dev_seed 표시를 공유하지 않는다.
시드 명령은 삭제 기능 없이 --yes로 명시적으로 실행한다.

## 확인 방법

단계별 테스트 결과를 아래에 기록한다.

- API 단계: 새 경로가 없어 테스트 5건이 404로 실패하는 것을 확인한 뒤 구현했다.
- API 단계: 기본 pytest 1,284건, 신규 DB 테스트 5건, ruff check와 Python 계약 생성 차이 검사 통과.
- 기본 pytest 종료 시 기존 FakeSshServer pending-task 경고 3건이 출력됐다(종료 코드 0).

- API 단계 전체 DB 회귀: 384건 통과(임시 로컬 PostgreSQL, 92.56초).
- 시드 단계: 모듈이 없어 테스트 수집이 실패하는 것을 확인한 뒤 구현했다.
- 시드 단계: 기본 3건·DB 3건 통과. 확인 인자 없는 실행의 연결 금지, 재실행 0건,
  충돌 전체 롤백, 기존 L1·L3 시드 삭제 뒤 UI 시드와 실제 자료 보존을 확인했다.
- 시드 표시는 details.seed_source와 raw_records.siem_profile에 저장한다. 상태·Artifact·Proposal은
  부모로 표시를 찾는다. 기존 L3의 details.dev_seed 키를 쓰지 않아 삭제 대상에 포함되지 않는다.
- 시드 API·개발 명령만으로 사용할 수 있는 커밋을 화면 구현 전에 남겼다.
