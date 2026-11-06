---
issue: 266
date: 2026-11-06
owner: Pandyo
supersedes: []
---

# UI 연결: 조회 API, 개발용 시드, 6개 화면

## 목표

개발용 시드로 채운 DB를 실제 API로 조회해 대시보드·Alert/Event·Ticket·Incident·Case·Hunting
6개 화면을 만든다. 목록 → 상세 패널 → 연결된 원본 이동이 동작한다.
로그·JSON·LLM 문장은 텍스트로만 표시한다.

## 방법

### API

- 기존 soc.api의 읽기 전용 연결·오류 형식·epoch ms 변환을 재사용한다. app.py는 등록만 추가한다.
- GET /api/dashboard: 전체 보관 자료의 집계를 같은 DB 스냅샷에서 읽는다.
- GET /api/alerts, /api/events 및 각각 /{id}: 성공·실패·대기를 같은 목록에서 상태 필터로 조회한다.
  RawRecord ID 내림차순과 마지막 raw ID cursor를 사용한다. 정규화 ID와 raw ID를 구분하며 상세는
  해당 종류의 정규화 ID 또는 raw ID를 받는다. 결과가 있으면 성공, 결과·상태가 없으면 대기다.
  성공 상세는 계약 객체·OCSF, 실패·대기는 RawRecord와 처리 상태를 제공한다.
- GET /api/tickets 및 /{id}: origin·status·위험도 필터. 위험도는 연결 Alert의 최댓값이며 없으면 0.
  계산 필드는 API 전용이고 Ticket 계약은 바꾸지 않는다. 상세에 Alert·Hunt 연결 ID를 제공한다.
- GET /api/incidents 및 /{id}: 상태 필터, Ticket 연결, 라운드별 Artifact·Proposal.
- GET /api/cases 및 /{id}: 승인된 Case와 Incident 연결. 승인 대기는 incidents의 awaiting_review다.
- 기존 /api/hunts 및 /{id}를 그대로 사용한다. 검증 과정은 기존 run 요약이다.
- 목록은 items·next_cursor, 기본 50·상한 200. Ticket·Incident·Case는 id DESC와 마지막 ID cursor.
  목록에는 원본·OCSF·Agent Log 입출력·분석 보고서 본문 등 큰 컬럼을 읽지 않는다.
  상세의 도메인 객체는 생성 모델을 사용하고 목록·집계·계산 필드는 API 전용 응답 모델로 둔다.
- 오류는 기존 404·422·503·500 형식을 유지하고 입력값·주소·예외 메시지를 노출하지 않는다.
- 집계: 정규화 대기, L1 pending Alert와 new Ticket, 전체 Ticket·Incident·Case 및 상태별 건수,
  Ticket 위험도별 건수, 종류별 정규화 성공·실패·대기, Artifact 있는 Incident 최신 10건,
  열린 Incident(analyzing/awaiting_review/human_handling)의 위험도 상위 10건,
  Hunt 상태별 수와 전체 Hunt 대비 Ticket이 생성된 Hunt 비율.
  Incident 위험도는 assessed_severity가 null일 때만 severity로 대체하고 동률은 id DESC.
  정규화 비율 분모는 성공+실패, 분모 0은 null(데이터 없음). 누적과 대기를 구분해 표기한다.

### 시드

- tests/fixtures/api/에 손으로 만든 샘플. 정규화 세 상태, 위험도 0~6, Ticket 출처·상태,
  Incident·Artifact·Proposal, Case, Hunt와 검증 run·연결 관계를 포함한다.
- 명령은 uv run python -m soc.api.dev_seed --yes. 확인 인자가 없으면 DB 연결 전에 종료한다.
  개발 전용 DATABASE_URL을 사용하며 앱 시작 시 자동 실행·마이그레이션·모델 호출은 하지 않는다.
- 전용 표시 이름은 dev-seed-ui. RawRecord.siem_profile과 details.seed_source에 기록한다.
  details가 없는 상태·Artifact·Proposal은 부모 관계로 식별하고 API에서 시드 표시를 제공한다.
  기존 dev-seed, dev-seed-l1 및 Hunt의 details.dev_seed=true는 사용하지 않는다.
- 고정 ID로 동일 샘플 재실행은 추가하지 않는다. 기존 자료를 삭제·덮어쓰지 않고 충돌 시 전체
  트랜잭션을 되돌린다. 삭제 명령은 만들지 않는다. 기존 시드 삭제 명령도 UI 시드를 선택하지 않는다.
- 실행기와 분리된 개발 DB에서 확인한다. Case는 합성된 승인 결과다. 출력은 건수만 남긴다.

### 화면·타입·검사

- 확정된 React/Vite/TypeScript, Tailwind/shadcn/ui, TanStack Query, React Router, Recharts,
  MSW(테스트 전용), Vitest/Testing Library, Node LTS/pnpm, ESLint/Prettier만 사용한다.
- 도메인 타입은 contracts에서 json-schema-to-typescript로 생성한다. API 포장 타입은 API 모델이
  내보내는 JSON Schema에서 같은 도구로 생성하고 차이를 검사한다. Python 생성 명령은 유지한다.
