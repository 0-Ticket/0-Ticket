---
issue: 332
date: 2026-11-18
owner: Pandyo
supersedes: []
---

# ModSecurity·Suricata 알럿 매핑표 추가와 매핑표의 엔티티 선언

`328-ocsf-schema-mapping-tables.md`의 범위 밖에 있던 "엔티티, `_detect_source`는 코드에 둔다"를 이 계획이 바꾼다(D-062가 D-061의 해당 부분을 대체). 328 계획 파일은 고치지 않는다.

## 목표

엔티티와 소스 판별(`detect`)을 코드(`mapping.py`)에서 매핑표로 옮기고, ModSecurity 알럿의 목적지(dst)를 엔티티와 observables에 복구한다. Suricata와 그 밖의 알럿 출력은 바뀌지 않는다.

## 방법

1. **테스트 먼저.** `tests/fixtures/normalize/mapping_tables/`에 `entities` 형식 오류(잘못된 type·role, 미등록 엔티티 변환, 형식 틀림)와 `detect`의 `field` 목록 표를 두고 로더·검증기 테스트를 먼저 쓴다. `alert_skeleton.json`에서 ModSecurity 두 케이스의 기대 엔티티를 dst까지 늘려 실패하는 것을 확인한 뒤 구현한다.
2. **표 형식.** 표에 선택 최상위 `entities` 목록을 더한다. 항목은 `type`, `role`(생략하면 null), `from`(원본 경로 목록, 앞에서부터 처음 있는 값, `$.` 접두 규칙은 `entries`와 같다), `transform`(선택)이다. `type`·`role`은 계약(`contracts/common/entity.schema.json`)의 허용 값이어야 한다.
3. **엔티티 변환 등록부.** `transforms.py`에 `entries` 변환과 분리된 등록부를 둔다. 변환은 `(type, 값)`을 돌려준다(None이면 값 없음). `ip`는 IP 형식이 아니면 읽지 못한 항목, `domain_or_ip`는 포트와 대괄호를 떼고 IP면 type을 `ip`로 바꾼다. `mapping._strip_port`는 여기로 옮긴다. 변환 없는 항목은 문자열을 그대로 쓴다. 미등록 이름은 표 로드 시점의 오류다.
4. **`common.yaml`의 ECS 엔티티.** 지금 `_alert_entities`와 같은 순서·같은 role로 `source.ip`(ip, src), `destination.ip`(ip, dst), `user.name`(user, actor), `url.domain`(`domain_or_ip`, dst), `destination.domain`(`domain_or_ip`, dst), `url.original`(url, dst)을 둔다. `url.domain`과 `destination.domain`은 항목 둘이다. 소스 표는 여기에 더할 것만 둔다. 적용 순서는 common → 소스 표이고, 같은 엔티티는 한 번만 둔다.
5. **잘못된 IP.** type이 ip인 항목에서 값이 있는데 IP가 아니면 role에서 누락 경로를 만든다(src → `evidences[].src_endpoint.ip`, dst → `evidences[].dst_endpoint.ip`). 같은 경로는 한 번만 적는다. 순서는 지금과 같게 표 순서다. `evidences`를 채우는 코드는 그대로다.
6. **`detect`.** 조건의 `field`를 문자열 또는 목록(앞에서부터 처음 있는 값)으로 받는다. `modsecurity.yaml`과 `suricata.yaml`에 `field: [event.module, kibana.alert.original_event.module]`, `equals: <소스>`를 둔다. `mapping._detect_source`는 표 판별 → GuardDuty(코드) → `unknown` 순으로 부른다. `alert_source`는 표 이름이다.
7. **소스 표.**
   - `modsecurity.yaml`: `detect`와 엔티티 `transaction.client_ip`(ip, src), `transaction.host_ip`(ip, dst), `transaction.request.hostname`(`domain_or_ip`, dst). `headers.Host`와 `host_port`는 쓰지 않는다.
   - `suricata.yaml`: `detect`만 둔다. 추가로 읽을 `suricata.eve.*`는 샘플로 확인한 것이 없어 넣지 않는다.
8. **`mapping.py`.** `_alert_entities`의 ECS 고정 읽기를 표 적용으로 대체한다. `evidences`는 `destination.ip`를 코드에서 읽는 그대로 둔다. Event 쪽 `ENTITY_FIELDS`·`_entities`는 건드리지 않는다.
9. **검증기.** `table_check.py`가 `entities`의 type·role과 엔티티 변환 이름을 검사한다. 저장소의 모든 표를 pytest가 돌린다.
10. **샘플.** ModSecurity 두 케이스의 기대 엔티티를 dst까지 늘리고, XSS 샘플에 `transaction.client_ip`·`host_ip`·`host_port`·`request.hostname`을 문서용 값으로 더한다. 센서 컨테이너 ID(`host.name`·`agent.*`)가 어떤 엔티티에도 없다는 테스트를 둔다. 나머지 케이스는 기대값을 바꾸지 않는다.

## 바꿀 곳

