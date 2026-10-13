# 데이터 계약

박스끼리 주고받는 데이터의 필드명, 타입, 필수 여부를 고정한다. 박스를 따로 만들어도 서로 맞물리게 하기 위한 문서다.

> **상태: 초안.** 박스 1~24가 주고받는 객체를 모두 정의했다. 공통 기반(구현 순서 0단계) PR에서 사람이 검토해 "확정"으로 바꾼다. 확정 후에는 아래 "바꾸는 절차"를 거쳐야만 바꿀 수 있다.

## 공통 규칙

- 필드명은 `snake_case`
- 시간은 UTC epoch 밀리초 정수(`int`). 필드명은 `time`, `*_at`, `*_seen`, 그리고 유효 기간용 `valid_from`, `valid_to`
- ID는 접두어가 붙은 문자열: `raw_`, `al_`, `ev_`, `tk_`, `in_`, `cs_`, `ht_`, `rp_`, `doc_`
- 필수 아님(`선택`) 필드는 값이 없으면 `null`. 필드 자체를 빼지 않는다
- 목록 필드는 값이 없으면 빈 목록 `[]`
- 열거형(enum)은 아래 표에 적힌 값만 쓴다
- 여러 객체가 함께 쓰는 작은 객체(Entity, Evidence)는 맨 아래 "공통 객체"에 한 번만 정의한다
- **확장 필드**: 표에 `extensions`가 있는 객체는 조직이나 플러그인이 붙인 추가 필드를 담는다. 키는 `<조직 또는 플러그인>.<필드>` 형식이고, 코어 코드는 읽지 않고 그대로 전달·저장한다. 원본에서 매핑되지 않은 값은 `unmapped`, 일부러 붙인 값은 `extensions`다
- **등록형 값**: 타입이 `등록형`인 필드는 열거형처럼 정해진 값만 쓰지만, 플러그인이 새 값을 등록해 늘릴 수 있다. 표에 적힌 값은 기본으로 제공하는 값이다(`docs/extensibility.md`)
- 계약의 코드 원본은 레포 루트 `contracts/`의 JSON Schema(draft-07)다. Python 모델과 TypeScript 타입은 여기서 생성하고, 생성된 파일은 직접 고치지 않는다(D-014, D-025, D-031, D-032). 아래 "계약 Schema" 참고

## 바꾸는 절차

1. 바꿀 필드와 이유, 영향받는 박스와 화면을 적어 사람에게 제안한다.
2. 승인되면 같은 PR에서 이 문서 → `contracts/`의 Schema → 생성 명령으로 Python·TypeScript 코드 다시 생성 → 영향받는 박스·화면 코드와 테스트 순서로 고친다.
3. PR "변경 내용"에 "데이터 계약 변경"이라고 표시한다.
4. 필드를 없애기보다 `선택`으로 바꾸는 쪽을 먼저 검토한다.

## 계약 Schema

이 문서는 사람이 읽는 설명이고, 코드가 쓰는 원본은 `contracts/`의 JSON Schema다. 둘은 항상 같아야 하고, 바꿀 때는 같은 PR에서 함께 바꾼다.

| 무엇 | 위치 |
|---|---|
| 원본 Schema | `contracts/<snake_case>.schema.json` (객체 하나에 파일 하나) |
| Python 생성 코드 (Pydantic) | `src/soc/contracts/generated/` |
| TypeScript 생성 코드 | `frontend/src/contracts/generated/` |
| 생성 명령 | `uv run python scripts/generate_contracts.py` (두 언어 함께 생성; 아래 "계약 생성 구현 (#5)" 참고) |

Schema로 옮길 때 지킬 것:

- **선택 필드**: 이 문서의 공통 규칙대로 필드를 빼지 않으므로, 모든 필드를 `required`에 넣고 선택 필드는 타입에 `null`을 더한다. 예: `"type": ["string", "null"]`
- **열거형**: `enum`으로 쓴다.
- **등록형 값**: 플러그인이 늘릴 수 있어야 하므로 `enum`을 쓰지 않고 `"type": "string"`으로 둔다. 기본값은 `description`에 적는다. 값 검증은 플러그인 레지스트리가 한다(`docs/extensibility.md` 5항).
- **`extensions`**: `"type": "object"`, `"additionalProperties": true`
- **공통 객체**(Entity, Evidence 등): 파일 하나에 정의하고 `$ref`로 가져다 쓴다.
- **필드 사이 조건**: draft-07로 표현 가능한 조건은 원본 Schema의 `if`/`then`, `anyOf` 등으로 검증한다. 생성 타입만으로 이를 대체하지 않는다. 원본 참조 확인·계산·상태 전이처럼 코어 동작이 필요한 비즈니스 조건은 설명과 후속 박스의 검증으로 남긴다. 아래 "Schema 검증과 생성 타입의 범위" 참고.
- 생성된 파일 맨 위에 "자동 생성, 직접 수정 금지"와 생성 명령을 적는다.
- CI는 생성 명령을 다시 돌려 생성 파일에 차이가 생기면 실패한다.

