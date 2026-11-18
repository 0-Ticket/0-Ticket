---
issue: 340
date: 2026-11-19
owner: uptime-zero
plan: 340-event-class-config.md
supersedes: []
---

# 이벤트 수집 대상에 OCSF 클래스 번호(`class`)를 적을 수 있다

## 한 일

- `[[ingest.sources]]`에 선택 항목 `class`(OCSF 클래스 번호)를 더했다. 이벤트 대상만 쓸 수 있고, `ocsf/classes/<번호>.json`이 있는 번호여야 하며 2004(알럿)는 쓰지 못한다. 적지 않으면 `Source.ocsf_class`가 `None`이고 지금처럼 동작한다. `config/default.toml`의 nginx·apache에 `class = 4002`를 적었다(D-065).
- 이벤트가 쓸 클래스의 공식 OCSF 1.9.0 정의를 받아 `ocsf/classes/`에 고정했다. 새로 `2003`(compliance_finding), `3002`(authentication), `4001`(network_activity), `4003`(dns_activity)를 받았고, 줄여 두었던 `4002`·`6003`은 공식 정의(설명·optional 속성 포함)로 바꿨다. `scripts/fetch_ocsf_schema.py`의 `CLASSES`에 6개를 더했고, `objects.json`은 127개에서 138개가 됐다. 기존 127개는 바뀌지 않았다.
- `ocsf_schema.has_class_definition`을 더했다. 설정이 이 함수로 받아 둔 클래스만 허용한다.
- **이 설정은 읽고 검사만 한다.** 정규화(`mapping.normalize`, `run.py`)는 `class`를 쓰지 않으므로 서비스 동작과 DB에 쌓이는 결과는 이전과 같다.

## 계획과 달라진 점

- `tests/normalize/test_ocsf_full_schema.py`의 "클래스 0·2004와 참조 객체 127개" 검사를 "클래스 8개와 138개"로 고쳤다. 범위를 넓히면 숫자가 바뀌는 검사라서 내용은 두고 숫자와 대상 클래스만 바꿨다(계획 "바뀐 점"에 적음).
- 계획에 없던 테스트를 하나 더했다: 스크립트의 `CLASSES`와 `ocsf/classes/`의 파일 번호가 같은지(`test_fetch_ocsf_schema.py`). 어긋나면 설정이 받지 않은 클래스를 허용하기 때문이다.
- 알럿 대상에 `class`를 쓰면 번호와 관계없이 오류다(`0`, `4002`도 거부). 계획의 "알럿 대상에 쓸 수 없다"를 그대로 따랐다.
- 수집 설정이 `soc.normalize.ocsf_schema`를 불러오게 됐다(`ingest/config.py`). 함수 하나만 쓰고 DB·정규화 실행과 무관하다. 다른 단계 코드를 부르는 것이 마음에 걸리면 번호 목록을 가벼운 공유 모듈로 옮기는 방법이 있다.

## 다음 사람이 알아야 할 것

- **설정의 `class`는 아직 아무 곳에도 쓰이지 않는다.** 정규화에 연결하려면 먼저 원본에 클래스(와 수집 키)를 저장해야 하는데, `raw_records` 변경이라 공통 계약이고 DB 스키마 개편 결정이 먼저 필요하다. 지금 `raw_records`에는 클래스도 수집 키도 없어서 정규화는 여전히 `_index` 이름 정규식으로 클래스를 고른다. Filebeat 기본 스트림(`.ds-filebeat-9.5.0-...`)은 정규식에 맞지 않아 nginx·suricata 이벤트가 Base Event(class 0)로 저장되는 문제도 그대로다.
- **클래스 정의를 받아 둔 것과 정규화가 쓰는 것은 다르다.** 4001·4003·3002·2003은 정의만 있고 매핑표가 없다. 설정에 `class = 4001`을 적어도 검사는 통과하지만, 나중에 정규화에 연결하면 매핑표가 없는 클래스는 처리 방법을 정해야 한다. 검증 단계(`validate_ocsf`)는 정의 파일이 있어 통과한다.
- **이벤트 매핑표 위치(후속)**: `mapping_tables/events/<클래스 번호>.yaml`로 두기로 했다. 알럿 로더(`tables.py`)가 `mapping_tables/*.yaml`을 파일 이름을 소스 이름으로 읽고 `table_check.py`가 2004 기준으로 검사하므로, 이벤트 표를 같은 폴더에 두면 안 된다. 이벤트 표는 설정이 클래스를 정하므로 `detect`가 필요 없다. 이벤트용 로더와 검사(클래스 번호 기준)는 후속 이슈에서 만든다.
- **보류 항목(소스 쪽 사정)**: GuardDuty는 OCSF 2004가 맞지만 알럿 전용이라 이벤트 클래스로 쓰지 않았다. Suricata는 한 데이터셋에 `event_type`별 클래스(4001·4002·4003, 알럿성은 2004)가 섞여 "대상당 클래스 하나"와 맞지 않는다. Prowler가 2003인지 2004인지, ModSecurity가 어떤 로그인지, CloudTrail 로그인이 3002인지는 샘플로 확인하지 못했다. 그래서 `default.toml`의 클라우드 3곳에는 `class`를 적지 않았다.
- **"YAML로 해 달라"는 요청**은 매핑표인지 클래스 정의 파일인지 전해 준 사람에게 확인 중이다. 클래스 정의를 뜻하면 알럿 쪽(#328) 구조까지 바뀌므로 따로 정한다.
- 이 계획 작성 중 `origin/main`에서 결정 번호가 D-062~D-064로 올라가 D-065를 썼다. 머지 전에 번호가 겹치지 않는지 다시 확인한다.
- 실제 ELK에서는 확인하지 않았다. 설정 읽기와 스키마 파일은 로컬에서만 검증했다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- `uv run pytest`: 2,155 통과(566 제외). 이전 2,121에서 설정 검사·`has_class_definition`·클래스 파일 일치 테스트가 늘었다.
- 주요 테스트: `tests/ingest/unit/test_config.py`(기본 설정의 클래스 선언, 허용 번호 7개, 생략, 잘못된 값 7종, 알럿 대상 거부), `tests/normalize/test_ocsf_full_schema.py`(`has_class_definition`, 고정 범위 닫힘), `tests/normalize/test_fetch_ocsf_schema.py`(`CLASSES`와 파일 일치).
- `uv run python scripts/fetch_ocsf_schema.py`: 클래스 8개, 객체 138개. 기존 객체 127개는 바뀌지 않았고 `4002`·`6003`은 공식 정의로 바뀌어도 기존 이벤트 검증 테스트가 통과했다.
- 손으로 확인하지 않은 것: `-m db` 테스트(DB 변경이 없음), 실제 수집 실행.
