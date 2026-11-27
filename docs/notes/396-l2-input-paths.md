---
issue: 396
date: 2026-11-27
owner: Pandyo
plan: 396-l2-input-paths.md
supersedes: []
---

# L2 조사 입력에서 경로 중복과 실행 기록을 빼 서버 최대 구조가 한도 안에 든다

## 한 일

L2 조사 입력(`AnalyzeContext.investigate_data()`)만 바꿨다. Ticket과 Incident의 `details`를 통째로 빼고(`coverage`·`reason`·`paths`는 빼기 전에 `ticket_graph`가 읽는다), `graph.tickets[].paths`를 엔티티 → 상대 Ticket → 상대 ID 연결(`links`)로 요약한다. 상대 Ticket의 Incident는 `graph.peer_tickets`에 한 번만 있다. 한 연결의 상대 ID는 `MAX_PEER_IDS`(5)개까지 싣고 더 있으면 `omitted`에 생략 건수를 적는다. 출발이나 상대가 Hunt인 경로도 같은 모양이다(ID 접두사 `alt_`/`hnt_`로 구분되어 `kind`는 두지 않았다). DB 저장값과 화면용 API는 바뀌지 않았다. `l2_investigate.md`는 9행만 고쳤다.

## 계획과 달라진 점

- 계획 파일 "바뀐 점"대로 완료 기준을 서버에서 가장 큰 구조(경로 131, 엔티티 1, (출발 Ticket, 엔티티) 10, 상대 Ticket 21, 상대 Alert 21, Ticket 10개, 실패 기록 110건, Alert·Event 포함)가 한도 안에 드는 것으로 바꿨고, 최악 입력 테스트는 "한도를 넘는 것이 알려진 입력"의 측정 기록으로 바꿨다.
- `details`를 빼는 곳을 `read_context`가 아니라 `investigate_data()`로 했다(`AnalyzeContext.incident`·`tickets`는 그대로 전체를 들고 있고 입력으로 내보낼 때만 뺀다). `coverage`·`reason`·`paths`는 `read_context`가 `ticket_graph`로 먼저 읽는다.
- `AnalyzeContext`에 필드 `peer_tickets`(기본 빈 사전)를 더했다. 이 클래스를 만드는 곳은 `read_context`뿐이다.
- 합성 입력의 Event 몫은 서버에서 재지 못해 Alert와 같은 13,000자로 잡았다.

## 다음 사람이 알아야 할 것

- **한도를 넘는 것이 알려진 입력.** 연결 수 상한과 `max_input_chars`는 바꾸지 않았다.
  - 최악(Ticket 10개 × 경로 50개, 엔티티·상대 Ticket·상대 Alert가 경로마다 다름): 합계 **182,600자**(`graph` 136,631자). 경로 하나가 약 273자라 상한 N이 줄일 것이 없다.
  - 서버와 같은 구조(엔티티 1, 상대 Ticket마다 Alert 1개, 상대 수는 경로 수에 21/131로 비례)에서 경로가 늘 때: 131개 53,456 / 200개 60,954 / 250개 66,390 / 300개 71,826 / 500개 93,570. **228개부터 한도를 넘는다.** 서버 최대 131개의 여유는 10,544자다.
  - 이 합성에서 Ticket 10개의 Alert·Event 몫은 각 13,000자로 잡았다. 실제는 Incident마다 다르다.
- **상한 N=5.** 서버 구조는 상대 Ticket마다 상대 Alert가 하나라 `omitted`가 생기지 않는다(N과 무관). 상대 Ticket 3개에 상대 Alert가 몰린 입력(Ticket 10개 × 경로 50개)에서 `graph`는 N=1 6,360 / 3 9,000 / 5 11,640 / 10 18,210 / 20 이상 25,470자다. 5로 두면 몰린 경우 절반 아래로 줄고, 생략한 ID는 도구로 찾는다고 프롬프트에 적었다.
- **입력에서 알 수 없는 것.**
  - 저장 경로가 Ticket당 50개에서 잘렸는지(`coverage`는 그대로 complete).
  - 상한은 그래프만 제한한다. Alert·Event·Hunt·`previous_artifact`가 커서 넘는 경우는 그대로다.
  - 상대 Ticket이 서로 다른 Incident로 저장된 경로가 있으면 `peer_tickets`는 먼저 본 Incident를 쓴다. 저장 시점의 스냅샷이라 정상 동작에서는 생기지 않는다고 봤다.