## 객체 한눈에 보기

| ID | 객체 | 만드는 박스 → 쓰는 박스 |
|---|---|---|
| C1 | RawRecord | 1 → 2, 3 |
| C2 | SiemAlert | 3 → 4 |
| C20 | AliasTable (설정) | 사람 → 4 |
| C3 | NormalizedAlert | 4 → 5 |
| C12 | NormalizeFailure | 4 → 사람 확인 |
| C13 | EventRecord | 4, 5 → 7, 23 |
| C4 | AssetInfo, UserInfo | 5 (룩업 표) |
| C5 | AlertRecord | 5, 6 → 8, 9, 11 |
| C6 | Ticket | 9, 10 → 11, 16, 17 |
| C7 | Verdict | 11 → 10, 16 |
| C8 | AgentStep | 9, 11, 13, 14, 19, 23, 24 → 12 |
| C9 | HumanReview | 16 → 10, 17 (`tp`면 Correlation으로) |
| C10 | Incident | 17, 18 → 19 |
| C11 | IncidentArtifact | 19 → 20, 21 |
| C14 | SpecialistFinding | 13, 14 → 11 |
| C15 | L2Review | 21 → 19, 22 |
| C16 | Case | 22 → 8, 23, 24 |
| C17 | HuntFinding | 23 → 17, 24 |
| C18 | RuleProposal | 24 → 3 (사람 승인 후) |
| C19 | VectorDoc | 5, 6, 7, 10, 18, 22 → 8 |

---

## C1 · RawRecord

수집한 원본 한 건. 내용은 손대지 않는다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| raw_id | str | ✅ | `raw_` 접두어. 파일 입력은 `raw_<파일명>_<줄번호>`, 그 밖에는 커넥터가 정하는 고유값 |
| source_type | 등록형 | ✅ | 커넥터 이름. 기본 `web`, `cloud` |
| received_at | int | ✅ | 수집 시각 |
| payload | str | ✅ | 원문 한 줄 그대로 |
| sha256 | str | ✅ | `payload`의 해시 |

## C2 · SiemAlert

SIEM 어댑터가 낸 알럿 또는 이벤트. 시나리오마다 필드명이 달라도 그대로 둔다. SIEM 없이 받을 때는 `direct` 어댑터가 C1을 이 형식으로 바꾼다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| kind | enum | ✅ | `alert`(박스 4가 C3로 바꿈), `event`(C13으로 바꿈) |
| scenario | str | ✅ | 탐지 시나리오 또는 이벤트 종류 이름. 정규화 시 C20 별칭 표를 고르는 키. `direct` 어댑터는 설정에서 정한 이름을 쓴다 |
| raw_ids | list[str] | ✅ | 근거가 된 RawRecord ID |
| fields | dict | ✅ | SIEM 알럿 JSON 원본 그대로 |

## C20 · AliasTable

박스 4가 쓰는 시나리오별 별칭 표. 데이터가 아니라 설정 파일이다(형식은 D-015). 조직은 같은 `scenario` 이름의 파일로 기본 표를 덮어쓴다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| scenario | str | ✅ | C2의 `scenario`와 같은 값 |
| kind | enum | ✅ | `alert`, `event` |
| class_uid | int | 선택 | `event`일 때 C13의 OCSF 활동 클래스. `alert`는 항상 `2004` |
| activity | str | 선택 | `event`일 때 C13의 `activity` 값 |
| fields | dict[str, list[str]] | ✅ | C3·C13 필드 이름 → 원본 필드 이름 후보 목록. 앞에 있는 것부터 찾는다. 점(`.`)으로 중첩 필드를 가리킨다 |
| time_format | str | ✅ | 원본 시간 형식: `iso8601`, `epoch_s`, `epoch_ms`, 또는 strftime 형식 문자열 |
| severity_map | dict[str, int] | 선택 | 원본 심각도 값 → `severity_id`(0~6). `alert`면 필수 |
| default_techniques | list[str] | 선택 | 원본에 기법 정보가 없을 때 쓸 ATT&CK 기법 ID |
| extensions_map | dict[str, str] | 선택 | 원본 필드 → `extensions` 키. 조직이 보존하고 싶은 값 |

