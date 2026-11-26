---
issue: 382
date: 2026-11-26
owner: Juhyeok0603
supersedes: []
---

# 이벤트 정규화를 걷어내고 알럿에서 출발해 심에서 근거 로그를 직접 찾는다

## 목표

이벤트 OCSF 정규화를 파이프라인에서 없앤다. L1·L2·L3가 알럿에서 출발해 심(ELK)을 직접 조회하고, 근거로 쓸 문서를 모델이 인용하면 워커가 그 원문을 저장해 `evt_…`를 발급한다. 알럿 정규화와 근거 장부는 그대로 산다. 수리카타처럼 매핑표가 없는 소스도 근거로 쓸 수 있게 되는 것이 끝이다.

## 방법

```
ELK ─수집→ raw_records ─정규화→ alerts ──→ L1 ──→ L2 ──→ L3
                                            │      │      │
                              심 조회(도구) ─┴──────┴──────┤
                                                          │ 모델이 siem_ref로 인용
                                                          ▼
                                   워커: 원문 가져오기 → raw_records
                                         → normalize_status(succeeded)
                                         → events(class 0) → evt_ 발급
                                         → 다음 태스크의 근거 허용 목록에 더함
```

알럿 정규화를 남기는 이유는 엔티티가 거기서만 나오고(`src/soc/l1/ticketing.py:196`), 그 엔티티로 티켓이 묶이고 자산이 조회되기 때문이다.

### 1. 심 조회 대상을 소스 구분 없는 하나로 더한다

`siem.py`의 대상 상수에 ECS 공통 필드만 쓰는 대상을 더한다. 필터는 출발지·목적지 IP, 계정, 호스트, URL 경로, 메서드, 응답 코드, `event.module`, `event.dataset`. `event.module`로 좁히면 한 소스만, 안 좁히면 전부 걸린다. `default.toml`에는 넓은 예시(`logs-*,filebeat-*,.ds-logs-*,.ds-filebeat-*`)만 두고 실제 값은 `config/local.toml`에서 좁힌다. `siem.py`의 `_INDEX` 정규식이 `.`로 시작하는 이름을 허용하고 `_`로 시작하는 API 이름만 거부하므로 Filebeat 기본 스트림도 통과한다.

### 2. 원문 한 건을 통째로 가져오는 경로 (워커 전용, 도구 아님)

`query_siem`은 정해진 `_source` 필드만 돌려주고 문자열 하나를 300자, 히트를 200건으로 자른다(`FIELD_MAX_CHARS`, `SEARCH_MAX`). 불변 사본을 만들 수 없다. `siem_ref`로 문서 한 건을 통째로 받는 읽기 전용 경로(`GET /<index>/_doc/<id>`)를 더한다. 접속 설정 읽기·요청 단위 timeout·전체 마감 시간·응답 크기 상한·리다이렉트 비추적·오류 문구에 주소·키·본문을 넣지 않는 규칙을 도구와 공유하도록 함수로 뽑는다. 도구가 아니므로 레지스트리의 데몬 스레드(D-055)를 거치지 않는다.

**인덱스와 문서 ID는 `siem_ref`에서 되돌리지 않는다.** `src/soc/ids.py`의 `siem_ref_key`가 "키는 `/`로 나누어 `_index`와 `_id`로 되돌리지 않는다(index 이름의 `/`를 가정하지 않는다)"고 못 박았다. 대신 3번의 도구 세션 맵이 `siem_ref → (_index, _id)`를 들고 있고, 워커가 거기서 꺼내 쓴다. 모델에게는 인덱스 이름이 가지 않는다.

### 3. `siem_refs` 검증

모델이 적는 `siem_ref`는 밖에서 온 문자열이다(`docs/security.md` "밖에서 온 문자열"). 그 값이 ELK 요청 경로를 만들므로 형식 검사만으로는 부족하다. `ToolSession`에 `siem_refs: dict[SiemRefKey, tuple[str, str]]`을 더해 `query_siem`이 돌려준 히트의 `siem_ref`를 키로, 그 히트의 `(_index, _id)`를 값으로 모으고, 모델 출력의 `siem_refs`를 그 키 집합과 대조한다. 값은 2번의 원문 가져오기가 쓴다(검증과 조회가 같은 자료를 쓴다). `AgentResult`에 `cited_evidence_ids`와 나란히 실어 워커에게 넘긴다. 잘려서 모델에게 보이지 않은 히트(`fields_omitted`)의 `siem_ref`도 모델에게는 보였으므로 맵에 넣는다. 근거 장부 검사와 같은 자리(`src/soc/agent/runner.py`)에서 하고, 위반은 그 run을 멈춘다. `AgentTask`에 `cited_ids`와 나란히 `cited_refs`를 둔다.

