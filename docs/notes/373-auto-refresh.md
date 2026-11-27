---
issue: 373
date: 2026-11-27
owner: Pandyo
plan: 373-auto-refresh.md
supersedes: []
---

# 화면이 10초마다 조용히 다시 조회되고, 자동 요청은 세션 유휴 시간을 늘리지 않는다

## 한 일

- 대시보드(집계 차트), Alert·Event·Ticket·Incident·Case·Hunting 목록, 상세 패널, Incident 페이지가 10초마다 다시 조회된다(`frontend/src/live.ts`). 숨은 탭에서는 멈추고 보이게 되거나 온라인으로 돌아오면 즉시 한 번 읽는다. 연속 실패하면 10→20→40→60초, 성공하면 10초다. `?sample=`·`me`·정책·사용자 관리는 갱신하지 않는다.
- 자동 요청에는 `X-Auto-Refresh: 1`이 붙는다. 서버는 그 GET에서 세션·권한 검사는 똑같이 하고 `last_seen_at`만 갱신하지 않는다(`store.find_session_user(touch=False)`, `api/auth.py`).
- 갱신이 실패해도 네트워크 오류·5xx는 받은 값을 유지하고(`failure()`), 401은 로그인 화면, 403·404는 에러 화면이다. 제목 줄 오른쪽(Incident 페이지는 `incident-nav`)에 "마지막 갱신 HH:MM:SS"가, 실패 중에는 "갱신 실패 · 마지막 성공 …"이 보인다.
- 반려 창과 입력한 사유는 상태가 바뀌어도 남고, 상태·`review_round`·`analysis_round`가 창을 연 때와 달라지면 안내가 뜬다. 상태가 `awaiting_review`가 아니면 "반려하기"가 꺼진다. 409 안내도 다시 조회한 뒤에 남는다.
- 관계 그래프는 처음 그린 노드 자리와 확대·화면 위치를 고정하고 새 노드만 더한다.

## 계획과 달라진 점

- 정책 쿼리(`layout.tsx`)에도 `refetchOnReconnect: false`를 줬다. 갱신 대상은 아니지만 재연결 때 표시 없이 읽혀 유휴 시간을 늘리기 때문이다. 정책 화면·사용자 관리 화면의 쿼리는 그대로라 재연결 때 표시 없이 읽을 수 있다(알려진 한계).
- 갱신 때 진행 중인 요청을 `signal`로 취소하지 않는다. 화면을 벗어나면 타이머와 이벤트만 정리하고 이미 나간 요청은 끝까지 받는다. 취소하면 TanStack이 그 쿼리를 오류 상태로 두기 때문이다. 이탈 뒤 새 요청은 나가지 않는다.
- 409 안내를 `Header`로 옮기는 대신 `ReviewActions`가 상태와 관계없이 안내와 창을 그리게 했다(`Header` 안에서 항상 마운트돼 있어 같은 효과다).
- 자동 갱신 훅은 테스트를 구현 뒤에 맞춰 썼다. 새 테스트가 옛 코드에서 실패하는 것은 확인했다(반려 창 4건, 다음 페이지 버튼 깜빡임, 그래프 이동, 재연결 조회).
- 새 `tests/fixtures`는 만들지 않았다. 기존 `ui_seed.json`과 `incident_graph*.json`을 썼다.

## 다음 사람이 알아야 할 것

- **TanStack은 `queryFn` 안에서 요청이 타이머 때문인지 모른다.** 표시를 붙이려고 갱신 훅이 `fetchQuery`로 직접 읽는다. 갱신 대상 쿼리를 새로 만들 때는 `useLiveQuery`를 쓰고, 일반 `useQuery`로 쓰면 갱신되지 않는다. 같은 쿼리의 사용자 요청과 자동 요청이 동시에 나가면 TanStack이 하나로 합쳐 먼저 나간 쪽 표시가 따라간다.
- 테스트에서 타이머를 기다리지 않으려고 `window`의 `online` 이벤트로 같은 자동 읽기를 일으킨다(`auto-refresh.test.tsx`의 `refreshOnce`). `onlineManager`가 실제 오프라인→온라인 전환을 봐야 `refetchOnReconnect` 회귀가 잡힌다.
- 유휴 시간은 자동 요청이 아니라 사람이 시작한 요청만 늘린다. 화면을 켜 두기만 하면 마지막 사람 요청 뒤 `idle_timeout_seconds`(기본 3600)에 로그인 화면이 된다. 캐시로만 처리되는 클릭은 요청이 없어 늘리지 못한다(원래부터).
- 자동 요청도 인증용 쓰기 연결을 연다. 읽기 연결로 바꾸면 부하를 줄일 수 있지만 이번에는 하지 않았다.
- 엔티티 보기는 상위 60개만 그려서, 갱신으로 순위가 바뀌면 노드가 빠지거나 들어온다. 빠진 노드의 자리는 기억에 남는다.
- 1쪽 목록에서 새 행이 위에 들어오면 클릭 위치의 행이 밀릴 수 있다.
- 마지막 갱신 시각 표시는 `design/`에 프레임이 없어 기존 색·글자 크기(`--muted`, `--danger`, 12px)만 썼다. PR에 "디자인 없음"으로 표시하고 사람이 전·후 스크린샷을 붙인다(D-075).
- 로컬 DB 테스트는 `DATABASE_URL`이 `postgres` 같은 기존 DB를 가리키고 `127.0.0.1`이어야 돈다(375 기록과 같다).
- `pnpm test`가 가끔 1초 안에 못 끝나는 `findBy…` 때문에 실패했다(CPU가 바쁠 때 `ticket-detail.test.tsx` 같은 기존 테스트가 한두 건). 새 테스트 파일을 빼면 안 나왔고, 마지막 네 번의 전체 실행은 모두 통과했다. 원인은 확정하지 못했다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과. `uv run pytest`: 2711 통과.
- `uv run pytest -m db tests/test_auth_db.py`: 27 통과(새 테스트 3건: 표시 있는 GET은 유휴 시각 유지·권한 검사 같음, 61분·절대 만료는 401, POST에서는 표시 무시).
- `frontend/`에서 `pnpm contracts:check`, `pnpm lint`(경고 1건은 기존 `flow-chart.tsx`), `pnpm test`(236 통과), `pnpm build`: 통과.
- 주요 테스트: `live.test.tsx`(간격·백오프·숨은 탭·재연결·이탈·403·404 정지·마지막 갱신 문구), `auto-refresh.test.tsx`(표시 유무, 화면별 요청 수 홈 1·목록 3·Incident 1, 샘플·정책 제외, 값 유지·404·401·재시도), `review.test.tsx`(반려 창 4가지와 409 안내), `incident-graph.test.tsx`(새 노드가 와도 자리·확대 유지).
- 아직 하지 못한 것: `/api/dashboard`와 상세 API의 응답 시간(중앙값·p95, 측정 때 데이터 건수)은 세션이 필요해 측정하지 않았다. PR 전에 계획대로 재서 적는다. 전·후 스크린샷도 사람이 붙인다.
