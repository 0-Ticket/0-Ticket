---
issue: 365
date: 2026-11-20
owner: Pandyo
plan: 365-pen-screens.md
supersedes: []
---

# pen 디자인 화면 구현과 Incident 승인·반려 API (개발 중, 일부 미완)

## 한 일

- Incident 승인·반려 API(D-076): `POST /api/incidents/{id}/approve|reject`. Incident 행을 `FOR UPDATE`로 잠그고 `awaiting_review`일 때만 적용하며, 아니면 409(`incident_not_awaiting_review`와 현재 상태)다. 승인은 같은 트랜잭션에서 `cases`에 `open` 행을 만들고 Incident를 `confirmed`로 바꾼다. 반려는 `analyzing`으로만 바꾸고 기존 L2 워커가 재분석한다. `incident.approve`·`incident.reject`는 이제 라우트가 쓰는 권한이다(`UNUSED`는 `incident.close`만).
- Ticket 상세 응답에 원본 Alert 요약(`alerts`: id·title·time·severity)을 쿼리 한 번으로 더했다. Incident 상세 응답에 소속 Ticket의 제목(`tickets`)을 더했다.
- 화면: Ticket 상세(연결된 Incident, 원본 Alert 요약, 근거 검토, 엔티티, 이력), Incident 상세(사건 요약, 영향, 소속 Ticket 제목, 엔티티, 가장 최근 라운드의 권고 조치만, 분석 이력, 승인·반려 버튼), "내 승인 대기"→"승인 대기", Ticket 상태 이름(판정 대기·오탐 종결), 사용자 관리에서 `incident.approve`·`incident.reject` 개별 부여.

## 계획과 달라진 점

- 커밋을 화면 그룹별로 더 잘게 나누지 못했다. 한 테스트 파일(`App.test.tsx`)이 여러 그룹의 변경을 함께 담아 Ticket·Incident·대시보드 화면을 한 커밋(`feat(frontend): align ticket, incident and dashboard screens …`)으로 합쳤다.
- 제안은 API를 바꾸지 않고 화면이 가장 큰 `analysis_round`의 Artifact에 붙은 것만 보여 준다(계획대로). 최신 라운드는 `artifacts`에서 `analysis_round`가 가장 큰 것으로 고른다.
- 승인·반려 오류 화면은 409에서 현재 상태 이름을 보여 주려고 `ApiError`에 `state`를 더했다(`api/client.ts`).

## 다음 사람이 알아야 할 것

**아직 하지 않은 것(계획의 "바꿀 곳"·완료 기준 중)**

- 디자인과 화면을 나란히 놓고 하는 시각 대조(간격·색·정렬)는 하지 않았다. 문구와 구조만 `.pen` 텍스트와 비교했다. 사이드바·사용자 영역·로그인·가입·가입 완료·비밀번호 변경·403·설정·사용자 관리·Ticket 정책·Alert/Event·Case·Hunting 화면은 문구 대조에서 계획에 쓴 차이(아래)만 확인했고 코드는 바꾸지 않았다.
- 엔티티 그래프 노드 패널의 "자산 중요도"는 만들지 않았다. Incident 상세 응답에 자산 정보(`assets[].criticality`)가 없어 응답을 더 넓혀야 하고, 계획의 "바꿀 곳"에 없던 계약 변경이다.
- 빈 상태·로딩·오류 상태가 화면마다 있는지는 새로 점검하지 않았다(기존 구현을 그대로 둔다).
- 사람이 확인할 시나리오 9개, 화면 전·후 스크린샷, L1·L2·L3 담당 승인, PR 본문에 쓸 "디자인과 다른 곳"은 아직 하지 않았다.

**디자인과 다른 곳(PR에 적을 것)**

