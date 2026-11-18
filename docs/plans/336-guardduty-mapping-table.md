---
issue: 336
date: 2026-11-18
owner: Pandyo
supersedes: []
---

# GuardDuty 알럿 매핑표 추가와 엔티티 선언의 조건(when) 지원

## 목표

GuardDuty 알럿의 엔티티와 제목·설명을 매핑표로 채운다. 방향에 따라 role이 바뀌는 항목을 선언하도록 엔티티 항목에 `when`을 더하고, 코드의 GuardDuty 판별을 표로 옮긴다. ModSecurity·Suricata·unknown의 정규화 결과는 바뀌지 않는다.

## 방법

1. **샘플과 테스트 먼저.** 정제한 두 샘플의 구조로 문서용 값 fixture를 `tests/fixtures/normalize/alert_skeleton.json`에 더하고, `tests/fixtures/normalize/mapping_tables/`에 `when` 형식 오류 표를 둔다. 기대값을 먼저 쓰고 실패하는 것을 확인한 뒤 구현한다. 값은 모두 문서용(192.0.2.x, 198.51.100.x, 203.0.113.x, `i-0123456789abcdef0`, 계정 `123456789012`)이다.
   - RootCredentialUsage: 원격 IP(src), 사용자 `Root`(actor), 계정(target). 제목·설명은 `guardduty.title`·`description`.
   - TorClient OUTBOUND: 로컬 IP(src), 원격 IP(dst), 피해 호스트(target), 계정(target).
   - TorClient INBOUND: OUTBOUND 샘플에서 방향 값만 바꿔 직접 만든 fixture. 원격 IP(src), 로컬 IP(dst).
   - 기존 `guardduty_without_ecs_fields`: `guardduty.title`·`description`이 없는 케이스로 남긴다. 제목은 룰 이름 그대로이고 원격 IP(src) 엔티티만 기대값에 더한다.
   - `event.module`과 `guardduty` 키가 함께 있는 원본의 현재 판별 결과를 문서화하는 테스트 하나.
2. **`when`.** `tables.py`의 `EntityRule`에 선택 항목 `when`을 더한다. 형식은 `{field: <경로 또는 목록>, equals: <문자열>}`이다. 로더가 알 수 없는 키, 빠진 `field`, 문자열이 아닌 `equals`를 `MappingTableError`로 막는다. 원본 필드 이름은 검증하지 않는다. `apply_entities`는 필드 값(목록이면 처음 있는 문자열)이 `equals`와 같을 때만 항목을 적용하고, 값이 없거나 다르면 건너뛴다.
3. **소스 표 `entries`가 `common`을 덮어쓴다.** `mapping._finding`이 `common`을 적용하고 소스를 판별한 뒤 소스 표의 `entries`를 적용해 같은 target을 덮어쓴다. 원본에 값이 없으면 `common` 값을 유지한다. 폴백 판정(uid·title·time)은 `common` 기준 그대로이고 새 `required`는 만들지 않는다. `title`·`finding_info.desc`·`message`는 병합 결과에서 읽는다. `check_tables`는 같은 target을 `common`과 소스 표가 함께 선언하는 것을 허용한다.
4. **`guardduty.yaml`.** `mapping_tables/guardduty.yaml`을 더한다(경로는 `_source` 기준).
   - `detect`: `field: guardduty`, `exists: true`. 코드의 `_detect_source`에서 GuardDuty 판별을 지운다. 순서는 표 → unknown이고 표 안에서는 표 이름 순이다.
   - `entries`: `finding_info.title` ← `guardduty.title`, `finding_info.desc` ← `guardduty.description`, `message` ← `guardduty.description`.
   - `entities`:
     - `guardduty.service.action.awsApiCallAction.remoteIpDetails.ipAddressV4`: `ip`/`src`, 변환 `ip`
     - `guardduty.resource.accessKeyDetails.userName`: `user`/`actor`
     - `guardduty.resource.instanceDetails.instanceId`: `host`/`target`
     - `guardduty.accountId`: `host`/`target`
     - 네트워크 연결(`guardduty.service.action.networkConnectionAction.connectionDirection`): INBOUND이면 `remoteIpDetails.ipAddressV4`가 `ip`/`src`, `localIpDetails.ipAddressV4`가 `ip`/`dst`. OUTBOUND이면 로컬이 `ip`/`src`, 원격이 `ip`/`dst`. `when`으로 항목 넷을 나눈다.
