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
API → 시드 → 화면 순서로 구현하고 각 단계에 커밋을 남겼다.
대시보드·Alert/Event·Ticket·Incident·Case·Hunting을 실제 조회 API에 연결했다.
목록의 필터·페이지 이동, 오른쪽 상세 패널과 원본 이동, 로딩·빈 상태·오류 재시도를 제공한다.
Case의 승인 대기는 awaiting_review Incident로 명시하고 승인·반려는 비활성이다.

## 계획과 달라진 점

API 전용 모델과 SQL 읽기를 ui_models.py·ui_read.py로 분리했다. 기존 models.py의 Hunt 응답은 유지한다.
목표·범위·공통 계약 변경은 없다. Hunt 목록에는 기존 응답에 seed_source가 없으므로 합성 가설
제목에 [dev-seed-ui]도 붙여 목록에서 구분한다. 상세는 details.seed_source로 표시한다.

## 다음 사람이 알아야 할 것

시드 식별자는 dev-seed-ui다. 기존 dev-seed·dev-seed-l1과 details.dev_seed 표시를 공유하지 않는다.
시드 명령은 삭제 기능 없이 --yes로 명시적으로 실행한다.
--yes는 개발 DB임을 사람이 확인했다는 인자이며 호스트 이름으로 운영 DB를 판별하지 않는다.
실행기와 분리하고 마이그레이션을 마친 개발 DB를 DATABASE_URL로 지정한다.
샘플 변경 뒤 기존 같은 ID의 내용과 달라지면 시드가 덮어쓰지 않고 충돌로 종료한다.

TypeScript는 계약과 API 모델 JSON Schema에서 28개 파일을 생성한다. 생성 결과도 Prettier로
포맷하며 ESLint·Prettier 검사 대상이다. MSW는 테스트에서만 실행한다.
Node 22.22.3·pnpm 11.9.0·TypeScript 6.0.2를 고정했다. TypeScript 버전은 현재
typescript-eslint의 지원 범위와 맞췄다. 새 환경변수는 없다.
개발 명령과 프록시 설명은 CONTRIBUTING.md, CI의 frontend job은 타입 생성 차이·lint·test·build를 검사한다.
빌드는 통과하지만 Recharts를 포함한 단일 JS 청크가 약 719 kB(gzip 215 kB)라 Vite 크기 경고가 있다.
현재 정적 조회 화면이며 자동 주기 갱신·승인 동작·인증·배포는 범위 밖이다.

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
- 화면 단계: App 모듈이 없어 테스트가 실패하는 것을 확인한 뒤 구현했다.
- 미상 위험도만 있는 데이터에서 미상 건수가 사라지는 실패 테스트를 추가한 뒤 표시를 고쳤다.
- 최종 기본 pytest 1,287건·DB pytest 387건 통과. FakeSshServer의 기존 pending-task 경고는 동일하다.
- uv run ruff format --check ., uv run ruff check ., Python 계약 생성 --check 통과.
- pnpm lint, pnpm test(5건), pnpm build, pnpm contracts:check(28개 일치) 통과.
  고정 lockfile 설치와 strict peer dependency 검사도 통과했다.
- 화면 테스트는 Case/Incident 구분·비활성 버튼, 외부 문자열의 텍스트 표시, L3 Hunt 이동,
  필터 변경 시 cursor 초기화, 오류 재시도·빈 목록, 미상 위험도를 검증한다.
- 임시 로컬 PostgreSQL에 마이그레이션·시드를 적용하고 실제 API와 Vite를 실행했다.
  Safari·Chrome에서 6개 화면의 집계·목록, Case 대기 Incident 상세와 Artifact·Proposal,
  원본 Ticket→Alert 이동, Event 성공·실패·대기 혼합 목록을 확인했다.
- Hunt 제목의 시드 표시도 실패 테스트로 먼저 확인하고 보완했다. 변경 뒤 API·시드 테스트
  17건(DB 포함)과 화면 테스트 5건을 다시 확인했다.
