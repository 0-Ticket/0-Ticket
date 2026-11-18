---
issue: 340
date: 2026-11-18
owner: uptime-zero
supersedes: []
---

# 이벤트 수집 설정에 OCSF 클래스 번호(class) 추가와 이벤트 클래스 정의

## 목표

수집 대상(`[[ingest.sources]]`)마다 이벤트의 OCSF 클래스 번호를 설정에 적을 수 있게 한다. 사용할 소스(ModSecurity, Suricata, Nginx, GuardDuty, CloudTrail, Prowler)에서 주로 나오는 OCSF 1.9.0 클래스의 공식 정의(optional 속성과 참조 객체까지)를 `ocsf/classes/`에 받아 두어, 다음 이슈에서 이벤트 매핑표를 바로 검증할 수 있게 한다. 정규화와 DB는 바꾸지 않는다.

## 방법

1. **테스트 먼저.** 설정 검사와 스키마 받기의 실패하는 테스트를 먼저 쓴다.
2. **클래스 정의 받기.** `scripts/fetch_ocsf_schema.py`의 `CLASSES`에 `network_activity`(4001), `http_activity`(4002), `dns_activity`(4003), `api_activity`(6003), `authentication`(3002), `compliance_finding`(2003)을 더하고 다시 실행한다.
   - 공식 API(`/api/1.9.0/classes|objects/<이름>?profiles=`)가 주는 정의를 그대로 둔다. 모든 속성(required·recommended·optional)과 설명, `constraints`, 이 클래스들이 참조하는 객체를 `object_type`을 따라 빠짐없이 받는다.
   - 예전에 줄여 둔 `classes/4002.json`, `classes/6003.json`은 공식 정의로 대체한다. `objects.json`에는 새로 참조되는 객체가 더해진다.
   - 스키마 로더가 처리하지 않는 `constraints` 종류(지금 처리: `at_least_one`, `just_one`)가 나오면 스크립트가 실패한다. 그때는 멈추고 로더 확장 여부를 사람과 정한다.
   - `ocsf/SOURCE.md`에 받은 클래스, 날짜, 재생성 명령을 적는다.
3. **설정 `class`.** `[[ingest.sources]]`에 선택 항목 `class`(정수)를 더한다. `ingest/config.py`의 `Source`에 `ocsf_class: int | None = None`을 더한다.
   - `ocsf/classes/<번호>.json`이 있는 번호만 허용한다. 정의 파일 존재 확인은 `soc.normalize.ocsf_schema`에 작은 함수를 두어 쓴다.
   - 2004(Detection Finding)는 알럿 전용이라 이벤트 대상에 쓸 수 없다.
   - `kind = "alert"` 대상에 `class`를 쓰면 설정 오류다(알럿은 2004로 정해져 있다).
   - 정수가 아닌 값(불리언 포함), 정의 파일이 없는 번호는 설정 오류다.
   - 적지 않으면 `None`이고 지금처럼 동작한다. 기존 `local.toml`은 영향이 없다.
4. **기본 설정.** `config/default.toml`의 nginx·apache 대상에 `class = 4002`를 적고, `class`의 뜻과 "정규화에 연결되기 전까지 효과가 없다"는 주석을 단다. 나머지 대상(클라우드 3곳)에는 적지 않는다.

## 바꿀 곳

- `scripts/fetch_ocsf_schema.py`: `CLASSES`에 6개 클래스 추가
- `src/soc/normalize/ocsf/classes/`: `2003.json`, `3002.json`, `4001.json`, `4003.json` 새로 받음, `4002.json`, `6003.json` 공식 정의로 대체
- `src/soc/normalize/ocsf/objects.json`, `ocsf/SOURCE.md`: 참조 객체 추가, 출처 기록
- `src/soc/normalize/ocsf_schema.py`: 클래스 정의 파일이 있는지 확인하는 함수
- `src/soc/ingest/config.py`: `Source.ocsf_class`, `class` 읽기와 검사
- `config/default.toml`: nginx·apache에 `class = 4002`, 설명 주석
- `tests/`: 설정 검사 테스트, 스키마 받기 테스트
- `docs/decisions.md`: D-065, D-061 메모

## 다른 코드와 맞물리는 곳

- 설정 키 `[[ingest.sources]].class`: 새로 더하는 선택 항목이다. 기존 설정은 그대로 동작한다.
- `Source` 데이터클래스: 끝에 기본값이 있는 필드를 더한다. 기존 생성 호출은 바뀌지 않는다.
- `ocsf/classes/4002.json`, `6003.json`: 기존 이벤트 정규화의 검증(`validate_ocsf`)이 읽는다. 공식 정의로 바뀌어도 기존 이벤트 결과가 검증을 통과해야 한다(기존 normalize 테스트로 확인).
- `ocsf/objects.json`: 알럿(0·2004) 검증과 매핑표 검사(`table_check.py`)도 읽는다. 객체가 늘어나도 알럿 결과와 검사 결과는 같아야 한다.
- 수집 설정이 `soc.normalize.ocsf_schema`의 함수를 부른다(정의 파일 존재 확인만, DB·정규화 실행과 무관).
- `mapping.py`, `run.py`, `raw_records`, `events`, `normalize_status`, 계약, 에이전트 도구, API, 화면: 바꾸지 않는다. 설정에 `class`를 적어도 지금은 어디에도 쓰이지 않는다.

