---
issue: 376
date: 2026-11-25
owner: Pandyo
supersedes: [365-pen-screens.md]
---

# 화면에 필요한 판정·자산 데이터 응답 추가

## 목표

디자인에는 있으나 데이터가 없어 비워 둔 두 곳을 채운다. 그래프 선택 패널의 Ticket 판정 칩과 Entity 자산 중요도(Incident 상세 응답 확장), Ticket 상세의 "근거 N개"(화면 계산). 값이 없는 기존 건은 지금처럼 비워 둔다.

## 방법

### Incident 상세 응답 확장 (D-078)

`GET /api/incidents/{id}`의 응답 모델 `IncidentDetail`(`ui_models.py`)만 바꾼다. `contracts/`의 JSON Schema, DB 스키마, 마이그레이션은 바꾸지 않는다. 새 필드는 모두 기존 필드를 그대로 두고 더한다.

- `tickets[]`(`IncidentTicket`)에 `decision`을 더한다. 값은 `tickets.verdict`의 `decision`(`benign`·`malicious`·`undetermined`)이고, 판정 전이면 `null`이다. 기존 쿼리가 읽는 `tickets` 행에서 꺼내므로 쿼리를 더하지 않는다.
- `IncidentDetail`에 `entity_criticality`를 더한다. 항목은 `type`·`value`·`criticality`(1~5)이다.
  - 소속 Ticket의 `alert_ids`를 모아 `alerts`에서 `assets`를 한 번의 쿼리로 읽는다(Alert 수에 따라 쿼리가 늘지 않는다).
  - 각 자산의 `entity`(`type`, 정규화한 `value`)를 키로 `criticality`를 모은다. 같은 키가 여러 Alert에 있으면 최댓값을 쓰고 `null`은 무시한다. 값이 `null`뿐인 키는 목록에 넣지 않는다.
  - Alert가 없는 Ticket(Hunt 출신)은 건너뛴다. 읽는 `alerts.assets`는 정규화 시점의 스냅샷이다. 자산이 나중에 등록되면 기존 `reprocess`(D-063)로 갱신하며, 이 이슈는 재처리를 더하지 않는다.
- TypeScript 타입은 `pnpm contracts`로 생성한다(D-003).

### 화면

- 그래프 선택 패널(`incident-graph.tsx`)
  - Ticket 노드: 심각도 칩 줄에 판정 칩을 더한다. `decision` 원문 소문자(`malicious`)를 텍스트로만 표시하고 `null`이면 칩이 없다.
  - Entity 노드: "자산 중요도"에 `entity_criticality`를 `(type, value)`로 찾아 보인다. 문구는 1 매우 낮음 / 2 낮음 / 3 보통 / 4 높음 / 5 매우 높음이고 한 함수(`criticalityLabel`)에 둔다. 값이 없으면 "—"다. 다른 노드 종류는 지금처럼 "—"다.
- Ticket 상세(`detail-sections.tsx`)의 "근거 검토": 머리에 "근거 N개"를 보인다. N은 `verdict.evidence_ids.length`이고 0이면 "근거 0개"다. API는 바꾸지 않는다. 판정이 없는 Ticket은 지금처럼 "아직 판정되지 않았어요."다.
- 밖에서 온 문자열(엔티티 값 등)은 텍스트로만 표시한다(`docs/security.md` "화면").

### 테스트(먼저 쓴다)

- `tests/fixtures/`에 손으로 만든 샘플: Ticket 둘이 같은 엔티티를 서로 다른 `criticality`(예: 3과 5)로 가진 Incident, `criticality`가 `null`인 자산, 판정 전 Ticket, Alert가 없는 Ticket. IP는 문서용 대역을 쓴다.
- API 테스트: 최댓값 선택, `null` 무시, 판정 전 `decision: null`, 자산이 없으면 빈 목록, Alert 수가 늘어도 쿼리 수가 늘지 않음, 기존 필드(`ticket_ids` 등)가 그대로임.
- 프런트 테스트: 판정 칩 표시·미표시, 중요도 문구 5단계와 "—", "근거 N개"와 "근거 0개", 값이 없는 응답에서 깨지지 않음.
- Entity 노드의 `value`가 자산 쪽 정규화 값과 같은 키로 맞는지 샘플로 확인한다. 어긋나면 개발을 멈추고 알린다.

## 바꿀 곳

- `src/soc/api/ui_models.py`: `IncidentTicket.decision`, `IncidentDetail.entity_criticality`와 항목 모델
- `src/soc/api/routes/workflow.py`: `incident()`가 판정과 자산 중요도를 채운다(읽기 쿼리 한 번 추가)
- `frontend/src/api/generated/`: `pnpm contracts`로 생성(손으로 고치지 않는다)
- `frontend/src/incident-graph.tsx`, `frontend/src/detail-sections.tsx`, 해당 스타일(`style.css`)과 테스트
- `tests/`, `tests/fixtures/`: 위 테스트와 샘플
- `docs/decisions.md`: D-078과 기록
- `docs/plans/376-graph-panel-data.md`, `docs/notes/376-graph-panel-data.md`

## 다른 코드와 맞물리는 곳