5. **`mapping.py`.** `_finding`의 소스 판별에서 GuardDuty 코드 분기를 없애고 병합 흐름을 3번대로 바꾼다. Event 쪽은 건드리지 않는다. `evidences`는 `destination.ip`로 채우는 그대로다.
6. **적용.** 머지 후 사람이 개발 DB 사본에서 `reprocess --source guardduty`를 돌려 건수를 알리면 PR 초안에 적는다(운영 DB 알럿 4건 확인).

## 바꿀 곳

- `src/soc/normalize/tables.py`: `when` 로더와 적용
- `src/soc/normalize/mapping.py`: 소스 표 `entries` 병합, GuardDuty 판별 코드 제거
- `src/soc/normalize/table_check.py`: `common`과 소스 표의 같은 target 허용 확인(필요하면)
- `src/soc/normalize/mapping_tables/guardduty.yaml`(새)
- `tests/normalize/`, `tests/fixtures/normalize/`(`alert_skeleton.json`, `mapping_tables/`)
- `docs/decisions.md`: D-064

## 다른 코드와 맞물리는 곳

- GuardDuty 알럿의 `entities`·`observables`·`title`·`desc`가 바뀐다. 계약은 그대로이고 L1·L2·L3가 읽는 데이터가 바뀐다. 담당자 확인은 사용자가 받아 알린다.
- D-027: OUTBOUND에서 로컬 IP(피해 호스트의 사설 IP)가 `src`가 되어 그래프 연결 근거가 된다. 같은 사설 IP를 쓰는 다른 알럿과 Incident로 묶일 수 있다. 묶음 담당자 확인은 사용자가 받아 알린다.
- 표 형식(`when`)과 `tables.py` 공개 동작(소스 표 `entries` 적용)이 바뀐다. 읽는 곳은 `mapping.py`와 정규화 실행기의 시작 점검이다. 소스 판별은 표 이름 순이라 `guardduty`가 `modsecurity`·`suricata`보다 먼저 검사된다. 실제 GuardDuty 알럿에는 `event.module`이 없어 영향은 없고 테스트로 현재 동작을 문서화한다.
- 계정 ID가 `host`/`target`이라 observable이 Hostname이 되고 자산 조회가 `(host, 계정ID)`로 찾는다. 일치하는 자산이 없으면 결과에 넣지 않는다. 한계를 개발 기록에 적는다.
- 재처리(`reprocess`, D-063)는 `title`·`entities`·`ocsf`를 갱신하지만 이미 만든 Ticket·Incident 제목, 임베딩, 그래프 묶음은 바꾸지 않는다.
- 새 환경변수·설정 키·테이블·계약 변경은 없다.

## 범위 밖

- 포트와 `evidences` 채우기
- 배열 안쪽 값(`networkInterfaces`, `tags`)
- 액세스 키 ID와 `principalId`의 엔티티화(자격 증명 식별자)
- 자산 조회(host target의 자산 매핑)
- 새 GuardDuty 유형의 필드 확인(현재 확인된 유형: RootCredentialUsage, TorClient)
- 심각도(`guardduty.severity`), 시각(`eventFirstSeen`) 매핑 변경
- 이벤트(Event) 정규화
- `when`의 `exists`와 원본 필드 이름 검증

## 완료 기준