규칙
- `fields`에 없는 원본 필드는 `unmapped`로 간다.
- C2의 `scenario`에 맞는 표가 없으면 C12(`unknown_scenario`), 필수 필드를 못 찾으면 C12(`missing_required`), 시간·심각도 변환에 실패하면 C12(`bad_value`)를 만든다.
- C12는 저장소에 남기고, 운영자가 별칭 표를 고칠 때 근거로 본다.

## C3 · NormalizedAlert

정규화를 거친 알럿. 오른쪽 열은 OCSF Detection Finding(`class_uid` 2004)에서 대응하는 경로로, OCSF 버전(D-017)이 확정되면 그 버전으로 검증한다.

| 필드 | 타입 | 필수 | 설명 | OCSF 경로 (참고) |
|---|---|---|---|---|
| class_uid | int | ✅ | 알럿은 `2004` | `class_uid` |
| time | int | ✅ | 탐지 시각 | `time` |
| severity_id | int | ✅ | 0~6 (0 Unknown ~ 6 Fatal) | `severity_id` |
| rule_id | str | ✅ | 탐지 룰 ID | `finding_info.analytic.uid` |
| rule_name | str | ✅ | 탐지 룰 이름 | `finding_info.analytic.name` |
| src_ip | str | 선택 | 출발지 IP | `src_endpoint.ip` |
| src_port | int | 선택 | | `src_endpoint.port` |
| dst_ip | str | 선택 | 목적지 IP | `dst_endpoint.ip` |
| dst_port | int | 선택 | | `dst_endpoint.port` |
| host | str | 선택 | 대상 호스트명 | `device.hostname` |
| user | str | 선택 | 관련 계정 | `actor.user.name` |
| http_url | str | 선택 | 웹 알럿의 요청 URL (원문, 데이터로만 취급) | `http_request.url.url_string` |
| http_status | int | 선택 | 웹 알럿의 응답 코드 | `http_response.code` |
| techniques | list[str] | ✅ | ATT&CK 기법 ID. 예: `T1190`. 원본에 없으면 C20의 `default_techniques`, 그것도 없으면 `[]` | `attacks[].technique.uid` |
| raw_ids | list[str] | ✅ | C2에서 그대로 | |
| unmapped | dict | ✅ | 별칭 표에 없는 원본 필드 | `unmapped` |
| extensions | dict | ✅ | 조직·플러그인 추가 필드. 없으면 `{}` | |

규칙: `src_ip`, `dst_ip`, `host` 중 하나 이상은 있어야 한다. 필수 필드가 비면 이 객체를 만들지 않고 C12 NormalizeFailure를 만든다.

## C12 · NormalizeFailure

정규화하지 못한 알럿 또는 이벤트. 버리지 않고 모아서 사람이 별칭 표를 고칠 근거로 쓴다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| scenario | str | ✅ | C2에서 그대로 |
| raw_ids | list[str] | ✅ | C2에서 그대로 |
| reason | enum | ✅ | `unknown_scenario`(별칭 표 없음), `missing_required`(필수 필드 없음), `bad_value`(시간·심각도 변환 실패) |
| missing_fields | list[str] | ✅ | 비어 있던 C3·C13 필수 필드 이름. 없으면 `[]` |
| detail | str | 선택 | 실패 내용 한 줄 |
| failed_at | int | ✅ | |

## C13 · EventRecord

정규화와 룩업을 거친 info 수준 이벤트. Event 저장소의 한 행. 알럿보다 양이 훨씬 많다.

