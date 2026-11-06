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