### 4. 근거 발급은 워커가 한다

도구는 읽기 전용을 유지한다(`docs/security.md` "에이전트 도구의 한계"). 모델은 인용만 하고 코드가 저장한다. 한 트랜잭션에서 셋을 쓴다.

1. `raw_records`에 원문을 넣는다. `(siem_profile, siem_ref)` 유니크가 중복을 막는다. `siem_profile`은 수집과 분리해 `[tools.siem] evidence_siem_profile`의 값을 쓴다. 수집 체크포인트가 `(siem_profile, source_key)`별이라 섞이지 않고, 나중에 기존 데이터를 정리할 때 수집분과 발급분을 갈라낼 수 있다
2. `normalize_status`에 `status='succeeded'` + `result_kind='event'` + `result_id`를 쓴다. 이걸 빼면 `src/soc/normalize/store.py:47`이 그 원본을 집어가 같은 원본으로 Event를 또 만든다
3. `events`에 class 0 행을 넣고 `evt_…`를 발급한다

`events.ocsf`에 `raw_data`를 넣지 않는다. 원문은 `raw_records.original_text`에만 둔다. D-059가 "마스킹은 `raw_records.original_text`를 바꾸지 않고 에이전트의 원본 조회 도구에는 적용하지 않는다"로 원본과 정규화 결과를 나눠 뒀고, D-008도 같은 분리다. `raw_data`에 담으면 마스킹 대상이 되어 불변 사본이 아니게 된다.

`events.message`는 `event.dataset` 값으로 채운다(D-068 폴백 2순위). `summary`는 기존 `event_summary()`가 파생하고, `message`가 없으면 `event`가 된다. `time`은 원문의 `@timestamp`를 쓰고 시간대가 없으면 UTC로 본다. 읽을 수 없으면 발급을 실패로 둔다.

**발급 실패는 그 근거만 버리고 나머지로 진행한다.** 원문 가져오기 실패(심 장애, 문서가 이미 삭제됨), 시각 읽기 실패, 저장 실패 모두 같다. 그 run을 실패로 두지 않고, 버린 건수만 다음 태스크 입력에 넣는다(`asset_lookup_failed`와 같은 모양). 버린 `siem_ref` 값은 넣지 않는다(밖에서 온 문자열). 모델이 왜 그 근거를 인용할 수 없는지 모르면 같은 것을 다시 가리켜 형식 오류로 돌 수 있어서 건수는 알린다. 발급 건수와 버린 건수는 `details`에 남긴다.

`events.details.entities`는 발급 시점에 ECS 공통 엔티티 규칙으로 채운다. `common.yaml`의 `entities` 섹션을 알럿·이벤트 공용으로 승격한다. 빈 배열로 두면 `src/soc/l3/hunt/store.py:157`이 읽을 엔티티가 없어 헌팅 엔티티가 `model_only_entities`만 남는다.

### 5. 원본을 읽는 도구 `get_raw`

발급한 근거를 다음 태스크가 읽을 수단이 지금 없다. `src/soc/tools/`에 `raw_records`를 읽는 도구가 하나도 없고 `raw_detail`은 화면용 API다(`src/soc/api/routes/records.py`, `src/soc/api/ui_read.py`). `evt_`·`alt_` 또는 `raw_id`로 `raw_records.original_text`를 돌려주는 읽기 전용 도구를 만든다. D-059 마스킹은 적용하지 않고(그 결정이 이미 정한 예외) 모델 입력 필터 `screen_input`은 적용된다. 도구 결과 자르기(`max_chars`)가 걸리므로 모델에게는 발췌가 간다. 완전한 원문은 DB와 화면에만 있다.

### 6. 도구 허용 목록을 태스크별로 쪼갠다