| 필드 | 타입 | 필수 | 설명 | OCSF 경로 (참고) |
|---|---|---|---|---|
| event_id | str | ✅ | `ev_` 접두어 | |
| class_uid | int | ✅ | OCSF 활동 클래스 ID (예: HTTP Activity, Authentication) | `class_uid` |
| time | int | ✅ | | `time` |
| activity | str | ✅ | 활동 이름. 예: `http_request`, `logon`, `api_call` | `activity_name` |
| src_ip | str | 선택 | | `src_endpoint.ip` |
| dst_ip | str | 선택 | | `dst_endpoint.ip` |
| host | str | 선택 | | `device.hostname` |
| user | str | 선택 | | `actor.user.name` |
| http_url | str | 선택 | 원문, 데이터로만 취급 | `http_request.url.url_string` |
| http_status | int | 선택 | | `http_response.code` |
| api_operation | str | 선택 | 클라우드 API 이름 | `api.operation` |
| status | str | 선택 | 성공·실패 | `status` |
| src_asset | AssetInfo | 선택 | | |
| dst_asset | AssetInfo | 선택 | | |
| user_info | UserInfo | 선택 | | |
| raw_ids | list[str] | ✅ | | |
| unmapped | dict | ✅ | | `unmapped` |
| extensions | dict | ✅ | 조직·플러그인 추가 필드. 없으면 `{}` | |

## C4 · AssetInfo, UserInfo

Lookup 표의 한 행이자, 알럿에 붙는 정보.

**AssetInfo**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| match | str | ✅ | IP 또는 CIDR |
| hostname | str | ✅ | |
| criticality | int | ✅ | 1(낮음) ~ 5(높음) |
| owner | str | 선택 | 담당자 |
| zone | str | 선택 | `dmz`, `internal` 등 |
| shared | bool | ✅ | 프록시·DNS·도메인 컨트롤러 같은 공용 자산이면 `true`. Correlation에서 묶는 기준으로 쓰지 않는다 |
| valid_from | int | 선택 | 이 대응이 유효한 시작 시각 |
| valid_to | int | 선택 | 끝 시각. `null`이면 현재까지 |
| extensions | dict | ✅ | CMDB 등에서 가져온 추가 속성. 없으면 `{}` |

**UserInfo**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| user | str | ✅ | 계정명 |
| dept | str | 선택 | 부서 |
| privileged | bool | ✅ | 관리자 권한 여부 |
| extensions | dict | ✅ | 디렉터리 서비스 등에서 가져온 추가 속성. 없으면 `{}` |

## C5 · AlertRecord

C3에 룩업 결과와 저장 정보를 더한 것. Alert 저장소의 한 행.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| alert_id | str | ✅ | `al_` 접두어 |
| (C3의 모든 필드) | | | C3와 같은 이름, 같은 타입. `extensions` 포함 |
| src_asset | AssetInfo | 선택 | 모르는 IP면 `null` |
| dst_asset | AssetInfo | 선택 | |
| user_info | UserInfo | 선택 | |
| count | int | ✅ | 중복으로 합쳐진 횟수. 처음엔 1 |
| first_seen | int | ✅ | |
| last_seen | int | ✅ | |

## C6 · Ticket

L1이 처리하는 업무 단위.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| ticket_id | str | ✅ | `tk_` 접두어 |
| status | enum | ✅ | `new`, `triaging`, `awaiting_human`, `closed_benign`, `closed_fp`, `escalated` |
| handling_type | 등록형 | ✅ | 기본 `web_attack`, `scan`, `cloud`, `other` |
| specialist | 등록형 | ✅ | 전문 에이전트 이름. 기본 `none`, `web`, `cloud` |
| priority | int | ✅ | `severity_id × 대상 자산 criticality`. 대상 자산은 `dst_asset`, 없으면 `src_asset`, 둘 다 없으면 criticality 1로 계산 |
| alert_ids | list[str] | ✅ | 하나 이상 |
| entities | list[Entity] | ✅ | 공통 객체 Entity. Correlation이 이 값을 본다 |
| verdict | Verdict | 선택 | 판정 전에는 `null` |
| extensions | dict | ✅ | 조직·플러그인 추가 필드. 외부 티켓 시스템 ID 등. 없으면 `{}` |
| created_at | int | ✅ | |
| updated_at | int | ✅ | |

상태 전이: `new → triaging → (awaiting_human →) closed_benign | closed_fp | escalated`

## C7 · Verdict

L1의 판정 결과. LLM 출력이 이 형식을 통과하지 못하면 판정으로 쓰지 않는다(`docs/llm-policy.md`).

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| verdict | enum | ✅ | `tp`, `fp`, `unknown` |
| confidence | float | ✅ | 0.0 ~ 1.0 |
| summary | str | ✅ | 한두 문장 |
| evidence | list[Evidence] | ✅ | 하나 이상. 공통 객체 Evidence. `ref_type`은 `alert`, `event`, `raw`를 쓴다 |
| recommended_action | str | ✅ | 권고 조치. 실행하지 않는다 |
| needs_human | bool | ✅ | 사람 검토가 필요하면 `true` |
| human_reason | str | 선택 | `needs_human`이 `true`일 때 이유 |