- 화면용 응답 모델 `IncidentDetail`·`IncidentTicket`에 필드를 더한다. 기존 필드는 바꾸지 않는다. 이 응답을 읽는 곳은 프런트의 Incident 상세·그래프이다. 이 변경은 L1·L3·L2 담당이 승인했다(사용자가 알림).
- Verdict 계약(`contracts/common/verdict.schema.json`), Alert·Ticket 계약, L1 프롬프트와 출력 검증, DB는 바꾸지 않는다.
- 새 환경변수, 새 도구, 새 라이브러리는 없다.
- 원칙 3·4·5와 부딪히지 않는다. 판정과 자산 값은 저장된 값을 읽어 보여 줄 뿐이고, 화면은 텍스트로만 표시한다.

## 범위 밖

- 근거별 강도(강한 근거·보조 근거)와 "N개 신호 일치" 문구. Verdict 계약 변경이 필요해 이번에 하지 않는다. 필요해지면 L1·L3 담당 승인을 받아 새 이슈로 한다.
- 자산 표를 채우는 코드. 지금은 값이 없어 실환경 화면에서는 중요도가 항상 "—"다.
- 기존 건 재처리. 값이 없는 Ticket·Incident는 비워 둔다.
- 그래프의 Entity 모드, Incident 노드의 L2 판정 칩, Alert 노드의 판정 칩.

## 완료 기준

- [ ] 그래프에서 Ticket 노드를 고르면 판정 칩(`decision` 원문)이 보이고, 판정 전이면 칩이 없다
- [ ] 그래프에서 Entity 노드를 고르면 자산 중요도가 1~5의 문구로 보이고, 값이 없으면 "—"다. 같은 엔티티의 값이 여럿이면 최댓값이다
- [ ] Ticket 상세에 "근거 N개"가 보이고 0이면 "근거 0개"다. 판정 없는 기존 건도 깨지지 않는다
- [ ] `IncidentDetail` 응답의 새 필드와 계산 기준(최댓값, `null` 무시, 쿼리 수 고정)을 확인하는 테스트가 있고 `tests/fixtures/`의 샘플을 쓴다
- [ ] `pnpm contracts:check`로 생성 타입이 응답 모델과 맞다. `contracts/`의 JSON Schema는 바뀌지 않았다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`와 `frontend/`의 `pnpm contracts:check`, `pnpm lint`, `pnpm test`, `pnpm build`가 통과한다
- [ ] 디자인과 다른 곳을 PR에 적었다. 전·후 스크린샷은 사람이 붙인다(D-075)

## 토론으로 정한 것

이슈 본문과 달라진 점:

- **계약 변경이 화면용 응답 모델 변경으로 줄었다.** 이슈는 판정 계약(Verdict)을 바꾸고 JSON Schema·생성 코드·검증 함수를 함께 바꾸는 것이었다. 근거별 강도를 이번 범위에서 빼서 Verdict는 그대로이고, 바뀌는 것은 `IncidentDetail` 응답 모델과 그 생성 TypeScript뿐이다. Verdict는 Alert 1차 판정·Ticket·L1 LLM 출력 검증이 함께 쓰는 한 계약이라, 필드 추가는 L1 출력 형식까지 바꿔서 이번에 하지 않는다.
- **근거별 강도는 범위 밖이다.** 질문 1: 강도의 출처로 L1 출력(A), 코드 계산(B), 이번 제외(C)를 놓고 사람이 C를 골랐다. 질문 2(강도 형식 오류 처리)는 해당 없다.
- **"N개 신호 일치"는 "근거 N개"로 바꿨다.** 강도를 빼고 N이 `evidence_ids` 개수라서 "신호 일치"가 아니라 "근거 N개"에 가깝다. N은 화면이 세고 저장하지 않는다. 디자인(.pen)은 "근거 검토 · 3개 신호 일치"와 근거 줄마다 "강한 근거/보조 근거"이다. 이 차이는 PR의 "디자인과 다른 곳"에 적는다.
- **자산 중요도 출처**는 Alert의 `assets[].criticality` 스냅샷이다(Alert JSON을 읽는 B안은 쓰지 않는다). 엔티티 키로 맞추고 여럿이면 최댓값이다. 값 문구는 5단계(매우 낮음~매우 높음)이다. 자산 표를 채우는 코드가 없어 실환경에서는 비어 있다.
- **판정 칩**은 Ticket 노드에만 둔다. 디자인의 칩 줄에 "Alert 1건" 칩이 같이 있어 Ticket 노드 패널로 확인했다.
- **기존 건은 비워 둔다**(재처리 없음).
- **승인 범위.** L1·L3·L2 담당 승인은 받았다. 이 계획의 승인 대상은 `IncidentDetail` 응답 확장뿐이다(사용자가 알림).
- 계획 365(`365-pen-screens.md`)의 "범위 밖"이던 근거 강도·"N개 신호 일치"와 "노드 패널의 자산 중요도는 `assets[].criticality`를 쓰고 값이 없으면 —"를 이 계획이 이어받는다. 365는 고치지 않는다.
- 결정 목록: D-078.

## 바뀐 점