- 심각도 문구: 디자인 파일은 한국어(치명…미상), 구현은 D-074(`N Level`·미상·"—").
- 대시보드 카드 제목: 디자인은 "심각도별 Ticket"·"Incident 심각도 Top 10", 구현은 "Tickets by Risk Level"·"Incident Risk Top 10"(#363이 제목을 유지하기로 한 기록을 따랐다).
- Incident 상태 이름: 디자인 목록은 "사람 검토 대기"·"승인됨"·"사람이 직접 처리", 디자인 Top 10 카드는 "승인 대기"·"승인/확인됨"·"사람 처리"로 서로 다르다. 구현은 후자를 쓴다.
- Top 10: 디자인 샘플 행에 확정·기각이 있으나 구현은 뺀다(D-077).
- "내 승인 대기"→"승인 대기", 승인·반려 안내 문구 제거, 근거별 강도·"N개 신호 일치" 미표시, "Entity 공격 경로" 모드·CSV 등록 동작 미구현.
- Ticket 상세의 엔티티·이력 표와 Incident 상세의 분석 이력은 디자인 구성을 따르되, 구현에는 JSON 원본 보기(`Ticket 원본`, `Incident`, 라운드별 보고서)를 남겼다(계획 274의 "살리는 기능").

**함정**

- 반려 후에는 L2 워커가 `analyzing` Incident를 집어 바로 재분석한다. `review_round`는 오르지 않아 D-028의 한도(`human_handling`)가 작동하지 않는다(별도 이슈). 재분석에는 LLM 비용이 든다.
- Case가 생기면 유사 사례 검색 도구(D-053)의 `decided_by`가 해당 Incident의 Ticket에서 `human`으로 바뀐다.
- 로컬에서 `-m db` 테스트를 돌릴 때 `.env`의 `DATABASE_URL`이 가리키는 DB 이름(`zt_dev`)이 로컬 서버에 없어서, 같은 서버의 `zt`로 바꾼 값을 그 명령에서만 환경변수로 줬다(`.env`는 고치지 않았다). 임시 DB는 테스트가 만들고 지운다. `-m qdrant` 테스트는 `QDRANT_URL`이 `.env`에 없어서 `http://127.0.0.1:6333`을 그 명령에서만 줬다.
- 이 PC 부하가 높을 때(load average 40~50) `pnpm test`가 무작위 테스트에서 5초 제한에 걸려 실패했다(`severity.test.ts`, `users.test.tsx`, `ticket-detail.test.tsx` 등이 번갈아). `pnpm exec vitest run --maxWorkers=2 --testTimeout=30000`로는 115건이 모두 통과했다. 테스트 설정은 바꾸지 않았다.
- `pnpm test -- <파일>`은 파일 필터를 쓰지 않고 전체를 돌린다(`vitest run` 앞의 `--`가 그대로 전달돼서). 특정 파일만 돌리려면 `pnpm exec vitest run <파일>`을 쓴다.

## 확인 방법

- `uv run pytest tests/test_api_review.py tests/test_api_detail.py tests/test_auth.py tests/test_api.py tests/test_api_ui.py -m "db or not db"`(`DATABASE_URL`은 위처럼 `zt`로): 통과.
- 주요 테스트: `test_approve_confirms_the_incident_and_creates_one_open_case`, `test_simultaneous_requests_let_exactly_one_through`, `test_other_states_answer_409_with_the_current_state_and_change_nothing`, `test_ticket_detail_query_count_does_not_grow_with_alerts`, `test_dashboard_top_incidents_leave_out_confirmed_and_dismissed`, 프런트 `review.test.tsx`, `ticket-detail.test.tsx`, `users.test.tsx`.
- `uv run ruff format --check .`, `uv run ruff check .`: 통과. `uv run pytest`: 2680건 통과. `uv run pytest -m "db or qdrant"`(위 환경변수로): db 659건과 qdrant 24건 통과.
- `pnpm contracts:check`, `pnpm lint`(경고 1건은 기존 `flow-chart.tsx`), `pnpm build`: 통과. `pnpm exec vitest run --maxWorkers=2 --testTimeout=30000`: 115건 통과.
- 손으로 확인한 것은 아직 없다.