## C8 · AgentStep

에이전트의 조사 단계 하나. Agent Log의 한 행.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| subject_type | enum | ✅ | `ticket`, `incident`, `hunt`. 이 단계가 속한 작업 |
| subject_id | str | ✅ | 해당 객체 ID (`tk_`, `in_`, `ht_`) |
| step | int | ✅ | 같은 작업 안에서 1부터 증가 |
| agent | str | ✅ | 예: `analyst`, `l1`, `web`, `cloud`, `l2`, `l3` |
| action | enum | ✅ | `llm_call`, `tool_call`, `decision` |
| tool | str | 선택 | `tool_call`일 때 도구 이름 |
| prompt_version | str | 선택 | `llm_call`일 때 프롬프트 파일 버전 |
| input_excerpt | str | ✅ | 입력 앞부분 (최대 2,000자) |
| output_excerpt | str | ✅ | 출력 앞부분 (최대 2,000자) |
| model | str | 선택 | |
| tokens | int | 선택 | |
| latency_ms | int | ✅ | |
| created_at | int | ✅ | |

## C9 · HumanReview

사람의 L1 검토 결과.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| ticket_id | str | ✅ | |
| reviewer | str | ✅ | |
| decision | enum | ✅ | `tp`, `fp` |
| overturned | bool | ✅ | 에이전트 판정과 다르면 `true` |
| reason | str | 선택 | `overturned`가 `true`면 필수 |
| created_at | int | ✅ | |

## C10 · Incident

한 캠페인으로 묶인 티켓·헌팅 결과 묶음. 모든 Incident는 Correlation(17)이 만든다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| incident_id | str | ✅ | `in_` 접두어 |
| title | str | ✅ | |
| status | enum | ✅ | `open`, `investigating`, `closed_benign`, `escalated_to_case` |
| created_by | enum | ✅ | `correlation`(규칙이 묶음), `manual`(사람이 직접 묶음). 묶음 항목의 출처는 IncidentMember `source` |
| severity_id | int | ✅ | 0~6. `excluded`가 아닌 묶음 항목 중 가장 높은 값. 티켓 항목은 소속 알럿(C5)의 `severity_id`, 헌팅 항목은 C17의 `severity_id`를 쓴다 |
| first_seen | int | ✅ | |
| last_seen | int | ✅ | |
| tactics | list[str] | ✅ | ATT&CK 전술 ID. 예: `TA0001` |
| summary | str | 선택 | L2가 채운다 |
| members | list[IncidentMember] | ✅ | 아래 IncidentMember |
| extensions | dict | ✅ | 조직·플러그인 추가 필드. 없으면 `{}` |

**IncidentMember**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| member_type | enum | ✅ | `ticket`, `hunt` |
| ticket_id | str | 선택 | `member_type`이 `ticket`이면 필수 |
| hunt_id | str | 선택 | `member_type`이 `hunt`이면 필수. C17 |
| source | enum | ✅ | 이 항목이 Correlation에 들어온 경로. `l1`(L1이 TP로 판정), `human_l1`(사람이 L1 검토에서 TP로 확정), `l3`(L3 이상 징후) |
| rule | str | ✅ | 묶인 Correlation 규칙 ID. 사람이 묶었으면 `manual` |
| matched_entity | Entity | 선택 | 묶는 기준이 된 엔티티 (공통 객체) |
| excluded | bool | ✅ | L2가 노이즈로 뺐으면 `true` |
| excluded_reason | str | 선택 | `excluded`가 `true`면 필수 |

## C11 · IncidentArtifact

L2의 분석 결과물. 사람이 읽는 보고서는 이 객체로부터 만든다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| incident_id | str | ✅ | |
| timeline | list[TimelineEntry] | ✅ | 시간순 |
| affected_assets | list[str] | ✅ | 호스트명 |
| iocs | list[Ioc] | ✅ | 아래 Ioc |
| suspected_cause | str | ✅ | |
| recommendations | list[Recommendation] | ✅ | 아래 Recommendation |
| needs_human | bool | ✅ | 사람 확인이 필요하면 `true`. LLM 출력 실패 처리는 `docs/llm-policy.md` 4항 |
| human_reason | str | 선택 | `needs_human`이 `true`일 때 이유 |
| generated_at | int | ✅ | |

