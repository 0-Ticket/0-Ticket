---
issue: 396
date: 2026-11-27
owner: Pandyo
supersedes: []
---

# L2 분석 입력의 그래프 경로 중복을 없애 한도 초과 해결

## 목표

L2 조사 입력(`AnalyzeContext.investigate_data()`)에서 같은 경로가 두 번 들어가는 것과 실행 기록(`details`)을 없애고, 그래프는 연결 요약으로 바꾼다. 서버에서 `budget_exceeded`(`sent=false`)로 반복 실패하던 Incident가 `max_input_chars`(64,000자) 안에서 분석된다. 저장된 값과 화면 응답은 바뀌지 않는다.

## 방법

모델 입력만 `src/soc/l2/analyze/context.py`에서 바꾼다.

1. **빼기 전에 읽기.** `read_context`가 Ticket의 `details.l2_branch`에서 `coverage`·`reason`·`paths`를 먼저 읽는다. 그다음 입력의 `tickets[]`와 `incident`에서 `details`를 통째로 뺀다(두 계약 모두 "계약에 없는 값. 다른 단계는 읽지 않는다"). 조사 입력에만 적용한다. 보고 입력(`make_report_task`)은 이미 Incident의 `id`·`summary`만 받아 바꿀 것이 없다.
2. **경로 요약(B안).** `graph.tickets[].paths`를 `links`로 바꾸고, 상대 Ticket의 Incident는 `graph.peer_tickets`에 한 번만 둔다.

   ```json
   "graph": {
     "peer_tickets": {"tkt_…01": "inc_…aa"},
     "tickets": [{
       "ticket_id": "tkt_…02", "coverage": "complete", "reason": "paths_found",
       "links": [{"entity": "ip:203.0.113.1", "from": ["alt_…02"],
                  "to": {"tkt_…01": ["alt_…10", "alt_…11"]},
                  "omitted": {"tkt_…01": 3}}]
     }]
   }
   ```

   - 요약은 저장된 `paths`에서만 만든다. 항목은 엔티티(`type:값`)마다 하나고, `from`은 출발 노드(Alert 또는 Hunt) ID, `to`는 상대 Ticket ID별 상대 노드(Alert 또는 Hunt) ID 목록이다.
   - 출발이나 상대가 Hunt인 경로도 같은 형식이다. Alert와 Hunt는 ID 접두사로 구분되는지 개발 때 확인하고, 구분되지 않으면 항목에 `kind`를 덧붙인다.
   - 같은 `(출발, 엔티티, 상대 Ticket)`은 한 번만 쓴다. `coverage`·`reason`은 그대로 둔다.
   - 경로가 없거나 `l2_branch`가 없는 Ticket은 지금처럼 `coverage: legacy`와 빈 `links`다.
3. **상한(A-1).** 한 항목의 `to[상대 Ticket]` 안에서 상대 ID를 N개까지만 싣고, 더 있으면 `omitted[상대 Ticket]`에 생략 건수를 적는다(0이면 키를 두지 않는다).
   - 연결 관계(어떤 엔티티가 어느 상대 Ticket과 이어지는지)는 하나도 빠지지 않는다. `from`과 `peer_tickets`도 줄이지 않는다.
   - `data.alerts`·`events`·`hunts`는 줄이지 않는다.
   - N은 측정해서 정하고 개발 기록에 값과 근거를 적는다.
