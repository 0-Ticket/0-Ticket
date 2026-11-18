---
issue: 336
date: 2026-11-18
owner: Pandyo
plan: 336-guardduty-mapping-table.md
supersedes: []
---

# GuardDuty 알럿의 엔티티·제목·설명을 매핑표로 채우고 엔티티 선언에 when을 더함

## 한 일

- 엔티티 항목에 선택 항목 `when: {field, equals}`를 더했다. `field`는 문자열 또는 목록이고 `equals`는 문자열 하나다. 로더가 알 수 없는 키, 빠진 `field`, 문자열이 아닌 `equals`, 객체가 아닌 값을 `MappingTableError`로 막는다. `exists`는 받지 않는다. 필드 값이 없거나 다르면 그 항목은 적용하지 않고 누락 경로도 남기지 않는다.
- `mapping_tables/guardduty.yaml`을 더했다. 판별은 `guardduty` 키가 있는지(`exists`)이고 코드의 GuardDuty 판별(`_detect_source`의 분기)은 없앴다. 판별은 표 → unknown이다.
- 엔티티: AWS API 호출의 원격 IP(ip/src), `accessKeyDetails.userName`(user/actor), `instanceDetails.instanceId`(host/target), `accountId`(host/target). 네트워크 연결은 `connectionDirection`으로 `when`을 걸어 INBOUND면 원격이 src·로컬이 dst, OUTBOUND면 로컬이 src·원격이 dst다.
- 소스 표 `entries`가 처음으로 적용된다. `_finding`이 `common`을 적용하고 소스를 판별한 뒤 소스 표를 적용해 같은 target을 덮어쓴다. `guardduty.title`·`description`이 `finding_info.title`·`finding_info.desc`·`message`가 된다. 원본에 값이 없으면 `common` 값(룰 이름·설명)이 남는다. 폴백 판정(uid·title·time)은 `common` 기준 그대로다.

## 계획과 달라진 점

- 계획에 있던 `check_tables` 수정은 필요 없었다. `common`과 소스 표가 같은 target을 선언해도 검증기는 그대로 통과한다(저장소 표 전체 검사 테스트가 이를 지킨다).
- `_detect_source`가 `source` 인자를 받지 않는다(GuardDuty 코드 분기가 없어져 필요 없어졌다). 호출은 `_finding` 한 곳뿐이었다.
- 소스 `required` 누락(`missing`)은 병합 후에도 값이 없는 target만 남긴다. 지금 소스 표에는 `required`가 없어 동작 차이는 없다.

## 다음 사람이 알아야 할 것

- GuardDuty 알럿의 `entities`·`observables`·`title`·`desc`가 바뀐다. L1·L2·L3가 읽는 데이터가 바뀌며 담당자 확인은 사용자가 받아 알린다.
- D-027: OUTBOUND에서 로컬 IP(피해 호스트의 사설 IP)가 `src`가 되어 그래프 연결 근거가 된다. 같은 사설 IP를 쓰는 다른 알럿과 Incident로 묶일 수 있다.
- 계정 ID를 `host`/`target`으로 두어 observable이 Hostname이 되고 자산 조회가 `(host, 계정ID)`로 찾는다. 일치하는 자산이 없으면 결과에 넣지 않는다. 계약에 계정 타입이 없어서 생긴 한계다.
- 소스 판별은 표 이름 순이라 `guardduty`가 `modsecurity`·`suricata`보다 먼저 검사된다. `event.module`과 `guardduty` 키가 함께 있는 원본은 이제 guardduty다(`test_tables_are_checked_by_name_so_guardduty_wins_over_suricata`가 이 동작을 문서화한다). 실제 GuardDuty 알럿에는 `event.module`이 없다. `guardduty`가 문자열 같은 객체가 아닌 값이어도 GuardDuty로 본다. `null`은 아니다.
- 기존 알럿은 바뀌지 않는다. `reprocess --source guardduty`(D-063)를 돌려야 갱신된다. 재처리는 이미 만든 Ticket·Incident 제목, 임베딩, 그래프 묶음을 바꾸지 않는다.
- `guardduty.severity`, `eventFirstSeen`, 포트, `evidences`, 배열 안쪽 값, `accessKeyId`·`principalId`는 읽지 않는다(범위 밖).
- 새 GuardDuty 유형은 필드를 확인하지 않았다(확인한 유형은 RootCredentialUsage, TorClient). 표에 없는 경로는 조용히 건너뛴다.
- 샘플의 실제 값은 쓰지 않았다. 문서용 값(192.0.2.x, 198.51.100.x, 203.0.113.x, `i-0123456789abcdef0`, 계정 `123456789012`)만 있다. INBOUND 케이스는 OUTBOUND 샘플의 방향만 바꿔 직접 만든 것이다.
- 개발 DB 사본에서 `reprocess --source guardduty`를 돌린 건수는 아직 없다. 사람이 돌려 알려 주면 PR에 적는다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`: 통과(2120건, 마커 제외).
- DB 테스트(`-m db`)는 이 환경에 DB 연결 설정이 없어 돌리지 못했다. 이번 변경은 DB 코드를 건드리지 않는다.
- 새 테스트: `tests/normalize/test_when_and_guardduty.py`(`when` 로더·적용, 덮어쓰기와 `common` 유지, 판별 순서). 새 샘플: `alert_skeleton.json`의 `guardduty_root_credential_usage`, `guardduty_tor_client_outbound`, `guardduty_tor_client_inbound`와 기존 `guardduty_without_ecs_fields`의 기대 엔티티(원격 IP src 추가). `desc` 기대값을 `test_alert_skeleton.py`가 있을 때만 검사한다. 표 샘플은 `mapping_tables/source_when_ok.yaml`과 `source_bad_when_*.yaml` 다섯 개.
- 실제 알럿 건수 확인: 아직 안 했다.