- [ ] `when`을 로더가 읽고, 알 수 없는 키·빠진 `field`·문자열이 아닌 `equals`를 로더가 실패로 잡는다는 테스트가 있다.
- [ ] RootCredentialUsage 샘플에서 원격 IP(src), 사용자(actor), 계정(target) 엔티티가 만들어진다.
- [ ] TorClient 샘플에서 OUTBOUND와 INBOUND 두 방향의 src/dst가 맞고, 피해 호스트(target) 엔티티가 있다. INBOUND fixture는 문서용 값으로 직접 만든다.
- [ ] `finding_info.title`과 `desc`가 `guardduty.title`·`description` 값이고, 값이 없으면 `common` 값이 유지된다는 테스트가 있다.
- [ ] GuardDuty 판별이 표에서 동작하고, 코드의 GuardDuty 판별을 제거했다. `guardduty` 키가 없으면 지금처럼 unknown으로 간다. `event.module`과 `guardduty`가 함께 있을 때의 결과를 문서화하는 테스트가 있다.
- [ ] GuardDuty가 아닌 소스(ModSecurity, Suricata, unknown)의 정규화 결과는 변경이 없다. GuardDuty 케이스의 기대값만 늘린다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과한다.
- [ ] `docs/decisions.md`에 D-064가 있다.
- [ ] 개발 DB 사본에서 `reprocess --source guardduty`를 실행한 건수 결과를 PR에 적었다(사람이 돌려 알린다).
- [ ] 실제 데이터에는 OUTBOUND만 있으므로 INBOUND 케이스는 문서용 값으로 만든 fixture로 검증한다.

## 토론으로 정한 것

답은 2026-11-18에 사람이 정했다.

- **소스 표 `entries`가 `common`을 덮어쓴다.** 이슈의 "우선 규칙이 아직 없다면 로더에 추가"에 대해 확인한 결과 소스 표 `entries`는 지금 어디서도 적용되지 않아 규칙이 없었다. 원본에 값이 없으면(예: `guardduty.title`) `common` 값(룰 이름)을 유지하고 새 `required`는 만들지 않는다.
- **`when` 형식.** `{field, equals}`만 받는다(`detect`와 같은 문법). 이슈의 "존재하지 않는 필드를 쓰면 검증기가 실패로 잡는다"는 표 형식 검사(알 수 없는 키, 빠진 `field`, 문자열이 아닌 `equals`)로 한정한다. 원본 필드 이름은 검증하지 않는다. D-060의 "조건식 금지"에서 이 한 가지를 예외로 둔다(D-064).
- **소스 판별 순서.** 표 이름 순 그대로 두고 현재 동작을 테스트로 문서화한다. `guardduty` 키가 객체가 아닌 값이어도 GuardDuty로 본다(현실에 없다고 본다).
- **재처리 건수.** #334가 머지됐으므로(`ee8088e`) 사람이 머지 후 개발 DB 사본에서 `reprocess --source guardduty`를 돌려 건수를 알린다.
- **D-027 영향.** OUTBOUND의 로컬 IP가 `src`가 되는 것을 "맞물리는 곳"에 적고 담당자 확인은 사용자가 받아 알린다.
- **샘플.** 사람이 정제한 샘플 둘(RootCredentialUsage, TorClient)로 필드 경로를 확인했다. 접두사는 `guardduty.`가 맞다. 레포에는 문서용 값으로 다시 쓴 fixture만 넣는다.
- **계정 ID 한계.** 계정 ID를 `host`/`target`으로 두면 observable이 Hostname이 되고 자산 조회가 `(host, 계정ID)`로 찾는다. 이슈대로 가고 개발 기록에 한계를 적는다.
- **D-064.** 위 `when`, 덮어쓰기 규칙, GuardDuty 판별의 표 이동을 확정으로 추가한다. D-062의 "GuardDuty 판별만 코드에 남긴다"를 대체한다.

## 바뀐 점
