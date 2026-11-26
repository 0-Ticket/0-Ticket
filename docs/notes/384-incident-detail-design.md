---
issue: 384
date: 2026-11-26
owner: Pandyo
plan: 384-incident-detail-design.md
supersedes: []
---

# Incident 상세 화면이 디자인 프레임 구성에 맞게 보완되고 그래프는 숨기지 않고 흐리게 강조한다

## 한 일

- 분석 이력 탭은 `artifacts[]`를 라운드 타임라인(Round N, 판정, 심각도, 시각, 요약)으로 보인다. 원본 JSON은 하단 접힘 "원본 보기(고급)"에 있다.
- 개요 탭은 2단이다. 왼쪽은 사건 요약·영향(비면 제목도 숨김)·소속 Ticket(행 전체가 링크, UUID·복사 없음, 시각·근거 수·판정·심각도), 오른쪽은 핵심 엔티티(연결 Ticket 수 상위 3개)와 권고 조치(우선순위·카테고리 칩)다.
- 헤더는 요약 숫자와 진행 단계를 한 줄로 줄였고 탭 줄이 sticky다(예전에는 헤더 전체가 sticky였다). 엔티티 탭은 값 열 너비를 넓히고 "그래프에서 보기"를 더했다. Ticket 탭은 상세 링크를 행 끝으로 옮기고 시각을 한 줄로 두었다.
- 그래프는 노드를 hover하거나 선택하면 직접 연결된 노드·선만 그대로 두고 나머지를 투명도 0.3으로 흐리게 한다. 숨기거나 빼지 않는다. 우측 패널에는 엔티티의 `src`→`dst` 직접 이웃 목록("이 노드의 연결")이 있다.
- `?tab=graph&view=entity&node=<JSON [type, value]>`로 그래프가 그 엔티티를 선택해서 연다.
- 개발 전용 샘플 모드: 개발 서버에서 `/incidents/<id>?sample=graph`(104개 엔티티)와 `?sample=empty`(Ticket 0건). 로그인과 `incident.read` 권한은 필요하다.

## 계획과 달라진 점

- 탭 줄을 sticky로 하려고 헤더의 `position: sticky`를 뺐다. 헤더는 스크롤하면 올라가고 탭 줄만 남는다.
- 핵심 엔티티 카드의 줄은 링크가 아니다(텍스트만, `종류 · 값`).
- 권고 조치 칩 문구는 `우선순위 높음`처럼 쓴다(`review.test.tsx`가 이 문구를 확인하고 있어 그대로 유지). 디자인의 P0/P1/P2는 D-072와 달라 쓰지 않았다.
- 분석 이력 머리에 `분석 N회 · 검토 N회`만 남겼다. 이전 "생성·마지막 갱신" 표는 지웠다.
- `vite.config.ts`에 `server.fs.allow: [".."]`를 더했다. 샘플 모드가 `tests/fixtures/`의 손으로 만든 JSON을 읽기 때문이다(개발 서버에만 해당).
- 검색 흐림과 강조 흐림이 겹친 노드는 CSS로 더 낮은 쪽(0.2) 하나만 적용한다(곱하지 않음).
- `IncidentGraph`에 prop `start`(JSON 문자열)가 늘었고 열릴 때 한 번만 읽는다. 열려 있는 동안 주소의 `node`가 바뀌어도 따라가지 않는다.
- 선택한 노드가 상위 60 밖이면 선택하는 동안만 그래프에 더한다(`buildGraph`의 `include`). 선택을 풀면 사라진다.

## 다음 사람이 알아야 할 것

- 브라우저로 확인하지 못했다. jsdom은 투명도·sticky·열 너비·hover 감각을 보지 못한다. 전·후 스크린샷은 사람이 붙인다(D-075).
- `PLAIN_LINES_BY_DEFAULT`는 `true`로 두었다(사람이 확인함).
- 터치 화면에는 hover가 없고 선택만 강조한다. 키보드로 노드를 고르면 선택 기준으로 강조된다.
- 우측 패널의 "이 노드의 연결"은 `arrowLinks(detail, key)`로 전체 응답에서 `src`→`dst`를 찾아 8개까지 보인다(더 있어도 나머지는 목록에 없다). 엔티티 노드에서만 나온다.
- Ticket 0건 Incident는 계약(`ticket_ids` 1개 이상)상 서버에 없다. 빈 상태는 샘플 모드와 테스트로만 본다. 샘플 모드 코드(`incident/dev-sample.ts`)는 `import.meta.env.DEV` 분기 안의 동적 import라 `pnpm build` 결과(`dist/`)에 들어가지 않는다(빌드 결과에서 문자열 검색으로 확인함).
- 반려 이력·라운드 변화량 칩·위험 경로는 근거가 되는 데이터가 없어 만들지 않았다(D-076, D-081). 하려면 라운드별 소속 Ticket·엔티티·판정 스냅샷과 반려 이벤트(사유·시각) 저장이 필요하고 L2 담당 승인이 필요하다.
- 항목별 로딩 문구는 만들지 않았다(상세가 한 요청이다).
- 헤더 높이 "약 210px"이 얼마나 줄었는지는 숫자로 재지 못했다.
- 이전 기록 380의 "선택하면 직접 이웃만 남는다"는 이 기록이 대체한다(`supersedes`에는 적지 않았다. 380은 그래프 전체 기록이라 일부만 바뀐다).
- `pnpm lint`의 경고 1건(`flow-chart.tsx`)은 이 이슈 전부터 있다. `vitest run`은 `--maxWorkers=2 --testTimeout=30000`으로 돌렸다(기록 379·380과 같은 이유).

## 디자인과 다른 곳 (PR에 적을 것)

- 분석 이력: 라운드 칩(`Ticket +N`, `엔티티 +N`, `판정 변경 N`)과 반려/승인 이벤트 노드가 없다. 라운드 제목은 "Round N" 뒤에 "재분석 완료" 같은 문구 대신 판정 칩을 둔다.
- 권고 조치 우선순위는 P0/P1/P2 대신 높음·중간·낮음(D-072).
- 그래프 패널의 "위험 경로"·연결 단계 번호·역할 문구("공격 출발지" 등)가 없다. 대신 `src`→`dst` 직접 이웃 목록이다.
- 그래프에서 노드를 고르면 나머지는 숨기지 않고 흐리게 한다.
- 로딩은 페이지 전체 로딩이다(디자인의 "엔티티 100개를 불러오는 중…" 같은 항목별 문구 없음).
- Entity 보기 프레임이 디자인에 없는 점은 기록 380과 같다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과. `uv run pytest`: 2696건 통과(Python은 바꾸지 않음).
- `pnpm contracts:check`(36개 일치), `pnpm lint`(경고 1건은 기존), `pnpm build`: 통과. `pnpm exec vitest run --maxWorkers=2 --testTimeout=30000`: 199건 통과.
- 주요 테스트: `incident-graph.test.tsx`(선택·hover 흐림과 복귀, 선택이 hover에 덮임, 검색 흐림과 겹침, 이웃 목록, `start`), `incident/graph-model.test.ts`(`directNeighbours`·`arrowLinks`·`include`), `incident-page.test.tsx`(타임라인, 2단 개요, 핵심 엔티티 순서, 영향 숨김, Ticket 행, 칩, 그래프로 보기, `node` 주소, 샘플 모드 3건).
- 손으로 확인한 것은 아직 없다.