- Vite 프록시로 /api를 호출한다. 화면은 DB·SIEM·LLM을 직접 부르지 않는다.
- 이슈의 밝은 배경·흰 카드·남색 KPI·파란 강조색과 사이드바를 따른다. 6개 페이지에 표·차트,
  오른쪽 상세 패널과 원본 이동, 필터·페이지 이동, 로딩·빈 상태·오류·재시도를 둔다.
- 위험도 기본 눈금은 1~6, 0은 미상으로 별도 표시. L3 Ticket에 Alert가 없으면 Hunt로 이동한다.
- Case 탭 문구는 '승인 대기 Incident'와 '승인된 Case'이며 대기는 아직 Case가 아님을 설명한다.
  승인·반려 버튼과 로그인·설정은 비활성 자리만 둔다. 자동 주기 갱신은 하지 않는다.
- 외부 문자열은 HTML·마크다운·링크로 변환하지 않는다. 내부 이동은 검증한 ID로만 한다.
- frontend에서 pnpm lint(ESLint+Prettier), pnpm test(Vitest run), pnpm build(TypeScript+Vite).
  CI에 같은 검사와 생성 타입 차이 검사를 추가한다.

### 순서와 커밋

확정 계획 커밋 뒤 API → 시드 → 화면. 각 단계는 샘플 → 실패 테스트 → 구현 → 검사를 거친다.
API와 시드만으로도 먼저 쓸 수 있게 각각 커밋한다. 시간이 부족해도 API·시드의 사용 가능한
경계를 남기고 화면은 미완료로 명시한다. 전체 완료 범위에서 화면을 빼지는 않는다.

- docs(plans): add plan for ui connection (#266)
- feat(api): add read APIs and dashboard aggregates (#266)
- feat(api): add development seed for UI (#266)
- feat(frontend): connect SOC pages to APIs (#266)

## 바꿀 곳

- src/soc/api/: 라우트·응답 모델·시드 명령
- tests/fixtures/api/, API·시드·DB 테스트: 샘플과 동작 검증
- frontend/: 화면·API 연결·타입·테스트
- scripts/, .github/workflows/ci.yml: 타입 생성·차이 검사·화면 검사
- docs/decisions.md, CONTRIBUTING.md: 확정 명령·타입 생성 방식·실행법
- docs/notes/266-ui-connection.md: 단계별 기록

## 다른 코드와 맞물리는 곳

수집·정규화 테이블은 읽기만 한다. L1 Ticket 위험도는 API 계산이며 계약·상태 전이는 그대로다.
L2 Artifact·Proposal을 읽고 L3의 기존 Hunt API·run 요약·tickets.hunt_id를 사용한다.
공통 API 모델·라우트 검사·타입 생성·CI를 확장한다. 기존 정책 API와 Python 생성 명령은 유지한다.
테이블·공통 데이터 계약·마이그레이션 변경은 없다. 기존 L1·L3 시드의 식별자와 겹치지 않는다.

## 범위 밖

승인·반려·Case 생성 로직, 대응 실행, 인증·SIEM 설정 화면, 실시간 갱신, 서버 배포,
실제 로그·공개 데이터셋 적재.

## 완료 기준

- [ ] API 목록·상세·집계가 합성 샘플 기대값과 일치한다.
- [ ] 실패·대기, 미상 위험도, Alert 없는 L3 Ticket, 승인 대기 Incident를 구분한다.
- [ ] 필터·cursor·빈 목록·입력 오류·없는 ID·DB 장애를 테스트한다.
- [ ] 시드에 dev-seed-ui 표시가 있고 기존 시드와 구분되며 상호 삭제되지 않는다.
- [ ] --yes 없이는 DB에 연결하지 않고, 재실행 중복·기존 자료 변경이 없다.
- [ ] 실제 API로 6개 화면과 상세·원본 이동을 브라우저에서 확인한다.
- [ ] Case 대기 탭이 awaiting_review Incident임을 문구로 표시한다.
- [ ] 외부 문자열이 실행·HTML·마크다운·링크로 변환되지 않는 테스트가 있다.
- [ ] ruff format --check, ruff check, pytest, pytest -m db(모두 uv run)가 통과한다.
- [ ] pnpm lint, pnpm test, pnpm build와 Python·TypeScript 생성 차이 검사가 통과한다.
- [ ] 계획·기록·CI를 남긴다. 새 환경변수가 있으면 .env.example에 이름만 둔다.

## 토론으로 정한 것

- 이슈 번호 오기를 #226에서 #266으로 바로잡았다.
- 집계 한 엔드포인트, 실패 혼합 목록과 필터, 검사 세 명령(D-017)을 확정했다.
- 공통 계약 0~6을 보존하고 0은 미상으로 표시한다. Ticket 위험도는 조회 때 계산한다.
- Case 승인 대기는 Incident이며 탭·설명에 분명히 적는다. 승인은 구현하지 않는다.
- API 포장 타입 생성 방식(D-003)을 정하고, 실패 목록은 raw ID 기준으로 페이지 처리한다.
- 개발 시드 표시·--yes·비파괴 재실행을 추가하고 API·시드 단계별 사용 가능한 커밋을 남긴다.

## 바뀐 점
