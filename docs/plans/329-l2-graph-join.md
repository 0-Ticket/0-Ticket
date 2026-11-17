---
issue: 329
date: 2026-11-18
owner: Juhyeok0603
supersedes: [319-incident-graph.md]
---

# L2 그래프가 수집기 엔티티로 무관한 Ticket을 연결하지 않게 한다

## 목표

L2 분류 그래프가 수집기·목적지 엔티티를 연결 근거로 삼아 무관한 Ticket을 한 Incident에 넣는 일을 막는다. 출발 측 엔티티가 같은 Ticket은 후보로 찾되, Incident 하나의 Ticket 수를 10개로 제한한다. 엔티티 자체는 증거와 Incident 상세에 남긴다.

## 방법

- Alert·Hunt 출발 노드와 상대 노드의 엔티티가 **모두** `role = src`이고 기존 type·정규화 값이 같을 때만 경로를 만든다. `read_graph`의 시드에 역할을 싣고, SQL의 `matches`에서 양쪽 역할을 확인한 뒤 `candidate_incidents`의 `LIMIT`을 적용한다. 직접 호출되는 `classify_graph`도 같은 규칙을 따른다. 같은 type·값이 여러 역할로 존재할 때 `dst`가 `src`를 덮지 않도록 역할을 필터링한 뒤 경로 키를 만든다. Event는 기존처럼 경로에 쓰지 않는다.
- `src` 공개 IP도 연결 경로로 허용하고 `graph.py`의 공개 IP 무조건 제외 처리를 없앤다. `public_ip_only` 사유는 새 분류에서 만들지 않는다. 저장된 과거 Ticket을 읽는 화면의 해당 사유 표시와 테스트는 남긴다.
- `[l2.branch] max_incident_tickets = 10`을 추가하고 양의 정수로 검증한다. 그래프 SQL의 `peers` 두 분기에서 `cardinality(i.ticket_ids) < %s`를 확인해 가득 찬 Incident가 후보 수 한도를 차지하지 않게 한다. `save_branch`는 Incident를 잠근 뒤 상태와 Ticket 수를 다시 확인한다. 상한에 닿았으면 `decision_fallback = incident_full`을 남기고 새 Incident를 만든다. `candidate_window_ms`의 `updated_at` 기준과 `max_candidates = 5`는 유지한다.
- L3 Hunt에도 양쪽 `src` 규칙을 그대로 적용한다. 별도 역할 예외는 두지 않는다.
- `src/soc/normalize/mapping.py`의 `ENTITY_FIELDS`는 바꾸지 않는다. #326부터 새 Alert는 `host.name`을 엔티티로 올리지 않지만 기존 Alert와 Event의 host 값은 남아 있다. 그래프에서 제외한 엔티티도 Alert·Ticket·Incident의 증거와 상세 응답에서 지우지 않는다.
- 기존 Ticket·Incident 관계와 저장된 그래프 경로는 재분류하거나 수정하지 않는다. 기존 23 Ticket `held` Incident는 1시간 쿨다운 뒤 분석과 실패를 반복할 수 있음을 개발 기록에 적는다. 현 화면·API에는 `held`를 `human_handling`으로 바꾸는 기능이 없으므로, 중단이 필요하면 DB 운영자가 별도로 수동 상태 변경을 검토한다. 이번 작업은 기존 데이터 상태를 변경하지 않는다.

## 바꿀 곳

- `src/soc/l2/branch/graph.py`: 역할을 SQL 조회와 경로 판정에 적용하고 공개 IP 제외를 없애며 가득 찬 Incident를 후보 조회에서 제외한다.
- `src/soc/l2/branch/store.py`: 잠근 Incident의 Ticket 수를 재확인하고 가득 찼으면 새 Incident로 저장한다.
- `src/soc/l2/config.py`, `config/default.toml`: Ticket 수 상한 설정과 검증을 더한다.
- `tests/fixtures/l2/`, `tests/test_l2_graph.py`, `tests/test_l2_branch_db.py`, `tests/test_l2_config.py` 및 설정을 직접 만드는 테스트: 손 작성 샘플과 역할·공개 IP·상한·L3 경로의 기대를 새 규칙에 맞춘다.
- `docs/decisions.md`: D-027의 연결 기준과 성장 상한을 갱신한다.
- `docs/notes/329-l2-graph-join.md`: 개발 결과와 기존 23 Ticket Incident의 재시도 순환, 별도 DB 운영 조치 필요성을 기록한다.

