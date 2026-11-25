---
issue: 376
date: 2026-11-25
owner: Pandyo
plan: 376-graph-panel-data.md
supersedes: []
---

# 그래프 패널의 판정 칩·자산 중요도와 Ticket 상세의 "근거 N개"

## 한 일

- `GET /api/incidents/{id}` 응답에 두 가지를 더했다. `tickets[].decision`(Ticket 판정의 `decision`, 판정 전이면 `null`)과 `entity_criticality`(`type`·`value`·`criticality`)다(D-078). 자산 중요도는 소속 Ticket들의 Alert `assets[].criticality`를 `(type, value)`별로 모은 최댓값이고, `null`뿐인 키는 목록에 없다. 키는 `(type, value)` 순으로 정렬해 돌려준다.
- 그래프 선택 패널(`incident-graph.tsx`): Ticket 노드를 고르면 판정 칩(`decision` 원문)이 보이고 판정 전이면 없다. Entity 노드의 "자산 중요도"는 `type`·`value`가 같은 항목을 찾아 5단계 문구로 보이고, 값이 없으면 칸을 숨긴다(Ticket·Alert·Incident 노드 패널에는 칸이 없다). 문구는 `frontend/src/criticality.ts`의 `criticalityLabel` 한 곳이다.
- Ticket 상세 "근거 검토"에 "근거 N개"를 더했다. N은 `verdict.evidence_ids.length`이고 API는 바뀌지 않는다. 0이면 "근거 0개"다.
- `contracts/`의 JSON Schema와 DB는 바뀌지 않았다. 생성 TypeScript(`IncidentDetail.ts`)만 `pnpm contracts`로 다시 만들었다.

## 계획과 달라진 점

- 사람이 개발 중에 두 가지를 바꿨다(계획 파일 "바뀐 점"에 적음). 자산 중요도는 값이 없으면 "—"가 아니라 칸을 숨기고 Ticket 노드에는 칸이 없다. 그래프의 Entity 보기 버튼은 비활성이고 "준비 중" 라벨·툴팁·`aria-disabled`로 분명히 보인다(Entity 보기는 만들지 않았다). D-078 문구를 같은 ID로 고쳤다.
- 응답 모델에서 `decision`·`entity_criticality`는 필수 필드(null 가능)로 두었다. 응답을 읽는 곳은 프런트의 Incident 상세뿐이고, 목(mock) 응답 두 곳(`App.test.tsx`)에 필드를 더했다.
- 중요도 쿼리는 `ui_read.entity_criticality`에 두고 Alert 행 전체가 아니라 `assets` 열만 읽는다. 쿼리 수는 Ticket·Alert 수와 상관없이 일정하고, 테스트가 이를 지킨다.

## 다음 사람이 알아야 할 것

- **실환경에서는 자산 중요도 칸이 항상 숨겨진다.** 자산 표(`assets`·`asset_identifiers`)를 채우는 코드가 아직 없다(`INSERT INTO assets`는 테스트에만 있다). 값이 보이는 것은 fixture 테스트로만 확인했다.
- 중요도는 정규화 시점의 Alert 스냅샷(`alerts.assets`)이다. 자산이 나중에 등록돼도 Incident 화면은 `reprocess`(D-063)로 Alert를 갱신하기 전까지 바뀌지 않는다.
- 그래프 Entity 노드의 `value`와 자산의 `entity.value`가 같은 정규화 값이라는 가정에 기댄다. 둘 다 `normalize_entity_value`를 거친 값이지만, 키가 어긋나면 중요도가 조용히 "—"가 된다. 실제 ELK 데이터에서 맞는지는 확인하지 못했다.
- Alert가 없는 Ticket(Hunt 출신)은 중요도 계산에서 빠진다.
- 판정 칩은 Ticket 노드에만 있다. Alert 노드의 `triage.verdict`와 Incident 노드의 L2 판정은 보이지 않는다(범위 밖).
- 근거별 강도와 "N개 신호 일치"는 하지 않았다. 필요해지면 Verdict 계약(Alert 1차 판정·Ticket·L1 출력 검증이 같이 쓴다)을 바꿔야 하므로 L1·L3 담당 승인을 받아 새 이슈로 한다.
- 로컬에서 `-m db` 테스트를 돌릴 때 `.env`의 `DATABASE_URL`이 가리키는 `zt_dev`가 없어서, 그 명령에서만 `zt`로 바꾼 값을 환경변수로 줬다(`.env`는 고치지 않았다).

## 디자인과 다른 곳 (PR에 적을 것)

- Ticket 상세 근거 검토 머리: 디자인은 "근거 검토 · 3개 신호 일치"와 근거 줄마다 "강한 근거/보조 근거"이고, 구현은 "근거 N개"와 기존 근거 ID 목록이다.
- 판정 칩은 디자인의 칩 줄(심각도 "High", "malicious", "Alert N건") 중 판정 칩만 만들었다. 심각도·Alert 수 칩은 이 이슈의 범위가 아니다.
- 자산 중요도는 디자인의 "높음"과 같은 문구 체계(매우 낮음~매우 높음)이다. 디자인은 Entity 패널에 항상 이 줄을 두지만, 구현은 값이 있을 때만 보인다(자산 등록이 노드가 뜨는 조건이 아니라 추가 정보라서).
- Ticket/Entity 보기 전환: 디자인은 Entity 보기가 동작하지만 구현은 Entity 버튼을 "준비 중"으로 비활성 표시한다.

## 확인 방법

- 테스트(DB는 `zt`로 바꾼 `DATABASE_URL`): `uv run pytest tests/test_api_detail.py -m db` 13건 통과. 주요 테스트: `test_incident_detail_gives_each_ticket_its_verdict_decision`, `test_entity_criticality_takes_the_highest_value_and_skips_nulls`, `test_entity_criticality_is_empty_without_asset_values`, `test_incident_detail_query_count_does_not_grow_with_tickets`. 샘플은 `tests/fixtures/api/incident_panel.json`.
- 프런트: `criticality.test.ts`, `incident-graph.test.tsx`(판정 칩, 중요도 칸 표시·숨김, Entity 버튼 "준비 중"), `ticket-detail.test.tsx`("근거 N개").
- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- `pnpm contracts:check`, `pnpm lint`(경고 1건은 기존), `pnpm build`: 통과. `pnpm exec vitest run --maxWorkers=2 --testTimeout=30000`: 131건 통과.
- 전체 `uv run pytest`와 `-m db` 결과는 아래 "마무리" 때 채운다.
- 손으로 확인한 것은 아직 없다. 전·후 스크린샷은 사람이 붙인다(D-075).