## 범위 밖

- 이벤트 매핑표 작성. 다음 이슈에서 `src/soc/normalize/mapping_tables/events/<클래스 번호>.yaml`에 둔다. 알럿 로더는 `mapping_tables/*.yaml`만 읽어 하위 폴더는 영향이 없고, 이벤트 표는 설정이 클래스를 정하므로 `detect`를 두지 않는다. 이벤트용 로더와 검사(클래스 번호 기준)는 그 이슈에서 만든다.
- `normalize` 변경, 이벤트 폴백·마스킹·엔티티 규칙.
- 원본에 클래스·수집 키를 저장하는 일, 정규화 연결, `events` 구조, DB 스키마 변경(스키마 개편 결정 뒤 후속 계획).
- 알럿 구조 변경 협의, SIEM(Filebeat·인덱스) 설정 변경.

## 완료 기준

- [ ] `scripts/fetch_ocsf_schema.py`로 0·2003·2004·3002·4001·4002·4003·6003 클래스와 참조 객체를 공식 1.9.0 정의 그대로 다시 만들 수 있고, `SOURCE.md`에 출처·날짜·재생성 방법이 있다.
- [ ] 받은 클래스 정의에 required·recommended·optional 속성이 모두 있고 설명이 있다.
- [ ] 이벤트 대상의 `class`를 읽고, 정의 파일이 없는 번호·2004·정수 아님·알럿 대상의 `class`를 설정 오류로 막는다. 생략한 설정은 지금처럼 동작한다.
- [ ] `default.toml`의 nginx·apache에 `class = 4002`가 있고 설정 읽기 테스트가 통과한다.
- [ ] 기존 normalize·ingest 테스트(알럿 회귀, 이벤트 4002·6003 검증 포함)가 변경 없이 통과한다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과한다.
- [ ] `docs/decisions.md`에 D-065가 있다.
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록이 있고, 기록에 "설정은 읽히지만 정규화 연결은 후속"과 아래 보류 항목이 적혀 있다.

## 토론으로 정한 것

- 수집 대상의 `kind`는 유지하고, 이벤트의 클래스는 사용자가 설정에 번호로 적는다. 이유: SIEM이 다를 수 있어 분류 기준은 설정이 정하고 코드는 선언을 따른다.
- 층을 셋으로 나눈다. 설정(key → 클래스 번호), 매핑표(ECS 필드 → OCSF 필드, YAML), 클래스 정의(OCSF 공식 정의, JSON). 매핑표는 클래스 정의로 검증한다.
- 클래스 정의는 공식 서버에서 받은 JSON을 그대로 둔다. 사람이 고치지 않는 파일이라 YAML로 바꾸지 않는다(D-061). 처음에 생각한 별도 목록 파일(`event_classes.yaml`)은 `ocsf/classes/`와 겹쳐 만들지 않는다.
- 정의 범위는 사용할 소스에서 주로 나오는 클래스만이다. OCSF에 있으면 정의하고, 소스 쪽 사정으로 정해지지 않은 것은 아래처럼 보류로 적는다. optional 속성까지 모두 받아 둔다.
- `event.category`는 클래스를 정하는 데 쓰지 않는다(한 값이 여러 클래스에 걸리고 배열이며 비어 있을 수 있다).
- DB 스키마 전체 개편이 논의 중이라 스키마를 건드리는 부분은 이 계획에서 뺀다.
- 결정 목록에 D-065를 추가한다. 계획 작성 중 `origin/main`에 D-062~D-064가 이미 있어 번호를 D-065로 정했다.

**보류**
- GuardDuty: OCSF 2004(Detection Finding)가 맞지만 알럿 전용이라 이벤트 클래스로 쓰지 않는다. 별도 인덱스를 알럿 대상(`kind = "alert"`)으로 받을지는 보류. 알럿 쪽 GuardDuty 매핑표는 #336에서 이미 들어갔다.
- Suricata: 한 데이터셋에 `event_type`별 클래스(4001·4002·4003, 알럿성은 2004)가 섞여 "대상당 클래스 하나"와 맞지 않는다. 스트림을 `event_type`별로 나눌지, 설정에 조건을 둘지, 일부만 지원할지 보류.
- Prowler: 2003(Compliance Finding)을 받아 두지만 Prowler 출력이 2003인지 2004인지 확인하지 못했다. 샘플 확인 뒤 확정.
- ModSecurity: 4002를 쓰려 하지만 어떤 로그(감사 로그 등)가 오는지 확인하지 못했다.
- CloudTrail: 6003(API Activity)과 3002(Authentication, 로그인)를 받아 두지만 샘플을 확인하지 못했다.
- "YAML로 해 달라"는 요청이 매핑표를 뜻하는지 클래스 정의를 뜻하는지 전해 준 사람에게 확인 중이다. 클래스 정의를 뜻하면 알럿 쪽(#328) 구조까지 바뀌므로 따로 정한다.

## 바뀐 점