**Ioc**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| type | 등록형 | ✅ | 기본 `ip`, `domain`, `url`, `hash` |
| value | str | ✅ | IOC 값 |

**Recommendation**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| action | str | ✅ | 권고 조치 |
| risk | enum | ✅ | `low`, `medium`, `high` |
| reversible | bool | ✅ | 되돌릴 수 있는지 여부 |

**TimelineEntry**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| time | int | ✅ | |
| tactic | str | 선택 | ATT&CK 전술 ID |
| technique | str | 선택 | ATT&CK 기법 ID |
| description | str | ✅ | |
| evidence | list[Evidence] | ✅ | 하나 이상. 공통 객체 Evidence (모든 `ref_type` 사용) |

## C14 · SpecialistFinding

전문 에이전트(Cloud, Web)가 L1의 질문에 답한 분석 결과. LLM 출력은 이 형식으로 검증한다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| ticket_id | str | ✅ | |
| specialist | 등록형 | ✅ | 기본 `web`, `cloud` |
| question | str | ✅ | L1이 물은 것 |
| summary | str | ✅ | 한두 문장 |
| attack_type | 등록형 | 선택 | 기본 `sqli`, `scan`, `lfi`, `rfi`, `webshell_upload`, `logging_disabled`, `role_abuse`. 전문 에이전트가 늘릴 수 있다 |
| succeeded | enum | ✅ | `yes`, `no`, `unknown` |
| confidence | float | ✅ | 0.0 ~ 1.0 |
| evidence | list[Evidence] | ✅ | 하나 이상. `ref_type`은 `alert`, `event`, `raw` |
| details | dict | ✅ | 전문 분야별 추가 정보. 예: 클라우드는 주체·API 호출 흐름. 없으면 `{}` |
| needs_human | bool | ✅ | 사람 확인이 필요하면 `true`. LLM 출력 실패 처리는 `docs/llm-policy.md` 4항 |
| human_reason | str | 선택 | `needs_human`이 `true`일 때 이유 |
| created_at | int | ✅ | |

## C15 · L2Review

사람의 L2 검토 결과.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| incident_id | str | ✅ | |
| reviewer | str | ✅ | |
| decision | enum | ✅ | `approve`, `reject` |
| reject_type | enum | 선택 | `wrong_grouping`, `missing_step`, `wrong_conclusion`. `reject`면 필수 |
| comment | str | 선택 | `reject`면 필수 |
| round | int | ✅ | 같은 Incident의 몇 번째 검토인지. 1부터 |
| created_at | int | ✅ | |

## C16 · Case

사람이 확정한 실제 사고.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| case_id | str | ✅ | `cs_` 접두어 |
| incident_id | str | ✅ | |
| title | str | ✅ | |
| status | enum | ✅ | `open`, `responding`, `closed` |
| tasks | list[CaseTask] | ✅ | 아래 CaseTask |
| lessons | str | 선택 | 종결 시 작성 |
| extensions | dict | ✅ | 조직·플러그인 추가 필드. 외부 케이스 시스템 ID 등. 없으면 `{}` |
| created_at | int | ✅ | |
| closed_at | int | 선택 | |

**CaseTask**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| task | str | ✅ | 작업 내용 |
| owner | str | ✅ | 담당자 |
| due_at | int | 선택 | 마감 시각 |
| status | enum | ✅ | `todo`, `doing`, `done` |

## C17 · HuntFinding

L3 헌팅 한 번의 결과.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| hunt_id | str | ✅ | `ht_` 접두어 |
| hypothesis | str | ✅ | 헌팅 가설 |
| techniques | list[str] | ✅ | 가설과 관련된 ATT&CK 기법 ID |
| method | enum | ✅ | `baseline`(통계 기준선), `hypothesis`(가설 기반) |
| query_summary | str | ✅ | 무엇을 어떻게 조회했는지 |
| evidence | list[Evidence] | ✅ | 찾은 근거. `ref_type`은 주로 `event`. 없으면 `[]` |
| is_anomaly | bool | ✅ | 이상 징후로 판단했으면 `true` |
| severity_id | int | ✅ | 0~6 (C3와 같은 척도). L3가 이상 징후의 심각도를 정한다. `is_anomaly`가 `false`면 0(Unknown) |
| incident_id | str | 선택 | Correlation이 Incident로 묶었으면 그 ID |
| rule_candidate | bool | ✅ | 반복 가능한 패턴이라 룰 제안으로 넘길지 |
| needs_human | bool | ✅ | 사람 확인이 필요하면 `true`. LLM 출력 실패 처리는 `docs/llm-policy.md` 4항 |
| human_reason | str | 선택 | `needs_human`이 `true`일 때 이유 |
| created_at | int | ✅ | |