4. **프롬프트.** `src/soc/l2/prompts/l2_investigate.md`의 9행만 고친다. 10행은 그대로 둔다(#382가 바로 뒤에 줄을 추가한다). 9행에 아래를 담는다.
   - `links`의 읽는 법(엔티티, `from`, `to`의 키가 상대 Ticket ID, `peer_tickets`).
   - `from`과 `to`의 ID는 Alert 또는 Hunt이고 근거 ID가 아니라 연결 단서다. 근거로 인용하려면 도구로 확인한 기록 ID만 쓴다.
   - `omitted`가 있으면 그만큼 생략된 것이다. 생략된 것은 읽기 전용 조회 도구로 확인할 수 있고, 확인하지 않은 연결은 추측하지 않는다.
   - `links`가 비었거나 `coverage`가 complete가 아니면 그 범위 밖의 연결을 확인하지 못한 것이다(기존 문장 유지).
5. **테스트.** 손으로 만든 작은 샘플에서 합성 입력을 만든다(IP는 `203.0.113.0/24`, 도메인 `example.com`). 합성 규모는 코드로 늘린다. 키별 글자 수를 재는 도우미를 테스트에 둔다.

## 바꿀 곳

- `src/soc/l2/analyze/context.py`: `read_context`(읽은 뒤 `details` 제거, `links`·`peer_tickets` 구성)와 `investigate_data`(`graph.peer_tickets` 추가), 요약 함수.
- `src/soc/l2/prompts/l2_investigate.md`: 9행.
- `tests/test_l2_branch_db.py`: 기존 `test_analyze_context_uses_saved_graph_and_does_not_collect_related_records`(1150행 근처, 지금은 `graph.tickets == [{ticket_id, **graph}]`를 단언)를 새 모양으로 고친다.
- 새 테스트 파일(DB 없이 도는 순수 함수 테스트), `tests/fixtures/l2/`에 손으로 만든 작은 샘플.
- `docs/notes/396-l2-input-paths.md`: 개발 기록(`/soc-done`).

## 다른 코드와 맞물리는 곳

- 모델 입력의 모양 `data.graph.tickets[].paths`가 `links`로 바뀌고 `data.graph.peer_tickets`가 생긴다. 이 입력을 읽는 곳은 L2 조사 프롬프트뿐이다. 조사 출력 계약(`incident_findings`)과 DB 저장값은 바뀌지 않는다.
- 화면용 API(`src/soc/api/routes/workflow.py`의 `ticket_graphs`)는 DB에서 따로 읽으므로 영향이 없다.
- `l2_investigate.md`의 내용이 바뀌므로 프롬프트 해시(`prompt.version`)가 바뀐다.
- `feat/382-siem-direct-evidence`와 겹치는 파일: `l2_investigate.md`(9행 수정 대 10행 뒤 추가, 바로 옆 hunk라 병합 때 충돌할 수 있다)와 `tests/test_l2_branch_db.py`(약 47줄 거리). `tasks.py`·`worker.py`·`store.py`·`l2_report.md`·`tests/test_l2_worker.py`는 고치지 않는다.
- 새 환경변수, 설정 키, 결정 번호는 없다.

## 범위 밖

- DB 저장값과 화면 응답. 실패 기록(`details.l2_analyze.failures`)이 DB에서 계속 쌓이는 것도 이번에 고치지 않는다.
- `max_input_chars` 값 변경.
- 상한은 그래프만 제한한다. Alert·Event·Hunt·`previous_artifact`가 커서 한도를 넘는 경우는 이번에 해결하지 않고 한계로 기록한다.
- 저장 경로가 Ticket당 50개에서 잘렸는지는 입력에서 알 수 없다(`coverage`는 그대로 complete). 그 한계도 기록만 한다.
- 새 결정(D-xxx), 새 계약, 마이그레이션.

## 완료 기준

- [ ] 조사 입력의 `tickets[]`와 `incident`에 `details`가 없다.
- [ ] 경로 정보가 `graph`에만 한 번 들어가고, 입력에 `paths`·`nodes`·`edges`가 없다.
- [ ] 요약한 `links`에서 연결 엔티티와 상대 Ticket·Alert를 알 수 있다. `coverage`·`reason`은 유지된다. `details`를 빼기 전에 읽는다.
- [ ] 출발이나 상대가 Hunt인 경로도 `links`에 같은 형식으로 나타나고 테스트한다.
- [ ] 저장 경로가 Ticket당 50개에서 잘린 입력에서도 요약이 저장된 경로에 없는 엔티티·상대 Ticket·Incident 연결을 만들지 않는다는 테스트가 있다. 한 항목 안에서 `from × to`로 읽히는 쌍은 같은 엔티티를 공유한다는 것도 단언한다.
- [ ] 상대 ID가 N개를 넘는 연결에서 `omitted`에 생략 건수가 있고, 생략돼도 연결(엔티티 → 상대 Ticket)과 `from`은 빠지지 않는다.
- [ ] `l2_investigate.md` 9행에 `links` 읽는 법, 연결 단서, 생략 건수와 도구 확인 안내가 있고 10행은 그대로다.
- [ ] 키별 글자 수 측정 테스트가 있고 변경 전후를 개발 기록에 건수로 남긴다. 측정은 다음을 구분해 적는다.
  - 변경 전 모양은 같은 합성 경로로 손으로 만들어 잰다.
  - 실패 기록(100건 이상 누적한 Incident)의 글자 수는 따로 잰다. 서버 측정의 "나머지 약 26,000자"에 이번에 빠지는 실패 기록이 섞여 있을 수 있으므로 같은 덩어리로 적지 않는다.
  - 합성 입력은 기본 규모(Ticket 10개 × 경로 13개)와 최악(Ticket 10개 × 경로 50개, 상대 ID와 연결이 서로 다름)이다.
- [ ] 최악 입력에 Alert·Event 등을 더한 합계가 한도(64,000자)에 든다. 더하는 값은 서버 수치에서 구한 상한 약 26,000자다. 들지 않으면 구현을 넓히지 말고 수치를 보고하고 멈춘다. 이 상한은 그래프만 제한한다.
- [ ] 저장된 Ticket·Incident와 화면용 API 응답(`ticket_graphs`)이 바뀌지 않는다는 기존 테스트가 통과한다.
- [ ] 사람이 확인: 서버에서 `held` Incident가 재시도 뒤 분석된다. 쿨다운이 지나야 하므로 테스트로 닫지 않는다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과하고, `-m db` 테스트는 `test_l2_branch_db.py`로 확인한다.

## 토론으로 정한 것

- **요약 형식은 B안**(엔티티 → 상대 Ticket → 상대 ID, Incident는 `peer_tickets`에 한 번). A안(엔티티·상대 Ticket·Incident별 항목)은 같은 규모(Ticket 10개 × 경로 13개)에서 B안의 약 1.6배(46,733자 대 29,281자, 합성 합계)다. 단, 합성 값은 상대 Alert가 모두 다르게 잡은 입력이고 Alert·Event 등은 뺀 수치다.
  - 조건: Hunt 경로를 형식과 프롬프트와 테스트에 포함한다. 50개 잘림에서 없는 연결을 만들지 않는다는 테스트를 둔다.
- **이슈 본문과 달라진 점:** 완료 기준의 "Ticket 10개, 경로 50개가 한도 안에 든다"는 B안만으로 못 맞춘다. 합성에서 `graph`만 49,313자이고 Alert·Event 등을 더하면 약 88,000자로 추정된다. 그래서 상한 A-1(출발 Ticket의 엔티티 → 상대 Ticket 연결마다 상대 ID를 N개까지, 생략 건수 기록)을 더했다. 연결 관계는 줄이지 않고 `data.alerts`도 줄이지 않는다. 더한 뒤에도 한도를 넘으면 구현을 넓히지 않고 수치를 보고하고 멈춘다.
- **`details`는 통째로 뺀다**(이름 지정 제외가 아님). 두 계약이 "다른 단계는 읽지 않는다"로 정했고, 새 키가 생겨도 입력이 커지지 않는다. `coverage`·`reason`·`paths`는 빼기 전에 읽는다.
- **보고 입력은 바꾸지 않는다.** 이슈 본문의 "조사·보고 입력의 Incident"에서 보고 입력은 이미 `id`·`summary`만 받는다.
- **새 D-xxx는 만들지 않는다.** 모델 입력 모양만 바뀌고 팀 결정이 걸린 계약·저장은 건드리지 않는다. main에는 D-084까지 있고 #382 브랜치에 D-083이 두 줄 있어 번호가 겹칠 수 있으므로 피한다.
- 원인 분석은 합성으로 확인했다. Ticket 10개 × 경로 13개에서 `graph`가 151,483자(서버 최대 151,436자와 거의 같다), 합계가 366,928자(서버 최대 393,253자)다. 차이 약 26,000자는 Alert·Event 등과 이번에 빠질 실패 기록의 합으로 보이며 둘의 비율은 모른다.

## 바뀐 점

- 2026-11-27: 최악 입력(Ticket 10개 × 경로 50개, 엔티티·상대 Ticket·Alert가 모두 다름)이 상한 A-1로도 한도를 넘는 것(합성 181,288자)이 확인돼 멈췄고, 사람이 다음과 같이 정했다. 서버 Incident 14개의 경로 구조(가장 큰 것: 경로 131, 엔티티 1, (출발 Ticket, 엔티티) 10, 상대 Ticket 21, 상대 Alert 21)를 확인했다.
  - 완료 기준 "Ticket 10개 × 경로 50개가 한도 안에 든다"를 "서버에서 가장 큰 구조(위, Ticket 10개, 실패 기록 110건, Alert·Event 포함)가 `[agent.l2] max_input_chars` 안에 든다"로 바꾼다.
  - 변경 전후 키별 글자 수는 그 구조를 본뜬 테스트로 잰다. Alert ocsf는 Incident당 약 13,000자까지다.
  - 실패하는 최악 테스트는 지우지 않고 "한도를 넘는 것이 알려진 입력"의 측정 기록으로 바꾼다. 최악값과, 서버와 같은 구조에서 경로 몇 개부터 한도를 넘는지를 개발 기록에 적는다.
  - 연결 수 상한과 `max_input_chars`는 바꾸지 않는다.