`src/soc/agent/runner.py:142`가 `stage`의 허용 목록만 본다. 그래서 L2 보고 태스크에도 심 조회가 붙는다. 보고가 `siem_ref`를 인용하면 발급할 다음 태스크가 없다. `[tools.allowed]`를 단계 3개 키에서 태스크 7개 키로 바꾼다.

| 태스크 | 심 조회·`get_raw` |
|---|---|
| `l1_alert_triage` | 준다 |
| `l1_ticket_judgment` | 준다 |
| `l2_classify` | 주지 않는다. 그래프 후보와 모델 판단만 하는 단계이고 분류가 느려진다 |
| `l2_investigate` | 준다 |
| `l2_report` | 주지 않는다. 보고는 조사 결과만 보고 원문을 다시 보지 않는다(기존 2단계 설계) |
| `l3_hunt` | 준다 |
| `l3_verify` | 준다 |

그 밖의 도구는 지금 단계별 목록을 해당 태스크로 복사한다.

### 7. 이벤트 정규화를 걷어낸다

`[[ingest.sources]]`의 이벤트 대상 5개(nginx, apache, cloudtrail, azure, gcp), `mapping_tables/events/` 전체(클래스 표 7개 + 소스 표 2개), `event_tables.py`, 정규화의 이벤트 분기.

### 8. 프롬프트를 고친다

L1 판정·L2 조사·L3 헌팅 프롬프트에 "이벤트는 DB에 없다. 알럿에서 출발해 심을 조회하고, 근거로 쓸 문서는 `siem_refs`에 적는다"를 명시한다.

## 바꿀 곳

- `src/soc/tools/siem.py`: 소스 구분 없는 대상 상수 추가, 원문 한 건 가져오기 경로 추가, 접속·마감·상한 코드를 공유 함수로 분리
- `src/soc/tools/internal.py`: `get_raw` 추가, `query_records`의 `kind` enum을 `("alert",)`로 줄이고 설명에서 이벤트를 뺀다
- `src/soc/tools/web.py`: 파일 삭제(`query_http_flow`·`summarize_http_flow`뿐이다)
- `src/soc/tools/registry.py`: `ToolSession.siem_refs` 추가(`siem_ref → (_index, _id)` 맵)
- `src/soc/agent/runner.py`: `siem_refs` 검증, 태스크별 허용 목록 조회, `web.py` 참조 제거
- `AgentTask` 정의 위치: `cited_refs` 추가
- `src/soc/l1/judge.py`: 판정 출력 계약에 `siem_refs`, 발급 호출
- `src/soc/l2/analyze/worker.py`·`tasks.py`·`context.py`: `incident_findings`에 `siem_refs`, 조사 뒤 발급, 보고 허용 목록에 발급분 추가
- `src/soc/l3/hunt/verify.py`: `siem_refs`, 발급 호출
- 새 모듈(발급): 원문 가져오기 → `raw_records` → `normalize_status` → `events` 한 트랜잭션
- `src/soc/normalize/`: `event_tables.py` 삭제, `mapping_tables/events/` 삭제, 이벤트 정규화 분기 제거. `common.yaml`의 `entities`를 공용으로 승격
- `config/default.toml`: `[[ingest.sources]]` 이벤트 대상 5개 삭제, `[[tools.siem.targets]]` 새 대상, `[tools.allowed]`를 태스크 7개 키로, `[tools.siem] evidence_siem_profile` 추가
- `AgentResult`: `siem_refs` 맵을 실어 워커에게 넘긴다
- `src/soc/contracts/`: `incident_findings`·L1 판정 출력 계약에 `siem_refs`
- `docs/architecture.md`: 원칙 1에서 이벤트 정규화를 빼고 "근거 발급은 코드가 한다"를 넣는다. 원칙 3에 근거는 OCSF 공통 형식이 아니라 불변 사본이면 된다는 뜻을 명시한다. "큰 흐름" 표의 "수집·정규화" 줄에서 이벤트를 뺀다
- `docs/security.md`: `get_raw`의 마스킹 예외와 원문이 모델 입력으로 가는 한계를 "에이전트 도구의 한계"에 적는다
- `docs/decisions.md`: D-083·D-084 추가, D-067·D-069 폐기, D-007·D-062·D-068·D-073 수정
- `tests/`: `test_event_assemble.py`·`test_event_quality.py`·`test_event_tables.py`·`test_event_transforms.py`·`test_web_event_samples.py` 삭제 또는 새 동작으로 교체. 발급 경로·`siem_refs` 검증·태스크별 허용 목록 테스트 추가
- `tests/fake_siem.py`: `FakeElk`가 `POST /<index>/_search`만 허용하고 다른 경로는 599로 답한다. 제한된 `GET /<index>/_doc/<id>`를 허용 목록에 더한다
- `tests/fixtures/`: 심 조회 응답과 원문 한 건 샘플(문서용 IP 대역, `example.com`, 가짜 계정)

