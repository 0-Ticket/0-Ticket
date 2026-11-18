---
issue: 332
date: 2026-11-18
owner: Pandyo
plan: 332-modsecurity-suricata-mapping-tables.md
supersedes: []
---

# 알럿 엔티티와 소스 판별을 매핑표로 옮기고 ModSecurity 목적지를 복구함

## 한 일

- 매핑표에 `entities` 섹션(`type`·`role`·`from`·`transform`)을 더했다. `tables.apply_entities`가 `common` → 소스 표 순으로 적용하고 같은 엔티티는 한 번만 둔다. `mapping.py`의 고정 ECS 읽기(`_alert_entities`)는 없어졌다.
- 엔티티 변환 등록부(`transforms.ENTITY_TRANSFORMS`)에 `ip`(IP 형식만)와 `domain_or_ip`(포트·대괄호를 떼고 IP면 type을 `ip`로)를 뒀다. `_strip_port`·`_HOST_PORT`·IP 판별이 `transforms.py`로 옮겨 갔다.
- `common.yaml`이 ECS 표준 엔티티 6개를 선언한다(`url.domain`과 `destination.domain`은 항목 둘). 소스 표가 없는 알럿(unknown, GuardDuty)도 지금과 같은 엔티티를 얻는다.
- `modsecurity.yaml`이 `transaction.client_ip`(src), `host_ip`(dst), `request.hostname`(dst)을 더해 목적지를 복구한다. `suricata.yaml`은 `detect`만 가진다.
- `detect`의 `field`는 문자열 또는 목록(앞에서부터 처음 있는 문자열 값)이다. 두 소스는 `[event.module, kibana.alert.original_event.module]`로 코드의 우선순위를 지킨다. 판별은 표 → GuardDuty(코드) → unknown 순이다.

## 계획과 달라진 점

- **틀린 `transaction.host_ip`는 `partial`이 되지 않는다.** 질문 5의 답에 "partial이 되는 동작을 허용"이라고 적었지만, 지금 코드는 틀린 `source.ip`·`destination.ip`도 `outcome`은 `ok`로 두고 `missing_fields`에만 남긴다(`alert_skeleton`의 `invalid_ips_and_domain_ports`). 같은 규칙을 따랐으므로 `host_ip`도 `ok` + `missing_fields=["evidences[].dst_endpoint.ip"]`다. 계획의 "partial" 표현이 틀린 것이다.
- **엔티티 `type`·`role` 검사를 검증기(`table_check`)가 아니라 로더에서 한다.** 계약의 허용 값(생성된 `Entity` 모델의 Literal)을 읽어 표를 읽을 때 `MappingTableError`로 막는다. 정규화 실행기가 시작할 때 모든 표를 읽으므로 잘못된 표는 처리 전에 드러난다. `check_tables`는 바꾸지 않았고 저장소의 표 전체 검사는 그대로 돈다.
- `ip` 변환 항목은 `role`이 `src` 또는 `dst`여야 로드된다(누락 경로를 role에서 만들기 때문).
- `Condition.field`(문자열)를 `Condition.fields`(튜플)로 바꿨다. 이 때문에 #328의 `test_source_table_loads_with_detect_and_array_targets`의 기대값을 `fields` 튜플로 고쳤다. 다른 기존 테스트는 바꾸지 않았다. 바뀐 `alert_skeleton.json` 기대값은 ModSecurity 두 케이스뿐이다.

## 다음 사람이 알아야 할 것

- ModSecurity Alert의 `entities`·`observables`에 dst가 더해져 L1·L2·L3가 읽는 데이터가 바뀐다. 계약은 그대로이고 D-027 그래프 연결은 `src`만 쓴다. 담당자 확인은 사용자가 받는다.
- `evidences`는 여전히 코드가 `destination.ip`로만 채운다. ModSecurity는 dst 엔티티가 있어도 `evidences`가 비어 있다(범위 밖).
- 이미 정규화된 알럿은 바뀌지 않는다. 기존 알럿 재처리는 별도 이슈다.
- 새 소스 표를 더하면 `detect`와 필요한 `entities`만 쓰면 되고 `mapping.py`는 고치지 않는다. 표 이름이 곧 `alert_source` 값(`normalize_status.source`)이다.
- 샘플의 `transaction.client_ip`는 `source.ip`와 같아 중복 제거로 하나가 된다(실제 54건도 모두 같다고 확인받음). 값이 다르면 src가 둘이 되어 D-027의 연결 후보가 달라질 수 있다.
- `tests/test_tools_ssh_host.py`, `test_tools_threat_intel_vt.py`, `test_tools_siem_elk.py`는 실제 서비스 환경변수가 있어야 하는 마커 테스트라 `-m`을 덮어쓰면 실패한다. 이 이슈와 관계없다.
- 개발 DB: 새 컨테이너에는 `.env`의 DB(`zt_dev`)가 없어 `-m db` 테스트는 `DATABASE_URL`의 DB 이름만 `postgres`로 바꿔 돌렸다(#328과 같다).

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`: 통과(2092건, 마커 제외).
- `uv run pytest -m db tests/normalize tests/test_pipeline_db.py tests/test_lab_cycle_db.py`(DB 이름은 `postgres`로): 41건 통과.
- 새 테스트: `tests/normalize/test_entity_tables.py`(엔티티 로더·변환·`detect` 목록·저장소 표·ModSecurity dst·센서 ID·표 없는 소스). 표 샘플은 `tests/fixtures/normalize/mapping_tables/source_entities_ok.yaml`과 `source_bad_*`.
- 바뀐 샘플: `alert_skeleton.json`의 ModSecurity 두 케이스(dst 추가, XSS에 `transaction.*`·`host`·`agent` 추가).
- 실제 알럿 전후 비교: 아직 안 했다. 사람이 돌려 건수를 알려 주면 PR에 적는다.