## C18 · RuleProposal

탐지 룰 제안. 자동 배포하지 않는다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| proposal_id | str | ✅ | `rp_` 접두어 |
| hunt_id | str | 선택 | 근거가 된 C17. `hunt_id`와 `case_id` 중 하나 이상은 필수 |
| case_id | str | 선택 | 근거가 된 C16 (Case에서 찾은 패턴으로 제안할 때) |
| title | str | ✅ | |
| techniques | list[str] | ✅ | ATT&CK 기법 ID |
| sigma_rule | str | ✅ | Sigma 룰 원문 |
| siem_query | str | 선택 | 연결된 SIEM 쿼리로 변환한 결과 |
| syntax_ok | bool | ✅ | 문법 검사 통과 여부 |
| backtest | Backtest | 선택 | 아래 Backtest. 아직 안 돌렸으면 `null` |
| status | enum | ✅ | `draft`, `approved`, `rejected`, `deployed` |
| reviewer | str | 선택 | 사람 검토자 |
| needs_human | bool | ✅ | 사람 확인이 필요하면 `true`. LLM 출력 실패 처리는 `docs/llm-policy.md` 4항 |
| human_reason | str | 선택 | `needs_human`이 `true`일 때 이유 |
| created_at | int | ✅ | |

**Backtest**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| window_start_at | int | ✅ | 시간 범위 시작 |
| window_end_at | int | ✅ | 시간 범위 끝 |
| attack_hits | int | ✅ | 공격 구간에서 잡은 건수 |
| benign_hits | int | ✅ | 정상 구간 오탐 건수 |

## C19 · VectorDoc

Vector DB에 넣는 문서 한 건. 임베딩할 문장과 원본 연결 정보.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| doc_id | str | ✅ | `doc_` 접두어 |
| collection | 등록형 | ✅ | 기본 `closed_tickets`, `closed_incidents`, `cases`, `assets`, `alerts_summary`, `events_rare` |
| text | str | ✅ | 템플릿으로 만든 문장 |
| source_kind | enum | ✅ | 원본 객체 종류: `ticket`, `incident`, `case`, `asset`, `alert`, `event` |
| source_id | str | ✅ | 원본 객체 ID |
| keywords | list[str] | ✅ | 정확히 일치해야 하는 값(IP, 해시, 호스트명). 키워드 검색용 |
| created_at | int | ✅ | |
| expires_at | int | 선택 | `events_rare`처럼 보관 기간이 짧은 것 |

규칙: `closed_tickets`, `closed_incidents`, `cases` 컬렉션에는 판정이 끝난 원본만 넣는다.

---

## 공통 객체

**Entity**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| type | 등록형 | ✅ | 기본 `ip`, `host`, `user` |
| value | str | ✅ | |

**Evidence**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| ref_type | 등록형 | ✅ | 기본 `alert`, `event`, `raw`, `ticket`. 객체마다 쓸 수 있는 값이 다르면 그 객체 표에 적는다. 새 값을 등록하는 플러그인은 그 ID가 실제로 있는지 확인하는 함수도 함께 등록한다 |
| ref_id | str | ✅ | 실제로 존재해야 한다. 코드로 확인한다 |
| note | str | ✅ | 이 근거가 무엇을 보여 주는지 한 줄 |

## 계약 생성 구현 (#5)

이 절은 위 "계약 Schema"의 생성 방법을 구체화한다. C1~C20 및 보조 객체를
문서와 수동 대조했으며, 테스트에서 이 Markdown 문서를 파싱하지 않는다.
계약의 코드 원본은 `contracts/`만 유지한다. 이 문서의 상태는 사람 검토 전까지 초안이다.