## 다른 코드와 맞물리는 곳

- **`[tools.allowed]` 설정 키 구조**를 단계별에서 태스크별로 바꾼다. L1·L2·L3 전부가 쓴다
- **`incident_findings`와 L1 판정 출력 계약**에 `siem_refs`를 더한다. 공통 계약 변경이다
- **`common.yaml`의 `entities`**를 알럿 전용에서 알럿·이벤트 공용으로 승격한다(D-062 수정)
- **`events` 표**에 class 0 원문 포인터 행이 들어온다. 기존 정규화 행과 섞인다. `ocsf_class` CHECK는 둘 다 통과한다
- **`normalize_status`**에 정규화기가 아닌 코드가 `succeeded` 행을 쓴다
- **`query_records`**의 `kind` enum이 줄어든다. **`query_http_flow`·`summarize_http_flow`**가 없어진다
- `AgentTask`에 `cited_refs`가 생기고 `AgentResult`에 `siem_refs` 맵이 생긴다. 모든 태스크가 쓰는 구조다
- **`[tools.siem]`에 `evidence_siem_profile`** 설정 키가 생긴다

위 전부 원칙 7 대상이다. **L1·L2·L3·UI 담당 확인이 PR 전에 필요하다.**

## 범위 밖

- DB에 이미 쌓인 정규화 이벤트 정리. 둔다. 기존 `evt_…` 근거가 살아 있어 과거 인시던트를 열어 볼 수 있다
- 알럿 정규화 변경(`common`의 `entities` 승격 외에는 그대로)
- `raw_records` 스키마 개편. 클래스를 안 정하니 필요 없다
- 조사 지연 개선. 측정만 하고 개선은 별도 안건
- 인시던트 종결 시 근거 보존 기간 정리(D-008)
- 심 조회를 MCP로 바꾸는 것(D-023 그대로)

## 완료 기준

- [ ] 이벤트 정규화 경로·매핑표·수집 대상이 없고, 관련 테스트가 지워졌거나 새 동작으로 바뀌었다
- [ ] 심 조회 대상 하나로 `event.module`을 바꿔 가며 여러 소스의 문서를 찾는다. `tests/fixtures/` 샘플로 확인하는 테스트가 있다
- [ ] 원문 가져오기 경로가 `siem_ref`로 문서 전체를 받고, 잘리지 않았음을 샘플로 확인한다
- [ ] 모델이 도구 결과에 없는 `siem_ref`를 적으면 그 run이 멈춘다. 샘플 테스트가 있다
- [ ] 도구 세션의 `siem_ref → (_index, _id)` 맵에 성공한 조회에서 보인 히트만 들어가고, 원문 가져오기가 그 인덱스·ID를 쓴다. `_id`에 이스케이프가 필요한 글자가 든 샘플로 확인하는 테스트가 있다
- [ ] 원문 가져오기가 실패하면 그 근거만 버리고 run이 계속되며, 버린 건수가 다음 태스크 입력과 `details`에 남는다. 샘플 테스트가 있다
- [ ] 발급분의 `raw_records.siem_profile`이 `evidence_siem_profile` 값이고, 같은 문서를 수집이 가져와도 서로 덮지 않는다
- [ ] 발급이 한 트랜잭션에서 `raw_records`·`normalize_status`(succeeded)·`events`를 쓰고, 같은 원본으로 Event가 두 개 생기지 않는다. 정규화기를 이어 돌려 확인하는 테스트가 있다
- [ ] `l1_alert_triage`·`l1_ticket_judgment`·`l2_investigate`·`l3_hunt`·`l3_verify`에서 발급이 되고, 다음 태스크가 그 `evt_…`를 인용해 근거 장부 검사를 통과한다
- [ ] `l2_classify`·`l2_report`에 심 조회와 `get_raw`가 등록되지 않는다. 테스트가 태스크 7개의 허용 목록을 검사한다
- [ ] 발급된 Event의 `details.entities`가 ECS 공통 규칙으로 채워지고, `src/soc/l3/hunt/store.py`의 `record_entities`가 그 값을 읽는다
- [ ] `get_raw`가 `evt_`·`alt_`·`raw_id`로 원문을 돌려주고, `screen_input`이 적용된다
- [ ] `get_event`가 class 0 원문 포인터 Event에 대해 동작하고 `query_records`가 `kind=alert`만 받는다
- [ ] 기존 `evt_…` 근거로 만들어진 과거 인시던트를 화면에서 열어 볼 수 있다 (손으로 확인)
- [ ] 개발 첫 단계에서 서버의 심 조회가 실제로 200을 받는 것을 확인했다 (손으로 확인)
- [ ] L2 조사·보고의 라운드 소요 시간을 전·후로 측정해 `docs/notes/`에 건수로 적었다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과
- [ ] D-083·D-084가 `docs/decisions.md` "확정"에, D-067·D-069가 "폐기"에, 수정된 D-007·D-062·D-068·D-073이 반영됐다
- [ ] `docs/architecture.md` 원칙 1·3과 "큰 흐름", `docs/security.md` "에이전트 도구의 한계"가 고쳐졌다
- [ ] 공통 계약·설정 키 변경에 L1·L2·L3·UI 담당 확인을 받았다
- [ ] `docs/notes/382-siem-direct-evidence.md`에 개발 기록이 있다

