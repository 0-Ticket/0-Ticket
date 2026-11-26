---
issue: 382
date: 2026-11-26
owner: Juhyeok0603
plan: 382-siem-direct-evidence.md
supersedes: []
---

# 이벤트 정규화를 없애고 심에서 찾은 문서를 근거로 발급한다 (진행 중)

## 한 일

이벤트 OCSF 정규화를 파이프라인에서 걷어냈다. `soc.normalize.mapping.normalize()`는 이제
`kind != "alert"`인 원본을 `validation_failed`로 거부하고, 이벤트 매핑표(클래스 표 7개·소스 표 2개)와
`event_tables.py`, 관련 테스트 862줄이 사라졌다. 알럿 정규화와 `mask_headers`·`common.yaml`·
`ecs_fields.yaml`은 그대로다.

근거 발급의 앞 절반을 만들었다. `query_siem`이 모델에게 보인 히트마다 `siem_ref → (_index, _id)`를
도구 세션(`ToolSession.siem_refs`)이 들고, 모델이 출력에 적은 `siem_ref`를 그 키 집합과 대조해
없는 값을 인용하면 run을 멈춘다. 통과한 것은 `AgentResult.cited_siem_refs`로 워커에게 간다.
워커가 쓸 원문 가져오기(`siem.fetch_document`, `GET /<index>/_doc/<id>`)도 만들었다.

**아직 발급은 하지 않는다.** 저장 경로와 `get_raw`가 없다(아래 "다음 사람이 알아야 할 것").

## 계획과 달라진 점

1. **L1 판정 모델의 출력 계약을 `l1_verdict`로 새로 뒀다.** 계획은 "L1 판정 출력 계약에 `siem_refs`를
   더한다"고 했는데, 그 계약이 `common/verdict.schema.json`이고 **저장하는 Verdict와 같은 파일**이었다.
   거기 더하면 `tickets.verdict`와 `alerts.details.triage`에도 `siem_refs`가 들어간다. 발급이 끝나면
   근거는 `evt_…`가 되므로 저장된 `siem_refs`는 되돌릴 수 없는 포인터가 된다. 그래서
   `contracts/l1_verdict.schema.json`을 새로 만들어 출력에만 쓰고 저장 Verdict는 손대지 않았다.
   계약 샘플 2종(`valid`·`invalid`)과 `tests/contract_samples.py`의 목록에 더했다.
   → L1을 배선할 때 **출력에서 `siem_refs`를 떼고 저장해야 한다.**
2. **`siem_ref` 위반에 새 실패 코드를 만들지 않고 `evidence_id_error`를 썼다.** 성질이 같고(근거 인용
   위반), 새 코드를 넣으면 보류·재시도 로직 전부에 손이 간다.
3. **`event_row`를 `src/soc/normalize/mapping.py`에 되돌렸다.** 이벤트 정규화 제거 때 함께 지워졌는데,
   매핑표에 기대지 않는 순수 `events` 행 생성기이고 `dev_l1.py`·`hunt/dev_seed.py`와 앞으로의 발급
   경로가 쓴다. `derive_event_columns`·`seed_event_ocsf`가 같은 파일에 남아 있어 그 옆에 뒀다.
4. **`fetch_document`는 `{_index, _id, _source}` 세 칸만 돌려준다.** ELK의 `GET _doc` 응답에는
   `_version`·`found`가 더 있는데, 수집이 `raw_records.original_text`에 넣는 모양(검색 hit의 세 칸)과
   같게 맞췄다. `soc.ingest.quarantine.serialize_original`을 그대로 쓸 수 있고, `get_raw`·`raw_detail`이
   출처(수집/발급)에 관계없이 같은 모양을 보게 된다. `_source`는 자르지 않는다.
5. **`fetch_document`는 구체 인덱스만 받는다.** `siem.py`의 `_INDEX` 정규식은 쉼표·와일드카드를
   허용하지만 `_doc` 경로에는 쓸 수 없어 따로 막았다. 맵의 값은 늘 히트 하나의 `_index`라 문제없다.
6. **`common/types.schema.json`에 `siem_ref` 정의를 올렸다.** `raw_record.schema.json`에만 있던 서술을
   공용으로 옮기고 그쪽은 `$ref`로 바꿨다(서술 한 곳).

## 다음 사람이 알아야 할 것

### 아직 안 한 것 (계획의 절 번호)

- **§1 심 조회 대상 추가.** `siem.py`의 `TARGET_NAMES`·`TARGET_FILTERS`·`TARGET_FIELDS`와
  `config/default.toml`의 `[[tools.siem.targets]]`. 소스 구분 없이 ECS 공통 필드만.