## 다른 코드와 맞물리는 곳

- `read_graph`의 후보 조회와 `classify_graph`의 직접 판정에 같은 역할 규칙을 적용한다. `max_candidates`보다 앞에서 필터링해야 `candidate_limit`이 잘못 기록되지 않는다.
- `BranchSettings` 생성·검증과 이를 직접 만드는 테스트에 `max_incident_tickets`를 반영한다. 저장 직전 재검사는 동시 변경에도 상한을 지킨다.
- `details.l2_branch`의 새 실패 사유 `incident_full`은 기존 `decision_fallback` 필드에 넣는다. 과거 `public_ip_only` 기록을 읽는 Incident 상세 API·화면은 유지한다.
- Incident의 `entities`는 기존 병합 방식으로 보존한다. 화면의 Incident JSON 상세에서도 host 값을 계속 읽을 수 있어야 한다. 그래프 관계도에는 앞으로 연결 근거가 된 `src` 경로만 추가된다.
- L2 분석의 실패 쿨다운(D-028)은 바꾸지 않는다. Ticket 상한 10은 입력 크기의 상한이지 모든 `budget_exceeded`를 없앤다는 보장은 아니다.

## 범위 밖

- 자산 인벤토리 채우기와 자산 역할 연결 예외, `ENTITY_FIELDS` 변경, 기존 Incident 분리·재분류·상태 변경.
- Alert 시각 기반 창, Incident 종료·에이징 정책, CIDR 묶기, `max_candidates` 변경.
- 분석가용 Incident 상태 변경 API·화면, 기존 L2 분석 실패 쿨다운 변경.

## 완료 기준

- [ ] 손 작성 fixture에서 양쪽 `src` 엔티티가 같은 Alert는 기존 Incident 후보가 되고, 수집기 host만 같거나 domain·`dst`·역할 없는 값만 같은 Alert는 후보가 되지 않는다. 한쪽만 `src`인 경우도 연결되지 않는다.
- [ ] `src` 공개 IP가 같은 Alert는 연결 경로를 만들고 새 분류는 `public_ip_only`를 만들지 않는다. 과거 `public_ip_only` 기록의 화면 문구는 계속 표시된다.
- [ ] L3 Hunt의 `src` 엔티티에서 Alert로 가는 경로가 동작하고, `src`가 아닌 Hunt 엔티티는 연결하지 않는다.
- [ ] 가득 찬 Incident가 후보 조회 한도를 차지하지 않으며, 저장 직전 10개에 도달한 Incident를 선택해도 `incident_full` 사유와 함께 새 Incident가 만들어진다. 샘플에서 한 Incident의 Ticket 수가 10개를 넘지 않는다.
- [ ] `host` 등 제외한 엔티티가 증거와 Incident 상세 API·화면의 Incident 데이터에는 남는다.
- [ ] 설정 검증, 기존 그래프·분류·DB 테스트, `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과한다. 화면을 바꾸면 화면 검사도 통과한다.
- [ ] 기존 데이터는 바꾸지 않고 23 Ticket `held` Incident의 반복 실패 가능성과 DB 운영자 수동 조치 경로를 `docs/notes/`에 기록한다.

## 토론으로 정한 것

1. 공개 IP를 포함한 `src` 엔티티를 연결 근거로 쓴다. 이 환경에서 자산 인벤토리가 비어 있고 대부분의 엔티티가 상대 측 또는 수집기 값이므로, `src` 공개 IP가 실제로 남는 조인 키다(D-027).
2. Incident당 Ticket 상한을 10개로 둔다. `updated_at` 창은 건수 상한이 아니며 23 Ticket Incident의 분석 입력이 `budget_exceeded`를 일으켰다. 상한값 10에서도 분석 성공을 보장하지는 않는다.
3. L3 Hunt도 역할 예외 없이 양쪽 `src` 조건을 따른다. Hunt의 `src` 경로는 남고 `dst`·`target` 경로는 제외된다.
4. 기존 관계와 그래프 기록을 유지한다(D-027). 23 Ticket `held` Incident의 자동 재시도는 이번 변경으로 멈추지 않으므로 운영 메모에 남긴다. 현 API는 상태를 바꾸지 않아 중단은 DB 운영자의 별도 수동 조치가 필요하다.
5. 새 Alert의 센서 `host.name` 제외는 #326에서 이미 반영됐다. Event와 과거 Alert의 값은 남으므로 그래프 역할 필터가 필요하다.

## 바뀐 점