| 항목 | 구현 |
|---|---|
| Schema 파일 | `contracts/<snake_case>.schema.json`, 객체 하나에 파일 하나 (총 29개) |
| Python 모델 | `src/soc/contracts/generated/*_schema.py`, 공개 진입점 `soc.contracts` |
| TypeScript 타입 | `frontend/src/contracts/generated/*.ts`, 공개 진입점 `frontend/src/contracts/index.ts` |
| 두 언어 생성 | `uv run python scripts/generate_contracts.py` |
| 생성 결과 검사 | `uv run python scripts/generate_contracts.py --check` |
| 계약 타입 검사 | `pnpm --dir tools/contracts typecheck` |
| 계약 전체 테스트 | `uv run pytest tests/contracts` |

Python 3.12 이상, Node 22 이상과 pnpm 11.9.0을 사용한다. CI는 Node 22로 검증한다.
생성 도구용 Node 패키지는 `tools/contracts/`에 두며, F0 화면 앱 설치·빌드와 독립적이다.
처음에는 저장소 루트에서 다음 명령으로 잠금 파일의 의존성을 설치한다.

```bash
uv sync --locked
pnpm --dir tools/contracts install --frozen-lockfile
uv run python scripts/generate_contracts.py
```

생성기는 임시 디렉터리에서 두 언어를 모두 만든 다음 결과를 갱신한다.
입력 순서와 도구 버전(잠금 파일), 포맷을 고정하고 생성 시각은 넣지 않는다.
`--check`는 기존 파일을 바꾸지 않고 내용 차이, 누락, 추가 파일을 검사한다.
CI와 테스트가 재생성 결과를 검증한다. 생성 폴더는 생성기가 관리하므로 직접 수정하지 않는다.

### Schema 검증과 생성 타입의 범위

#5에서 승인된 기준에 따라, 위 "필드 사이 조건" 지침을 다음처럼 구체화한다.
표현 가능한 조건을 설명에만 남기지 않고 원본 draft-07 Schema에 정의한다.

- 모든 필드는 `required`이고 선택 필드는 nullable이다. 등록형 값은 열린 문자열이다.
- 고정 enum, 명시된 숫자 범위·목록 최소 길이·문자열 최대 길이·ID 접두어를 검사한다.
- `extensions`는 추가 값을 허용하되 키는 `<조직 또는 플러그인>.<필드>` 형식이다.
- `if`/`then`: 뒤집기 사유, 반려 유형·코멘트, 멤버 종류별 ID, 제외 사유,
  `needs_human` 사유, AgentStep의 작업 종류별 필드·주체 ID, 알럿 별칭 표 조건,
  C17의 `is_anomaly`가 `false`일 때 `severity_id`가 0인 조건.
- `anyOf`: C3·C5의 출발지·목적지·호스트 중 하나, C18의 헌팅·Case 근거 중 하나.

생성 도구가 객체 수준 조건을 두 언어에 동일하게 옮기지 못하므로, 생성기는
원본에서 루트 `allOf` 조건 목록과 설명만 제외한 임시 입력을 만든다.
필드 구조, nullable 참조, enum, 필드 수준 제약은 유지한다. 이 임시 입력은 별도 원본이 아니다.
**생성된 Pydantic 모델이나 TypeScript 타입만으로 모든 Schema 조건을 검증했다고 간주하면 안 된다.**
TypeScript는 런타임 검증기가 아니며, Pydantic도 루트 조건을 대신 검사하지 않는다.
박스에서 입력을 받아들일 때는 원본 Schema 검증 후 생성 모델을 사용해야 한다.
`jsonschema.Draft7Validator`에 로컬 `$id`별 `referencing.Registry`를 제공하는 사용 예는
`tests/contracts/test_schemas.py`의 `validator()`에 있다. 네트워크 Schema 참조는 사용하지 않는다.

후속 박스에서 구현할 비즈니스 검증은 K55의 미완료 부분으로 남긴다.
원문 해시 대조(2), 별칭 적용·변환 실패 처리(4), 시점별 자산 매칭(5),
중복 집계(6), 컬렉션별 원본 종결 여부(8), 우선순위·상태 전이(9·10),
근거 ID 실재 여부·등록형 값의 등록 여부·LLM 실패 처리(관련 박스),
조사 단계 순번(12), 뒤집기 여부 계산(16), 실제 묶음·심각도 계산(17·18),
타임라인 정렬(19), 검토 회차·재반려 처리(21), 승인 후 Case 생성(22),
룰 검사·백테스트·배포 승인(24)이 해당한다.