- **§4 발급 워커.** `raw_records` → `normalize_status(succeeded, result_kind='event', result_id)` →
  `events`(class 0)를 한 트랜잭션으로. `normalize_status`를 빼면
  `src/soc/normalize/store.py`가 그 원본을 집어가 **같은 원본으로 Event를 또 만든다.**
  `events.message`는 `event.dataset`, `details.entities`는 `common.yaml`의 ECS 공통 엔티티 규칙으로
  채운다. 발급분의 `siem_profile`은 `[tools.siem] evidence_siem_profile`.
  실패는 그 근거만 버리고 진행하고 버린 건수만 다음 태스크 입력에 넣는다.
- **§5 `get_raw` 도구.** `evt_`·`alt_`·`raw_id`로 `raw_records.original_text`를 돌려준다.
  D-059 마스킹은 적용하지 않고 `screen_input`은 적용된다.
- **§6 태스크별 허용 목록.** 아래 "함정" 참고.
- **§8 프롬프트** 3개, `config/default.toml`의 `[[ingest.sources]]` 이벤트 대상 5개 삭제,
  `docs/architecture.md` 원칙 1·3과 "큰 흐름", `docs/security.md` "에이전트 도구의 한계",
  `docs/decisions.md`의 D-067·D-069 폐기와 D-007·D-062·D-068·D-073 수정,
  L1·L2·L3 배선(`judge.py`, `l2/analyze/*`, `l3/hunt/verify.py`), `incident_findings`에 `siem_refs`.

### 함정

- **§6의 task 키.** `ToolRegistry.session(stage=...)`가 `tools.allowed[stage]`를 본다. 태스크별로
  바꾸면 `max_tool_result_chars`·`strict_mode`는 여전히 `stage`에서 읽어야 해서 둘을 같이 받아야 한다.
  그리고 **코드에 실제로 있는 task 문자열은 5개**다 — `l1_alert_triage`, `l2_classify`,
  `l2_investigate`, `l2_report`, `l3_verify`. 계획 표의 `l1_ticket_judgment`는 `judge.py`가
  `"l1_alert_triage" if kind == "alert" else "l1_ticket_judgment"`로 만들고, `l3_hunt`는 계획에만
  있고 코드에 없다(L3 가설 단계의 실제 이름을 확인해야 한다). 테스트에는 `task="test"`·`"l2_test"`
  같은 임시 이름이 있어 **알 수 없는 task를 기본 거부로 두면 그 테스트들이 깨진다.** 기본 거부(안전)와
  stage 폴백(호환) 중 어느 쪽인지 정해야 한다.
- **`uv run pytest`의 임시 디렉터리 권한.** 이 환경에서 `pytest-of-juhye` 아래 임시 경로가 간헐적으로
  `PermissionError: [WinError 5]`를 낸다(테스트 내용과 무관). 전체 실행은 통과했다.
- **셸 heredoc이 백슬래시를 하나 먹는다.** 테스트에 `'q"b\s\x01z한글'` 같은 소스를 넣을 때
  heredoc으로 쓰면 `\s`로 줄어 `SyntaxWarning`이 난다. 파일을 읽어 줄 단위로 바꾸거나 `chr(92)`로
  만들어야 한다.
- **계약을 고치면 두 곳을 같이 고친다.** `contracts/*.json` 수정 뒤
  `uv run python scripts/generate_contracts.py`를 돌려야 `src/soc/contracts/generated/`가 맞는다.
  새 계약 이름은 `tests/contract_samples.py`의 `CONTRACT_NAMES`에도 더해야 한다(별도 목록이다).

### 맞물리는 곳 (원칙 7, PR 전 확인 필요)

- `AgentTask.cited_refs`(선택)와 `AgentResult.cited_siem_refs`가 생겼다. 모든 태스크가 쓰는 구조다.
- `CallContext.siem_docs`(호출별)와 `ToolSession.siem_refs`(실행별)가 생겼다.
- 새 계약 이름 `l1_verdict`. 저장 Verdict는 바뀌지 않았다.
- `soc.normalize.mapping.normalize()`가 이벤트 원본을 거부한다. 이벤트 정규화를 부르던 코드는 없다.

## 확인 방법

```
uv run ruff format --check .   통과
uv run ruff check .            통과
uv run pytest                  2547 passed, 719 deselected
```

주요 테스트: `tests/test_tools_siem.py`(125건, 맵 5건·원문 가져오기 9건 포함),
`tests/test_agent_siem_refs.py`(6건, 인용 검증), `tests/normalize/`(이벤트 거부로 바뀐 것).
DB·Qdrant·ELK 마커 테스트와 서버 확인은 하지 않았다. 심 조회가 실제로 200을 받는지도
아직 확인하지 않았다(계획의 "전제", 개발 첫 단계 항목).