## 토론으로 정한 것

이슈 본문의 "어떻게"에서 달라진 점과 이유다.

1. **`siem_refs`를 도구 결과와 대조해 검증한다.** 이슈 본문에는 검증 규칙이 없었다. `siem_ref`가 ELK 요청 경로를 만드는데 모델이 적는 자유 텍스트라, `docs/security.md`의 "로그 내용이 어떤 도구를 부를지를 직접 바꾸지 못하게 한다"와 "판정 근거로 나온 ID는 실제로 존재하는지 코드로 확인한다"를 어긴다. `ToolSession`에 모은 집합과 대조하는 쪽으로 정했다.
2. **원문을 `events.ocsf.raw_data`에 담지 않는다.** 이슈 본문은 거기 담으려 했다. D-059가 정규화 결과(`ocsf`·`details`)의 Cookie·Authorization을 마스킹하고 `raw_records.original_text`는 바꾸지 않는다고 이미 정해 뒀다. 담으면 마스킹 대상이 되어 불변 사본이 아니게 된다. `raw_records`에만 두기로 했다.
3. **그 결과 `get_raw` 도구가 필요해졌다.** 2번으로 `events` 행이 포인터만 되는데, 에이전트가 `raw_records`를 읽는 도구가 하나도 없었다(`raw_detail`은 화면용 API). 도구를 새로 만들기로 했다. 대안으로 "모델이 필요할 때 심을 다시 조회"가 있었지만 심이 로그를 지우면 근거를 못 읽어 재현성이 반쪽이 된다.
4. **`events.summary`를 빈 문자열로 두지 않는다.** 이슈 본문은 빈 문자열로 쓰려 했으나 `event_summary()`가 `message`가 없으면 `event`를 돌려주고, D-068이 폴백 2순위로 `event.dataset`을 이미 정해 뒀다. `message` = `event.dataset`로 간다.
5. **도구 허용 목록을 태스크별로 쪼갠다.** 이슈 본문은 단계별 목록을 전제했다. `runner.py:142`가 `stage`만 보므로 L2 보고에도 심 조회가 붙고, 보고가 인용하면 발급할 다음 태스크가 없다. 프롬프트로만 막는 안도 있었지만 구조적 보장이 아니어서 설정 구조를 바꾸기로 했다.
6. **발급 시점에 ECS 공통 엔티티를 채운다.** 이슈 본문은 `entities=[]`와 L3 엔티티 품질 저하를 "받아들이는 비용"으로 뒀다. `src/soc/l3/hunt/store.py:157`이 그 값을 읽어 헌팅 엔티티에 머지하므로, 매핑표를 없애면서 엔티티 규칙 하나만 남기는 쪽으로 정했다. `common.yaml`의 `entities`를 공용으로 올린다(D-062 수정).
7. **발급 경로가 `normalize_status`를 쓴다.** 이슈 본문에 없었다. `src/soc/normalize/store.py:47`이 `normalize_status` 행이 없는 `raw_records`를 자동 등록하므로, 안 쓰면 정규화기가 같은 원본으로 Event를 또 만든다.
8. **내부 조회 도구 처리를 정했다.** `get_event` 남김, `query_records`는 `kind=alert`만 남김, `query_http_flow`·`summarize_http_flow` 삭제(`src/soc/tools/web.py`가 통째로 없어진다).
9. **`ecs_fields.yaml` 허용 목록 검사를 남긴다.** D-069가 폐기되며 사라질 검사지만 엔티티 추출이 ECS 필드를 읽으므로 남긴다.
10. **D-062를 수정 대상에 더했다.** 이슈 본문의 폐기·수정 표에 없었다.

