---
issue: 340
date: 2026-11-18
owner: uptime-zero
supersedes: []
---

# 이벤트 수집 설정에 OCSF 클래스 번호(class) 추가와 이벤트 클래스 정의

## 목표

수집 대상(`[[ingest.sources]]`)마다 이벤트의 OCSF 클래스 번호를 설정에 적을 수 있게 한다. 쓸 수 있는 클래스는 OCSF 1.9.0 클래스 중 사용할 소스(ModSecurity, Suricata, Nginx, GuardDuty, CloudTrail, Prowler)에서 주로 나오는 것을 정의 파일에 미리 정의해 둔다. 정의와 설정 읽기·검사까지만 하고, 정규화와 DB는 바꾸지 않는다.

## 방법

1. **테스트 먼저.** 정의 파일 읽기와 설정 검사의 실패하는 테스트를 먼저 쓴다.
2. **클래스 정의 파일.** `src/soc/event_classes.yaml`에 OCSF 1.9.0의 클래스 `uid`와 `name`을 적는다. 번호와 이름은 기억이 아니라 공식 목록(`https://schema.ocsf.io/api/1.9.0/classes`)에서 받아 확인한 값으로 쓰고, 확인한 날짜를 파일 머리 주석에 적는다. 정의할 클래스: `0 base_event`, `2003 compliance_finding`, `3002 authentication`, `4001 network_activity`, `4002 http_activity`, `4003 dns_activity`, `6003 api_activity`. `src/soc/event_classes.py`가 `yaml.safe_load`로 읽고, `uid` 중복·정수 아님·이름 없음을 오류로 막는다.
3. **설정 `class`.** `[[ingest.sources]]`에 선택 항목 `class`(정수)를 더한다. `ingest/config.py`의 `Source`에 `ocsf_class: int | None = None`을 더한다.
   - 정의 파일에 있는 번호여야 한다. 없는 번호, 정수가 아닌 값(불리언 포함)은 설정 오류다.
   - `kind = "alert"` 대상에 쓰면 설정 오류다(알럿은 2004로 정해져 있다).
   - 적지 않으면 `None`이고 지금처럼 동작한다. 기존 `local.toml`은 영향이 없다.
4. **기본 설정.** `config/default.toml`의 nginx·apache 대상에 `class = 4002`를 적고, `class`의 뜻과 "정규화에 연결되기 전까지 효과가 없다"는 주석을 단다. 나머지 대상(클라우드 3곳)에는 적지 않는다.

## 바꿀 곳

- `src/soc/event_classes.yaml`, `src/soc/event_classes.py`: 새 파일
- `src/soc/ingest/config.py`: `Source.ocsf_class`, `class` 읽기와 검사
- `config/default.toml`: nginx·apache에 `class = 4002`, 설명 주석
- `tests/`: 정의 파일 읽기 테스트, 설정 검사 테스트
- `docs/decisions.md`: 설정 `class` 선언 규칙(D-065)

## 다른 코드와 맞물리는 곳

- 설정 키 `[[ingest.sources]].class`: 새로 더하는 선택 항목이다. 기존 설정은 그대로 동작한다.
- `Source` 데이터클래스: 끝에 기본값이 있는 필드를 더한다. 기존 생성 호출은 바뀌지 않는다.
- PyYAML: #328이 이미 직접 의존(`pyyaml==6.0.3`)으로 넣었다. 코드는 `safe_load`만 쓴다.
- `mapping.py`, `run.py`, `raw_records`, `events`, `normalize_status`, 계약, 에이전트 도구, API, 화면: 바꾸지 않는다. 설정에 `class`를 적어도 지금은 어디에도 쓰이지 않는다.

## 범위 밖

- OCSF 스키마를 받아 고정하는 일, 클래스별 매핑표(YAML), `normalize` 변경, 이벤트 폴백·마스킹·엔티티 규칙.
- 원본에 클래스·수집 키를 저장하는 일, 정규화 연결, `events` 구조, DB 스키마 변경(스키마 개편 결정 뒤 후속 계획).
- 정의한 클래스에 매핑표가 없을 때의 정규화 동작.
- 알럿 구조 변경 협의, SIEM(Filebeat·인덱스) 설정 변경.

## 완료 기준

- [ ] `src/soc/event_classes.yaml`에 위 7개 클래스가 공식 1.9.0 목록 기준의 번호·이름으로 정의돼 있고, 확인한 날짜가 적혀 있다.
- [ ] 정의 파일의 중복·잘못된 값을 오류로 막고 테스트가 있다.
- [ ] 이벤트 대상의 `class`를 읽고, 정의에 없는 번호·정수 아님·알럿 대상의 `class`를 설정 오류로 막는다. 생략한 설정은 지금처럼 동작한다.
- [ ] `default.toml`의 nginx·apache에 `class = 4002`가 있고 설정 읽기 테스트가 통과한다.
- [ ] 기존 normalize·ingest 테스트가 변경 없이 통과한다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과한다.
- [ ] `docs/decisions.md`에 설정 `class` 선언 규칙이 있다.
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록이 있고, 기록에 "설정은 읽히지만 정규화 연결은 후속"과 아래 보류 항목이 적혀 있다.

## 토론으로 정한 것

- 수집 대상의 `kind`는 유지하고, 이벤트의 클래스는 사용자가 설정에 번호로 적는다. 이유: SIEM이 다를 수 있어 분류 기준은 설정이 정하고 코드는 선언을 따른다.
- 클래스 정의에 `status` 같은 구분은 두지 않는다. 정의된 클래스는 OCSF 1.9.0 안에서 그냥 쓸 수 있다.
- 정의 범위는 사용할 소스에서 주로 나오는 클래스만이다. OCSF에 있으면 정의하고, 소스 쪽 사정으로 정해지지 않은 것은 아래처럼 보류로 적는다.
- `event.category`는 클래스를 정하는 데 쓰지 않는다(한 값이 여러 클래스에 걸리고 배열이며 비어 있을 수 있다).
- DB 스키마 전체 개편이 논의 중이라 스키마를 건드리는 부분은 이 계획에서 뺀다.
- 결정 목록에 D-065를 추가한다. 계획 작성 중 `origin/main`에 D-062~D-064가 이미 있어 번호를 D-065로 정했다.

**보류**
- GuardDuty: OCSF 2004(Detection Finding)가 맞지만 알럿 전용이라 이벤트 클래스에 정의하지 않는다. 별도 인덱스를 알럿 대상(`kind = "alert"`)으로 받을지는 보류. 알럿 쪽 GuardDuty 매핑표는 #336에서 이미 들어갔다.
- Suricata: 한 데이터셋에 `event_type`별 클래스(4001·4002·4003, 알럿성은 2004)가 섞여 "대상당 클래스 하나"와 맞지 않는다. 스트림을 `event_type`별로 나눌지, 설정에 조건을 둘지, 일부만 지원할지 보류.
- Prowler: 2003(Compliance Finding)을 정의했지만 Prowler 출력이 2003인지 2004인지 확인하지 못했다. 샘플 확인 뒤 확정.
- ModSecurity: 4002를 정의했지만 어떤 로그(감사 로그 등)가 오는지 확인하지 못했다.
- CloudTrail: 6003(API Activity)과 3002(Authentication, 로그인)를 정의했지만 샘플을 확인하지 못했다.

## 바뀐 점
