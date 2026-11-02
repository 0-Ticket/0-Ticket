# 데이터 계약

박스끼리 주고받는 데이터의 필드명, 타입, 필수 여부를 고정한다. 박스를 따로 만들어도 서로 맞물리게 하기 위한 문서다.

> **상태: 초안.** v1 아키텍처의 박스가 주고받는 객체를 정의했다. 공통 기반(구현 순서 0단계) PR에서 사람이 검토해 "확정"으로 바꾼다. 확정 후에는 아래 "바꾸는 절차"를 거쳐야만 바꿀 수 있다.

> **v2 불일치 (아키텍처 v2, #33).** 아래 필드 중 L1 시연 계약 이슈(#37)에서 다룬 항목은 본문 계약에 반영했다. 나머지는 v1 흐름 기준으로, 후속 계약 변경 때 "바꾸는 절차"를 따른다. 그전까지 필드와 enum을 말없이 바꾸지 않는다.
>
> - C6의 `handling_type`, `awaiting_human` 및 `awaiting_human_at`, C9 HumanReview, C7 `needs_human`은 발표 후 정리 대상으로 유지한다. v2 경로에서 사람 검토나 라우팅에 사용하지 않는다.
> - C10 Incident: `created_by`의 `correlation`, IncidentMember `source`(`l1`, `human_l1`, `l3`), `member_type`의 `hunt`, `rule`은 폐기된 Correlation(17) 기준
> - C10: L2 재실행이 한도(D-039)에 걸려 멈췄다는 표시가 없다. `review_state`·`review_round`와 C15 반려는 v2에서도 유지한다(D-039). v3: 재분석 한도 멈춤·분석 실패 멈춤·검토 중 새 정보 표시는 #186에서 C10 계약 필드로 추가해 해소한다(`docs/milestone-demo.md` 이슈 사이 규칙 9)
> - C17 HuntFinding: v2에서 헌팅 결과는 Ticket(C6)으로 L2에 들어간다
> - C18 RuleProposal: `hunt_id`·`case_id` 대신 Incident·Artifact에서 나온다. 별도 승인 `status` 대신 21의 승인에 포함된다
> - C19 VectorDoc: 기본 컬렉션 중 `closed_incidents`, `assets`, `alerts_summary`, `events_rare`와 `source_kind`의 `incident`, `asset`, `alert`, `event`는 v2에서 VDB에 넣지 않는다
> - C11 IncidentArtifact·C10: L2 "증거 수집 실패" 표시(D-034)가 없다

> **v3 (#182).** D-034 폐기로 C11·C10의 "증거 수집 실패" 항목은 대상이 아니다. C14, C22, C6 `specialist`, C23 `evidence_request_failure`는 현재 코드에 남아 있고(#185에서 코드 제거, API 응답 모양 유지) 새 작업에서는 쓰지 않는다. C6 전이 설명의 "L3 풀"은 D-036, "박스 25의 L2 입구"와 C10의 "엔티티 분기(25)의 결과"는 D-044로 대체된다. C1·C2의 `direct` 설명은 D-042로 폐기된다. 세부 계약 수정은 #186·#188에서 한다.

## 공통 규칙

- 필드명은 `snake_case`
- 시간은 UTC epoch 밀리초 정수(`int`). 필드명은 `time`, `*_at`, `*_seen`, 그리고 유효 기간용 `valid_from`, `valid_to`
- ID는 접두어가 붙은 문자열: `raw_`, `src_`, `al_`, `ev_`, `tk_`, `in_`, `cs_`, `ht_`, `rp_`, `doc_`, `br_`, `rq_`, `ld_`
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

코드에서 계약 객체를 검증할 때는 공개 함수 `soc.contracts.validate_contract(name, data)`만 쓴다.
생성 모델을 직접 만드는 것을 계약 검증으로 삼지 않는다. `name`은 Schema의 `title`과 같은
객체명(예: `HuntFinding`, `Verdict`)이고, `data`는 JSON을 해석한 객체다.
원본 draft-07 Schema 및 파일 간 `$ref`를 먼저 검증하고, 통과하면 생성 Pydantic 모델을 반환한다.

실패는 `ContractValidationError`로 통일한다. 예외의 `path`는 필드 경로(`/severity_id` 등),
`rule`은 실패한 규칙명(`const`, `required`, `int_type` 등)이다. 루트 경로는 `/`로 표시한다.
Schema에 선언되지 않은 동적 키는 `*`로 가린다. 입력값과 원본 검증 예외는 포함하지 않는다.
계약별 검증기는 모듈 로드 시 한 번만 만들어 재사용한다.

wheel에는 루트 `contracts/`를 `soc/contracts/schemas/` 리소스로 포함한다.
설치된 패키지는 해당 리소스를 읽고, 편집 가능 설치는 모듈 위치를 기준으로 원본을 찾는다.
현재 작업 폴더에 의존하지 않으며, 설치용 Schema 사본을 별도 원본으로 관리하지 않는다.

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
| C1 | RawRecord | 1 → 2, 3 (박스 1·2는 외부. `direct` 어댑터의 재생 입력. 현재 코드에 남아 있음(#183에서 제거) / 새 작업에서는 쓰지 않음(D-042)) |
| C2 | SiemAlert | 3 → 4, 6, 7 |
| C20 | AliasTable (설정) | 사람 → 4 |
| C3 | NormalizedAlert | 4 → 5 |
| C12 | NormalizeFailure | 4 → 사람 확인 |
| C13 | EventRecord | 4, 5 → 7, 23 |
| C4 | AssetInfo, UserInfo | 5 (룩업 표) |
| C5 | AlertRecord | 5, 6 → 25, 11, 23, 27 |
| C6 | Ticket | 25, 11, 23, 10 → 26, 11, 25(L2 입구), 18, 19, 27 |
| C7 | Verdict | 11 → 10, 27 |
| C8 | AgentStep | 11, 13, 14, 19, 23, 24 → 12 |
| C9 | HumanReview | (v1 객체. v2에서 제거 예정. 위 "v2 불일치") |
| C10 | Incident | 25, 18, 19 → 19 |
| C11 | IncidentArtifact | 19 → 20, 21 |
| C14 | SpecialistFinding | 13, 14 → 11, 19 (현재 코드에 남아 있음(#185에서 제거) / 새 작업에서는 쓰지 않음(D-034)) |
| C15 | L2Review | 21 → 22 |
| C16 | Case | 22 → 8, 23 |
| C17 | HuntFinding | 23 (v2에서 헌팅 결과는 C6으로 L2에 들어감. 위 "v2 불일치") |
| C18 | RuleProposal | 24 → 20, 21, 3 (사람 승인 후) |
| C19 | VectorDoc | 10, 22 → 8 |
| C21 | BranchResult | 25 → 10, 11, 18 |
| C22 | EvidenceRequest | 10, 11, 19 → 26 → 14, 15, 5 → 26 → 11, 19 |
| C23 | L1DecisionRecord | 11 → 27 |

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

SIEM 어댑터가 낸 알럿 또는 이벤트. 시나리오마다 필드명이 달라도 그대로 둔다. `source_record_id`는 저장된 불변 원본 행을 식별하며, 정규화 결과가 이 값을 FK로 보존한다. `raw_ids`는 별도 원본 로그(C1) 참조로 유지한다. SIEM 없이 받을 때(개발·테스트·데모용 데이터셋 재생)는 `direct` 어댑터가 C1을 이 형식으로 바꾼다(현재 코드에 남아 있음(#183에서 제거) / 새 작업에서는 쓰지 않음(D-042)).

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| kind | enum | ✅ | `alert`(박스 4가 C3로 바꿈), `event`(C13으로 바꿈) |
| source_record_id | str | ✅ | `src_` 접두어. 저장되는 C2 원본 행의 고유 ID. 코어가 `src_` + sha256(정규화된 JSON: `kind`, `scenario`, `raw_ids`, `fields`만, 키 정렬, 공백 없음, UTF-8) 16진수 전체로 부여한다(`docs/architecture.md` 박스 3). 어댑터는 이 필드를 채우지 않는다 |
| scenario | str | ✅ | 탐지 시나리오 또는 이벤트 종류 이름. 정규화 시 C20 별칭 표를 고르는 키. `direct` 어댑터는 설정에서 정한 이름을 쓴다(현재 코드에 남아 있음(#183에서 제거) / 새 작업에서는 쓰지 않음(D-042)) |
| raw_ids | list[str] | ✅ | 근거가 된 RawRecord ID |
| fields | dict | ✅ | SIEM 알럿 JSON 원본 그대로. ES 계열 어댑터(`elastic`)는 `_source`의 점 표기 키(`"a.b": 1`)를 중첩 객체(`{"a": {"b": 1}}`)로 펼쳐 넣는다. ES 안에서 두 표기는 같은 뜻이고, 값은 바꾸지 않는다 |

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
| parse | object | 선택 | 원본이 텍스트 한 줄일 때 필드로 나누는 규칙. `field`(str, 나눌 원본 필드)와 `pattern`(str, 이름 붙은 그룹이 있는 정규식) 둘 다 필수. 그룹 값은 `<field>.<그룹 이름>`으로 `fields`에서 가리킨다. 예: `message.client_ip` |

규칙
- `fields`에 없는 원본 필드는 `unmapped`로 간다. 쓴 값만 빼고 원래 중첩 구조를 그대로 둔다. `extensions_map`으로 옮긴 값과 `parse`로 나눈 원본 필드는 `unmapped`에 넣지 않고, 나눈 그룹 중 쓰지 않은 값은 `unmapped`의 `<field>` 아래에 남는다.
- 빈 문자열과 없는 값은 "없음"이다. 정수 필드는 정수나 숫자 문자열, 문자열 필드는 문자열이나 정수, 목록 필드는 목록이나 문자열 하나를 받는다.
- 선택 정수 필드(C3 `src_port`·`dst_port`·`http_status`, C13 `http_status`·`http_bytes`)의 값이 정수로 바뀌지 않으면 그 필드만 `null`로 두고 나머지를 계속 정규화한다. C13 `http_bytes`는 0 이상만 유효하고 음수도 같은 방식으로 처리한다. 0 같은 다른 값으로 바꾸지 않는다. 원본 값은 쓰지 않은 것으로 보아 `unmapped`의 원래 자리에 원래 모양으로 남는다. 다음 후보는 찾지 않는다(앞에서 처음 값이 있는 후보만 쓴다).
- 시간대가 없는 시간은 추측하지 않고 실패(`bad_value`)로 둔다.
- `parse` 정규식은 공격자가 만든 문자열에 적용되므로 역추적이 폭발하지 않게 쓴다(중첩 반복 금지). 대상 값이 설정 `normalize.max_parse_length`보다 길면 정규식을 적용하지 않고 C12(`bad_value`)를 만든다. 정규식이 맞지 않으면 필수 필드를 못 찾은 것으로 본다(`missing_required`).
- C2의 `scenario`에 맞는 표가 없거나 표의 `kind`가 C2와 다르면 C12(`unknown_scenario`), 필수 필드를 못 찾으면 C12(`missing_required`), 시간·심각도 변환이나 선택 정수 필드가 아닌 필드의 형 변환에 실패하면 C12(`bad_value`)를 만든다.
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
| src_ip | str | 선택 | 출발지 IP | `evidences[0].src_endpoint.ip` |
| src_port | int | 선택 | | `evidences[0].src_endpoint.port` |
| dst_ip | str | 선택 | 목적지 IP | `evidences[0].dst_endpoint.ip` |
| dst_port | int | 선택 | | `evidences[0].dst_endpoint.port` |
| host | str | 선택 | 대상 호스트명 | `device.hostname`, `evidences[0].device.hostname` |
| user | str | 선택 | 관련 계정 | `evidences[0].user.name` |
| http_url | str | 선택 | 웹 알럿의 요청 URL (원문, 데이터로만 취급) | `evidences[0].http_request.url.url_string` |
| http_status | int | 선택 | 웹 알럿의 응답 코드 | `evidences[0].http_response.code` |
| techniques | list[str] | ✅ | ATT&CK 기법 ID. 예: `T1190`. 원본에 없으면 C20의 `default_techniques`, 그것도 없으면 `[]` | `finding_info.attacks[].technique.uid` |
| raw_ids | list[str] | ✅ | C2에서 그대로 | |
| unmapped | dict | ✅ | 별칭 표에 없는 원본 필드 | `unmapped` |
| extensions | dict | ✅ | 조직·플러그인 추가 필드. 없으면 `{}` | |

규칙: `src_ip`, `dst_ip`, `host` 중 하나 이상은 있어야 한다. 필수 필드가 비면 이 객체를 만들지 않고 C12 NormalizeFailure를 만든다.

OCSF 경로는 OCSF 1.9.0 Detection Finding, 프로필 없음 기준이다.

## C12 · NormalizeFailure

정규화하지 못한 알럿 또는 이벤트. 버리지 않고 모아서 사람이 별칭 표를 고칠 근거로 쓴다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| scenario | str | ✅ | C2에서 그대로 |
| raw_ids | list[str] | ✅ | C2에서 그대로 |
| reason | enum | ✅ | `unknown_scenario`(별칭 표 없음), `missing_required`(필수 필드 없음), `bad_value`(시간·심각도 변환 실패, 선택 정수 필드가 아닌 필드의 형 변환 실패, `parse` 대상 길이 초과) |
| missing_fields | list[str] | ✅ | 비어 있던 C3·C13 필수 필드 이름. 없으면 `[]` |
| detail | str | 선택 | 실패 내용 한 줄 |
| failed_at | int | ✅ | |

## C13 · EventRecord

정규화와 룩업을 거친 info 수준 이벤트. Event 저장소의 한 행. 알럿보다 양이 훨씬 많다. `source_record_id`로 불변 C2 원본 행을 가리킨다.

| 필드 | 타입 | 필수 | 설명 | OCSF 경로 (참고) |
|---|---|---|---|---|
| event_id | str | ✅ | `ev_` 접두어 | |
| source_record_id | str | ✅ | `src_` 접두어. C2 원본 Event 행을 가리키는 FK | |
| class_uid | int | ✅ | OCSF 활동 클래스 ID (예: HTTP Activity, Authentication) | `class_uid` |
| time | int | ✅ | | `time` |
| activity | str | ✅ | 활동 이름. 예: `http_request`, `logon`, `api_call` | `activity_name` |
| src_ip | str | 선택 | | `src_endpoint.ip` |
| dst_ip | str | 선택 | | `dst_endpoint.ip` |
| host | str | 선택 | | `device.hostname` |
| user | str | 선택 | | `actor.user.name` |
| http_url | str | 선택 | 원문, 데이터로만 취급 | `http_request.url.url_string` |
| http_status | int | 선택 | | `http_response.code` |
| http_bytes | int | 선택 | HTTP 응답 본문 크기(헤더 제외), 바이트 단위. 음수는 허용하지 않으며, 크기를 알 수 없거나 HTTP 응답이 아니면 `null`; 본문이 비어 있으면 `0` | `http_response.body_length` |
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
| shared | bool | ✅ | 프록시·DNS·도메인 컨트롤러 같은 공용 자산이면 `true`. 엔티티 분기(25)에서 공용 엔티티로 빼는 기준이다 |
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

C3에 룩업 결과와 저장 정보를 더한 것. Alert 저장소의 한 행. C2 원본은 별도 불변 행으로 저장하고 `source_record_id`로 연결한다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| alert_id | str | ✅ | `al_` 접두어 |
| source_record_id | str | ✅ | `src_` 접두어. 정규화 전 C2 원본 Alert 행을 가리키는 FK |
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
| origin | enum | ✅ | `l1_escalated`(L1 승격), `l3_escalated`(L3 승격), `scenario`(시나리오) (D-038) |
| status | enum | ✅ | `new`, `triaging`, `awaiting_human`, `on_hold`, `closed_benign`, `closed_fp`, `escalated`, `l2_escalated` |
| handling_type | 등록형 | ✅ | 기본 `web_attack`, `scan`, `cloud`, `other` |
| specialist | 등록형 | ✅ | 전문 에이전트 이름. 기본 `none`, `web`, `cloud`. 현재 코드에 남아 있음(#185에서 제거) / 새 작업에서는 쓰지 않음(D-034) |
| priority | int | ✅ | `severity_id × 대상 자산 criticality`. 대상 자산은 `dst_asset`, 없으면 `src_asset`, 둘 다 없으면 criticality 1로 계산 |
| alert_ids | list[str] | ✅ | 하나 이상 |
| entities | list[Entity] | ✅ | 공통 객체 Entity. 엔티티 분기(25)가 이 값을 본다 |
| verdict | Verdict | 선택 | 판정 전에는 `null` |
| extensions | dict | ✅ | 조직·플러그인 추가 필드. 외부 티켓 시스템 ID 등. 없으면 `{}` |
| created_at | int | ✅ | |
| updated_at | int | ✅ | |
| awaiting_human_at | int | 선택 | `awaiting_human` 상태에 진입한 UTC epoch 밀리초. 아직 진입하지 않았다면 `null`. 상태를 벗어나도 진입 시각을 유지한다 |

v2 상태 전이: `new → triaging → on_hold | closed_benign | closed_fp | l2_escalated`. `on_hold`는 L1 보류 결과로 L3 풀에 전달되고, `l2_escalated`는 박스 25의 L2 입구로 간다. `awaiting_human`과 `escalated` 값은 기존 데이터 호환을 위해 계약에 남기며 v2 흐름에서는 새로 만들지 않는다. `handling_type`과 `awaiting_human_at`도 발표 후 정리 전까지 유지한다.

`awaiting_human_at`은 공통 규칙에 따라 필드 자체는 필수이고 값만 nullable이다.
미진입 시 `null`, `awaiting_human` 진입 시 해당 시각 `t1`, 상태 종료 후에도 `t1`을 유지한다.
현재 상태 전이에는 재진입 경로가 없으므로 재진입 규칙은 정의하지 않는다.
`created_at`이나 `updated_at`을 대체 값으로 사용하지 않는다.

#12는 필드 계약·검증·직렬화 보존을 정의한다. 실제 상태 전이 시각 기록과 유지 로직은
박스 10의 후속 구현 및 K12 검증 대상이다. 검토 완료 시각이나 소요 시간 계산은 추가하지 않는다.

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
| subject_type | enum | ✅ | `alert`, `ticket`, `incident`, `hunt`. 티켓 생성 전 L1 단계는 `alert`에 연결 |
| subject_id | str | ✅ | 해당 객체 ID (`al_`, `tk_`, `in_`, `ht_`) |
| step | int | ✅ | 같은 작업 안에서 1부터 증가 |
| agent | str | ✅ | 예: `l1`, `web`, `cloud`, `l2`, `l3` |
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

사람의 L1 판정 검토 결과(v1). v2에서는 L1 판정을 사람이 뒤집지 않지만, 발표 후 정리 전까지 계약 호환을 위해 유지한다(위 "v2 불일치").

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| ticket_id | str | ✅ | |
| reviewer | str | ✅ | |
| decision | enum | ✅ | `tp`, `fp` |
| overturned | bool | ✅ | 에이전트 판정과 다르면 `true` |
| reason | str | 선택 | `overturned`가 `true`면 필수 |
| created_at | int | ✅ | |

## C10 · Incident

같은 엔티티로 엮인 Ticket 묶음. v2에서는 엔티티 분기(25)의 결과로 만들어지거나 갱신된다(박스 18). 묶음 관련 필드는 v1 Correlation 기준이다(위 "v2 불일치").

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
| review_state | enum | ✅ | L2 검토 흐름 상태. `analyzing`, `awaiting_review`, `approved`, `human_handling`. 아래 "L2 검토 흐름" |
| review_round | int | 선택 | 지금 열려 있는 L2 검토 기회의 회차. 1부터. `review_state`가 `awaiting_review`일 때만 값이 있고, 나머지 상태에서는 `null` |
| extensions | dict | ✅ | 조직·플러그인 추가 필드. 없으면 `{}` |

**L2 검토 흐름 (#21)**

`status`와 `review_state`는 서로 다른 값이다. `status`는 Incident 생명주기(열림 → 조사 → 종결·Case 전환)이고,
`review_state`는 그 안에서 L2 분석 → 사람 검토가 몇 번 오가는지를 나타낸다. 한쪽 값으로 다른 쪽을 대신하지 않는다.

| review_state | review_round | 뜻 |
|---|---|---|
| `analyzing` | `null` | 아직 검토 기회가 열리지 않았다. L2가 분석하거나 반려 후 재분석하는 중 |
| `awaiting_review` | 1 이상 | 지금 검토 기회가 열려 있다. 사람이 승인하거나 반려할 수 있다 |
| `approved` | `null` | L2 검토에서 승인했다. Case 생성은 박스 22가 한다 |
| `human_handling` | `null` | 두 번 반려되어 L2 자동 재검토를 끝냈다. 사람이 직접 처리한다 |

```
analyzing ──새 C11 검토 대상 준비──▶ awaiting_review (round n)
awaiting_review ──approve──▶ approved
awaiting_review ──reject (첫 번째 반려)──▶ analyzing ──재분석 후 새 검토 대상 준비──▶ awaiting_review (다음 round)
awaiting_review ──reject (두 번째 반려)──▶ human_handling
```

- 상태를 바꾸고 회차를 부여하는 것은 코어(박스 21)다. 화면과 검토 채널은 계산하지 않는다.
- 첫 검토 기회는 round 1이다. 새 기회가 열릴 때마다 코어가 다음 회차를 부여하며, 같은 Incident에서 회차는 단조 증가한다.
- 검토 기회 하나에는 검토(C15)가 하나만 남는다. 처리된 기회에는 다시 제출할 수 없다.
- `human_handling`은 L2 자동 검토 흐름의 끝일 뿐, Incident 생명주기의 끝이 아니다. 그 뒤 Case로 넘길지 종결할지는 `status`와 박스 22가 정한다. 이 상태에서는 새 L2 검토 기회를 열지 않는다. v3 데모: 시스템 안 처리 경로 없음(규칙 7).
- 반려 후 `analyzing`으로 돌아가 재분석하는 동안 `status`는 `investigating`을 유지한다. 이 흐름은 `status` 값이나 전이를 바꾸지 않는다.
- 화면은 검토 건수, C15 `round`, C11 `generated_at`, 그 밖의 시각으로 새 검토 기회를 추론하지 않는다. `review_state`와 `review_round`만 본다.

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

> 현재 코드에 남아 있음(#185에서 제거) / 새 작업에서는 쓰지 않음(D-034).

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
| round | int | ✅ | 이 검토가 처리한 검토 기회의 회차. 1부터. 코어가 그 기회의 C10 `review_round`를 기록한다. 요청 값이 아니다 |
| created_at | int | ✅ | |

검토와 관련된 값은 다섯 가지이고 서로 다르다.

| 값 | 위치 | 뜻 | 누가 정하나 |
|---|---|---|---|
| `status` | C10 | Incident 생명주기 | 코어(박스 18, 22) |
| `review_state` | C10 | L2 검토 흐름 상태 | 코어(박스 21) |
| `review_round` | C10 | 지금 열려 있는 검토 기회의 회차 | 코어(박스 21) |
| `expected_review_round` | 검토 요청 본문 | 요청이 답하는 검토 기회. 그 기회가 아직 열려 있는지 확인하는 사전 조건이며 계약 객체에 저장하지 않는다(`docs/api-contracts.md`) | 화면이 받은 `review_round`를 그대로 보냄 |
| `round` | C15 | 이 검토가 실제로 처리한 회차 | 코어(박스 21)가 기록 |

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
| incident_id | str | 선택 | Incident로 묶였으면 그 ID (v1 Correlation 기준) |
| rule_candidate | bool | ✅ | 반복 가능한 패턴이라 룰 제안으로 넘길지 |
| needs_human | bool | ✅ | 사람 확인이 필요하면 `true`. LLM 출력 실패 처리는 `docs/llm-policy.md` 4항. v3: 이슈 사이 규칙 11(D-046)로 대체. 본문 수정은 #184 |
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

## C21 · BranchResult

박스 25가 알럿 또는 Ticket에 대해 선택한 경로와 근거다. 분기 규칙은 코드로 적용하며 이 객체는 결과를 기록한다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| branch_id | str | ✅ | `br_` 접두어 |
| subject_type | enum | ✅ | `alert`, `ticket` |
| subject_id | str | ✅ | 대상 `al_` 또는 `tk_` ID |
| path | enum | ✅ | `deduplicated`, `excluded_shared_entity`, `scenario_ticket`, `l1_entity_lookup`, `existing_incident`, `new_incident` |
| reason | object | ✅ | 분기 근거. `rule_id`와 `entity`를 포함한다 |
| created_at | int | ✅ | |

`reason` 객체의 `rule_id`는 선택 문자열, `entity`는 선택 Entity이며 둘 다 없을 수는 없다. 분기 규칙 ID와 분기에 사용한 엔티티를 보존한다.

## C22 · EvidenceRequest

> 현재 코드에 남아 있음(#185에서 제거) / 새 작업에서는 쓰지 않음(D-034).

박스 26 증거 요청 큐의 한 항목. 재시도 횟수는 최초 요청 뒤 다시 시도한 횟수다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| request_id | str | ✅ | `rq_` 접두어 |
| requester_type | enum | ✅ | `ticket`, `incident`, `alert`. `alert`는 티켓 생성 전 L1 엔티티 정보 조회(11)의 요청이다 |
| requester_id | str | ✅ | 요청을 만든 Ticket(`tk_`), Incident(`in_`) 또는 Alert(`al_`) ID. `requester_type`과 접두어가 맞아야 한다 |
| request_type | enum | ✅ | `specialist_agent`, `siem_mcp`, `lookup`. `requester_type`이 `alert`이면 `siem_mcp`, `lookup`만 쓴다 |
| domain | str | 선택 | 전문가 도메인. `specialist_agent`이면 필요하며 기본 제공 도메인은 `web`, `cloud`; 그 외 요청은 `null` |
| params | object | ✅ | 무엇을 조회할지. `request_type`별 모양은 아래 표. 표에 없는 키는 받지 않는다 |
| retry_count | int | ✅ | 0 이상. 최초 요청은 0 |
| status | enum | ✅ | `pending`, `in_progress`, `completed`, `failed` |
| failure_reason | str | 선택 | 실패 상태일 때 사유, 그 외에는 `null` |
| result | object | 선택 | 요청 결과. `status`가 `completed`일 때만 값이 있고, 그 외에는 `null`. `request_type`별 모양은 아래 표 |
| created_at | int | ✅ | |
| updated_at | int | ✅ | |

**`params`** (모든 키 필수)

| request_type | 키 | 설명 |
|---|---|---|
| `specialist_agent` | `question` (str) | 전문가에게 물을 내용. 1자 이상 |
| `siem_mcp` | `entity` (Entity), `kind` (enum `alert`, `event`), `start_at` (int), `end_at` (int), `limit` (int) | SIEM MCP 공통 조회 조건(박스 15 `SiemQuery`와 같은 모양). 시간 범위는 양 끝 포함. `limit`은 1 이상 |
| `lookup` | `entity` (Entity), `at` (int, 선택) | 조회할 엔티티와 매칭 시점. 자산·계정 표의 유효 기간(`valid_from`, `valid_to`)을 이 시점으로 맞춘다. `null`이면 현재 시각 |

**`result`** (`status`가 `completed`일 때, 모든 키 필수)

| request_type | 키 | 설명 |
|---|---|---|
| `specialist_agent` | `finding` (C14) | 전문가 Agent의 분석 결과 |
| `siem_mcp` | `records` (list[C2]) | SIEM MCP가 돌려준 C2. 찾은 것이 없으면 `[]` |
| `lookup` | `asset` (C4 AssetInfo, 선택), `user` (C4 UserInfo, 선택) | Lookup(5)이 고른 자산·계정 한 건씩. 찾은 것이 없으면 둘 다 `null`이고 그래도 `completed`다 |

`requester_type`이 `alert`이면 전문가를 부르지 않는다. 전문가 결과 C14는 Ticket에 연결되기 때문이다.

코어 검증: 박스 26 큐가 요청 저장·결과 저장 때 수행한다(draft-07 Schema로 표현할 수 없는 조건).

- `siem_mcp`의 `params.end_at`은 `params.start_at` 이상이다.
- `siem_mcp`의 `params.limit`은 설정 `mcp.max_query_limit` 이하다.
- `specialist_agent` 결과의 `result.finding.ticket_id`는 `requester_id`와 같다.

## C23 · L1DecisionRecord

박스 11이 남기고 박스 27이 읽는 Alert·Ticket 단위의 승격·보류·판정 결과.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| decision_id | str | ✅ | `ld_` 접두어 |
| subject_type | enum | ✅ | `alert`, `ticket` |
| subject_id | str | ✅ | 대상 Alert(`al_`) 또는 Ticket(`tk_`) ID |
| decision | enum | ✅ | Alert: `l1_escalated`, `held`; Ticket: `held`, `closed_fp`, `l2_escalated` |
| confidence | float | 선택 | 0.0~1.0. 평가할 수 없는 경우 `null` |
| reason | enum | 선택 | `below_threshold`, `llm_failure`, `evidence_request_failure`; 보류가 아니면 `null` |
| created_at | int | ✅ | |

보류 결정에는 `reason`이 필요하다. 확신도 임계값은 D-036의 설정 값이며 계약은 고정 임계값을 검사하지 않는다. LLM 실패 처리에 대한 `needs_human` 필드는 C7에서 유지한다.

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

이 절은 위 "계약 Schema"의 생성 방법을 구체화한다. C1~C23 및 보조 객체를
문서와 수동 대조했으며, 테스트에서 이 Markdown 문서를 파싱하지 않는다.
계약의 코드 원본은 `contracts/`만 유지한다. 이 문서의 상태는 사람 검토 전까지 초안이다.

| 항목 | 구현 |
|---|---|
| Schema 파일 | `contracts/<snake_case>.schema.json`, 객체 하나에 파일 하나 (총 32개) |
| Python 모델 | `src/soc/contracts/generated/*_schema.py`, 공개 진입점 `soc.contracts` |
| TypeScript 타입 | `frontend/src/contracts/generated/*.ts`, 공개 진입점 `frontend/src/contracts/index.ts` |
| 두 언어 생성 | `uv run python scripts/generate_contracts.py` |
| 생성 결과 검사 | `uv run python scripts/generate_contracts.py --check` |
| 계약 타입 검사 | `pnpm --dir tools/contracts typecheck` |
| 계약 전체 테스트 | `uv run pytest tests/contracts` |

Python 3.12 이상, Node 24와 pnpm 11.9.0을 사용한다. F0(#8)에서 프론트와 계약 생성 CI를 Node 24로 통일했다.
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
  C10의 `review_state`와 `review_round` 짝(`awaiting_review`일 때만 1 이상 정수),
  C22의 요청자별 ID 접두어·요청 종류, 요청 종류별 `params`·`result` 모양, 완료 상태일 때만 `result`,
  `needs_human` 사유, AgentStep의 작업 종류별 필드·주체 ID, 알럿 별칭 표 조건,
  C17의 `is_anomaly`가 `false`일 때 `severity_id`가 0인 조건.
- `anyOf`: C3·C5의 출발지·목적지·호스트 중 하나, C18의 헌팅·Case 근거 중 하나.

생성 도구가 객체 수준 조건을 두 언어에 동일하게 옮기지 못하므로, 생성기는
원본에서 루트 `allOf` 조건 목록과 설명만 제외한 임시 입력을 만든다.
필드 구조, nullable 참조, enum, 필드 수준 제약은 유지한다. 이 임시 입력은 별도 원본이 아니다.
**생성된 Pydantic 모델이나 TypeScript 타입만으로 모든 Schema 조건을 검증했다고 간주하면 안 된다.**
TypeScript는 런타임 검증기가 아니며, Pydantic도 루트 조건을 대신 검사하지 않는다.
박스에서 입력을 받아들일 때는 `soc.contracts.validate_contract()`를 사용한다.
이 함수가 원본 Schema 검증과 생성 모델 변환을 순서대로 수행한다. `jsonschema`는 런타임 의존성이다.
로컬 리소스 레지스트리로 `$ref`를 해석하며 네트워크 Schema 참조는 사용하지 않는다.

후속 박스에서 구현할 비즈니스 검증은 K55의 미완료 부분으로 남긴다.
원문 해시 대조(2), 증거 요청의 시간 범위·조회 한도·결과 Ticket 일치(26), 별칭 적용·변환 실패 처리(4), 시점별 자산 매칭(5),
중복 집계(6), 컬렉션별 원본 종결 여부(8), 우선순위·상태 전이(10),
근거 ID 실재 여부·등록형 값의 등록 여부·LLM 실패 처리(관련 박스),
조사 단계 순번(12), 뒤집기 여부 계산(v1 16), 실제 묶음·심각도 계산(25·18),
타임라인 정렬(19), 검토 흐름 상태 전이·회차 부여·같은 기회 중복 제출 거부(21), 승인 후 Case 생성(22),
룰 검사·백테스트·배포 승인(24)이 해당한다.