- **#382(#398) 병합의 영향(2026-11-27 병합 뒤 다시 확인).**
  - 조사 입력: 발급 근거 Event(class 0)가 L1·L3 Ticket의 근거로 `data.events`에 들어올 수 있다. 원문은 입력에 없고 포인터(`ocsf`)와 엔티티만 있어 한 건이 약 660자(직렬화하면 약 770자)다(엔티티 5개인 합성 문서). 한 Incident에 들어오는 건수에는 상한이 없다(판정의 `evidence_ids`에 개수 제한이 없다). 서버 최대 구조에서 합성 Event 몫 13,000자에 더하면 **13건까지** 한도 안이고 14건째에 넘는다. 합성 Event 몫을 빼고 class 0 Event만 있다면 **30건까지**다(`test_issued_class_zero_events_are_small_and_their_capacity_is_recorded`). 실제 건수는 서버에서 확인하지 못했다.
  - 보고 입력: 이 이슈는 바꾸지 않았다(`incident`는 `id`·`summary`만). #382가 `evidence`(발췌, 최대 24,000자이고 `fit_to_budget`이 남은 예산 − 8,000자 안으로 맞춘다)와 `dropped_refs`를 더했다. 발췌 없이도 넘는 입력은 #382 기록대로 별도 이슈다.
  - 프롬프트: 9행은 이 이슈의 문장, 11~12행은 #382의 줄이고 둘 다 남아 있다. 병합 충돌은 없었다.
- 실패 기록(`details.l2_analyze.failures`)은 DB에서 계속 쌓인다. 입력에서만 빠졌다. 서버에서 길이를 건수로 확인해 두는 편이 좋다.
- 프롬프트가 바뀌어 `prompt.version`(해시)이 바뀐다.
- `feat/382-siem-direct-evidence`가 `l2_investigate.md` 10행 뒤에 2줄을 추가한다. 이번에 9행만 고쳐 병합 때 바로 옆 hunk가 닿을 수 있다.
- 서버에서 `held` Incident가 쿨다운 뒤 분석되는지는 사람이 확인한다(테스트로 닫지 않음).

## 확인 방법

변경 전후 키별 글자 수. 서버에서 가장 큰 구조를 본뜬 합성 입력이고(`tests/test_l2_input_graph.py`, 샘플 `tests/fixtures/l2/path_summary.json`), 변경 전 모양은 같은 합성 경로로 손으로 만들어 쟀다. 단위는 글자 수다.

| 키 | 변경 전 | 변경 후 |
|---|---|---|
| `incident` | 11,718 (실패 기록 110건 11,161) | 544 |
| `tickets` | 174,306 (`l2_branch.paths` 151,436, `candidates` 7,450, `snapshot` 7,450, `progress` 3,200) | 3,300 |
| `graph` | 152,639 (경로 그대로) | 15,779 (`links` 12,710, `peer_tickets` 1,848) |
| `alerts` | 13,063 | 13,063 |
| `events` | 13,063 | 13,063 |
| 합계(지시문 포함) | 408,070 | **53,456** (한도 64,000) |

- 수치는 #382(#398)를 병합한 코드로 다시 쟀다. #382가 지시문(조사 지시문과 출력 계약 `siem_refs`)을 1,312자 늘려 합계가 1,312자 늘었다(52,144 → 53,456).
- 변경 전 `l2_branch.paths` 합이 서버 최대 151,436자와 같고, 합계도 서버 최대 393,253자와 가깝다. 경로 중복(`tickets`와 `graph`에 두 번)이 주원인이라는 분석이 맞다.
- 새 테스트(`tests/test_l2_input_graph.py`): `test_links_group_by_entity_with_alert_and_hunt_ids`, `test_truncated_paths_do_not_invent_connections`, `test_peer_ids_over_the_limit_are_counted_not_listed`, `test_ticket_graph_keeps_coverage_and_reason_and_marks_legacy`, `test_investigate_input_has_no_details_and_no_raw_paths`, `test_largest_server_structure_fits_the_l2_input_limit`, `test_inputs_known_to_exceed_the_limit_are_recorded`.
- 고친 DB 테스트: `test_analyze_context_uses_saved_graph_and_does_not_collect_related_records`(새 모양, 저장된 Ticket 불변 확인).
- 명령(로컬, `DATABASE_URL`은 `zt`로 바꾼 값, `QDRANT_URL=http://127.0.0.1:6333`): `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`(2787건 통과), `uv run pytest -m db`(790건 통과). 경로 중복은 `docs/notes`의 위 표처럼 합성 입력으로만 확인했고 서버 실제 입력은 아직 확인하지 못했다.