- `src/soc/normalize/tables.py`: `entities`·`detect` 목록 `field` 로더와 적용
- `src/soc/normalize/transforms.py`: 엔티티 변환 등록부(`ip`, `domain_or_ip`)
- `src/soc/normalize/table_check.py`: 엔티티 검사
- `src/soc/normalize/mapping.py`: 엔티티·소스 판별을 표로 대체, `_strip_port` 이동
- `src/soc/normalize/mapping_tables/common.yaml`, `modsecurity.yaml`, `suricata.yaml`
- `tests/normalize/`, `tests/fixtures/normalize/`(`alert_skeleton.json`, `mapping_tables/`)
- `docs/decisions.md`: D-062, D-061 행 표시

## 다른 코드와 맞물리는 곳

- ModSecurity Alert의 `entities`·`observables`에 dst가 더해진다. 계약은 그대로이고 L1·L2·L3가 읽는 데이터가 바뀐다. D-027의 그래프 연결은 `src`만 써서 영향은 작다. 해당 담당자 확인은 사용자가 받아 알린다.
- 표 형식(`entities`, `detect` 목록)과 `tables.py` 공개 함수가 바뀐다. 읽는 곳은 `mapping.py`와 정규화 실행기의 시작 점검이다.
- 이미 정규화된 알럿은 바뀌지 않는다. 새 알럿부터 적용하고 재처리는 별도 이슈다.

## 범위 밖

- GuardDuty 표와 판별(코드에 남김), Event 정규화, 포트와 `evidences` 채우기
- 피해 자산 매핑(host target), 에이전트 원본 조회 도구의 마스킹, 계약 변경
- 기존 알럿 재처리, 읽기 전용 dry-run 명령
- `headers.Host`, 확인하지 않은 `suricata.eve.*` 값

## 완료 기준

- [ ] 매핑표 `entities`를 로더·검증기가 읽고, 잘못된 type·role과 미등록 변환을 실패로 잡는 테스트가 있다.
- [ ] `mapping.py`의 고정 엔티티 읽기를 표 선언으로 대체했다.
- [ ] ModSecurity 샘플(XSS, SQLi)의 정규화 결과에 dst IP가 엔티티와 observables에 들어간다.
- [ ] ModSecurity 두 케이스를 제외한 기존 케이스(Suricata, unknown, GuardDuty 포함)의 결과가 이전과 같다.
- [ ] 센서 컨테이너 ID(`host.name`·`agent.*` 값)가 어떤 엔티티에도 없다는 테스트가 있다.
- [ ] 두 소스의 `detect`가 표에서 동작하고 `event.module` 우선순위를 지키며, 판별에 실패하면 지금처럼 GuardDuty 또는 unknown으로 간다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과한다.
- [ ] `docs/decisions.md`에 D-062가 있다.
- [ ] 실제 알럿의 정규화 전후 비교 결과(ModSecurity dst 복구)를 건수로 PR에 적었다(사람이 돌려 알린다).

## 토론으로 정한 것

답은 2026-11-18에 사람이 정했다.

- **엔티티는 `common.yaml`에, 소스 표는 더할 것만.** 소스 표가 없는 알럿(unknown, GuardDuty)의 ECS 엔티티를 지키려는 것이다. 이슈의 "Suricata 표로 옮긴다"와 달리 Suricata 표는 `detect`만 갖는다.
- **ModSecurity 두 케이스의 기대 엔티티를 늘린다.** 이슈의 "기존 테스트 변경 없이 통과"는 "ModSecurity 두 케이스를 제외하고 변경 없음"으로 바로잡는다. XSS 샘플에는 실제 알럿(54건 전부 있음)에 맞춰 필드를 문서용 값으로 더한다.
- **필드 경로는 이슈 문구대로.** `transaction.client_ip`·`request.hostname`·`host_ip`·`host_port`가 54건 전부에 있고 `headers`는 45건뿐이라 Host 헤더는 쓰지 않는다. `source.ip`와 `client_ip`는 54건 모두 같아(다른 건 0, 빈 값 0) 중복 제거로 하나가 된다.
- **엔티티 전용 변환 등록부.** `(type, 값)`을 돌려주는 별도 등록부를 둔다.
- **`missing_fields`는 role에서 파생.** `transaction.host_ip`가 틀리면 `partial`이 되는 동작을 허용한다.
- **`detect`의 `field`를 목록으로 확장.** 코드의 우선순위(`event.module` 우선, 없을 때만 `original_event.module`)를 지키기 위해서다. 기존 문자열 형식도 받는다.
- **`url.domain`과 `destination.domain`은 항목 둘.** 지금 둘 다 엔티티가 되기 때문이다.
- **role 생략 = null.**
- **전후 비교와 재처리.** 사람이 돌려 건수만 알린다. 새 알럿부터 적용하고 기존 알럿 재처리는 별도 이슈다.
- **D-062.** D-061의 "엔티티·`_detect_source`는 코드" 부분을 대체한다.

## 바뀐 점