11. **도구 세션이 `siem_ref → (_index, _id)` 맵을 든다.** 처음에는 `set[str]`으로 두려 했으나 `src/soc/ids.py`의 `siem_ref_key`가 키를 `_index`·`_id`로 되돌리지 못하게 해 놔서 `GET /<index>/_doc/<id>`를 부를 방법이 없었다. 검증용 집합을 맵으로 올리면 검증(3번)과 조회(2번)가 같은 자료를 쓴다. 대안으로 `_search`에 `_id` term을 쓰는 안이 있었지만 인덱스 패턴에 의존해 롤오버 뒤에 못 찾을 수 있다.
12. **발급 실패는 그 근거만 버리고 진행한다.** 실패 횟수에 넣어 보류로 보내는 안도 있었으나, 심 쪽 사정으로 판정 전체가 멈추는 것보다 낫고 `asset_lookup_failed`가 이미 같은 방식을 쓴다. 버린 건수는 알리고 ref 값은 알리지 않는다.
13. **발급용 `siem_profile`을 수집과 분리한다.** 같은 `elk-default`를 쓰는 안도 있었으나, 분리하면 수집 체크포인트와 섞이지 않고 나중에 기존 데이터를 정리할 때 둘을 갈라낼 수 있다.

새 결정: **D-083**(이벤트 근거를 심에서 찾아 원문으로 발급하는 방식, `get_raw` 포함), **D-084**(도구 허용 목록을 태스크별로 둔다).

### 알려진 위험

- **마스킹 안 된 원문이 외부 LLM으로 간다.** `get_raw` 결과에 D-059 마스킹을 적용하지 않는다. 모델 입력 필터 `screen_input`이 알려진 비밀 모양은 가리지만 `docs/security.md`의 한계(8자 미만, 카멜 케이스, 명령줄 모양, `pwd=/a/b` 모양 등)는 통과한다
- **조사가 느려질 수 있다.** 요약 대신 발췌 원문을 받고 심 조회를 여러 번 한다. 워커가 단일 스레드 순차이고 조사가 이미 평균 30초다(#370 기록). 측정만 한다
- **발급 전 문서는 심 수명에 묶인다.** 인덱스 수명주기로 지워지면 채택할 기회가 사라진다
- **`events`에 두 종류가 섞인다.** 기존 정규화 행(class 4002 등)과 원문 포인터 행(class 0)이 공존한다
- **모델에게 가는 원문은 잘린다.** 도구 결과 자르기가 적용된다. 불변 사본은 저장 쪽에만 해당한다

## 바뀐 점

- **2026-11-26** — `/soc-plan` 재검토에서 세 가지를 더했다. (1) 도구 세션의 `siem_refs`를 `set[str]`에서 `siem_ref → (_index, _id)` 맵으로 올렸다. 그것이 없으면 `siem_ref_key`를 되돌릴 수 없어 원문 가져오기 경로를 만들 수 없었다(빈칸). (2) 발급 실패 처리를 정했다(그 근거만 버리고 진행, 건수만 알림). (3) 발급용 `siem_profile`을 수집과 분리했다. 코덱스 교차 검증에서 (1)이 막힌 것을 확인했다.
