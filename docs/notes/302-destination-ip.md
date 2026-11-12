---
issue: 302
date: 2026-11-12
owner: uptime-zero
plan: 302-destination-ip.md
supersedes: [234-ocsf-alert-event.md]
---

# 목적지 IP를 엔티티와 OCSF 본문에 보존한다

## 한 일

- 확정 계획에 따라 공통 엔티티와 클래스별 OCSF 매핑을 보완한다.
- 원본과 기존 추출 정책을 유지하고, 합성 샘플을 먼저 작성한다.

## 계획과 달라진 점

- Base Event의 자유 형식 객체 검증 지원은 사용자 확인 중이다. 나머지 클래스 수정은 확정 범위다.

## 다음 사람이 알아야 할 것

- HTTP·API Activity는 최상위 `dst_endpoint.ip`를 지원하지만 Detection Finding은 `evidences[].dst_endpoint.ip`를 사용한다.
- 기존 데이터가 없다는 사용자 확인에 따라 소급 보완은 하지 않는다.
- OCSF 본문과 공통 엔티티는 원본에서 각각 만들어지며, 이번 변경은 구조를 바꾸지 않는다.

## 확인 방법

검사 후 기록한다.

## 구현·검증 중간 결과

- `ENTITY_FIELDS`에 목적지 IP를 추가했다. 새 Alert·Event의 엔티티에 `role=dst`가 보존된다.
- Alert는 `evidences[].dst_endpoint.ip`, HTTP·API Activity는 `dst_endpoint.ip`에 같은 값을 보존한다. Base의 OCSF 표현 변경은 사용자 확인 전이므로 아직 적용하지 않았다.
- 공식 1.9.0 `evidences` 정의를 축약해 추가했다. 독립 검토에서 공식 API와 축약 결과가 정확히 일치함을 확인했다. 새로운 객체를 내보내지 않는 경로는 기존대로다.
- 새 목적지 단위 테스트는 구현 전 8 실패·35 통과로 누락을 재현했고 구현 후 43건이 통과했다. 기존 매핑 테스트와 합쳐 77건이 통과했다.
- `uv run ruff format --check .`: 346개 파일 통과. `uv run ruff check .`, `git diff --check`: 통과.
- `uv run pytest`: 1,575 통과, 480 기본 제외. 기존 `FakeSshServer`의 pending-task 종료 경고 3건이 출력됐고 종료 코드는 0이었다.
- 코드·테스트 독립 검토에서 결함은 발견되지 않았다. 실제 ELK나 LLM은 호출하지 않았다.
- 전체 DB 테스트는 별도 일회용 PostgreSQL 17 컨테이너에서 실행 중이다.

### DB 검증 결과

- 일회용 PostgreSQL 17 컨테이너에서 `uv run pytest -m db -q`: 449 통과, 1,606 제외, 종료 코드 0(91.46초).
- 새 DB 테스트에서 목적지 엔티티·Alert OCSF 증거·목적지 자산 스냅샷 저장, 출발지 보존, 반복 실행 중복 방지, 원본 글자 불변을 확인했다.
- 검증용 컨테이너는 테스트 후 제거한다. 실제 환경 DB는 사용하지 않았다.
- Base Event의 `unmapped` 표현과 자유 형식 객체 검증 보완은 사용자 결정 전이다. 전체 확정 계획의 완료로 보고하지 않는다.

## Base Event 보완 승인 (2026-11-12)

- 사용자가 “그럼 그렇게 진행하고, 명확하게 명시만 하면 되겠네”라고 승인했다. 앞 절의 Base 승인 대기 상태를 대체한다.
- Base Event(class_uid 0)는 `dst_endpoint`가 정의되어 있지 않다. 원본에는 있지만 해당 클래스의 표준 필드로 매핑하지 못한 목적지 IP를 OCSF 표준 필드 `unmapped` 아래 `destination.ip` 경로로 보존한다. `unmapped`는 임의 접두사가 아닌 표준의 자유 형식 객체다.
- 소비자는 HTTP·API Event의 `ocsf.dst_endpoint.ip`, Alert의 `ocsf.evidences[].dst_endpoint.ip`, Base Event의 `ocsf.unmapped.destination.ip`를 읽는다. 클래스에 따른 조회 경로 차이가 있으며, `unmapped.destination.ip`를 모든 OCSF 클래스의 표준 목적지 필드로 취급하면 안 된다.
- 모든 클래스의 공통 엔티티는 `entities`의 `{type: ip, value: 원본 값, role: dst}`다. 원본은 `raw_records.original_text`에 변함없이 보존된다.
- 자유 형식 JSON 객체에만 예외를 더하고 일반 OCSF 객체 검증은 유지한다. Base에서 출발지 IP나 다른 원본 속성까지 복사하지 않는다.

### Base Event의 저장 형태와 조회

원본 `_source.destination.ip`가 `192.0.2.24`인 경우 `events.ocsf` JSONB의 해당 부분은 다음과 같다(나머지 OCSF 공통 필드 생략).

```json
{
  "class_uid": 0,
  "unmapped": {
    "destination": {"ip": "192.0.2.24"}
  }
}
```

```sql
-- Base Event: 표준 목적지 전용 필드가 아닌 원본 보존 경로
SELECT ocsf #>> '{unmapped,destination,ip}' FROM events WHERE ocsf_class = 0;
-- HTTP·API Activity
SELECT ocsf #>> '{dst_endpoint,ip}' FROM events WHERE ocsf_class IN (4002, 6003);
-- Detection Finding: 현재 매핑이 만드는 첫 번째 증거
SELECT ocsf #>> '{evidences,0,dst_endpoint,ip}' FROM alerts;
```

- `destination.ip` 전용 SQL 컬럼을 추가하지 않았다. `entities`와 `ocsf`는 각각 JSONB 컬럼이고 원본은 `original_text` text다.
- 목적지가 없거나 문자열이 아니거나 공백뿐이면 Base에서도 빈 `unmapped` 객체를 생성하지 않는다. 평평한 점 키가 존재하면 유효성에 관계없이 중첩 키보다 우선한다.
- 자유 형식 객체 보완의 RED는 4 실패·66 통과(목적지 누락과 유효한 generic JSON 객체 거부)였고, 구현 후 새 목적지 테스트 70건 및 기존 매핑 테스트 34건이 통과했다.
- Base 보완에 대한 독립 코드 검토에서 결함은 발견되지 않았다.

## 최종 완료 확인

앞의 중간 검사·승인 대기 기록은 아래 최종 상태로 대체한다.

- Base Event도 목적지 IP를 `ocsf.unmapped.destination.ip`에 저장한다. 네 클래스 모두 목적지 공통 엔티티와 OCSF 본문 보존을 완료했다.
- `uv run ruff format --check .`: 346개 파일 통과. `uv run ruff check .`, `git diff --check`: 통과.
- `uv run pytest`: 1,602 통과, 481 기본 제외, 종료 코드 0(23.94초). 기존 FakeSshServer pending-task 종료 경고 3건은 남아 있다.
- `uv run pytest -m db -q`: 별도 일회용 PostgreSQL 17에서 450 통과, 1,633 제외, 종료 코드 0(125.52초). Base Event의 JSONB 경로 SQL 조회, 목적지 자산 저장, 반복 실행 무중복, 원본 보존을 추가 확인했다. 테스트 컨테이너는 제거한다.
- 정의 밖의 최상위 속성, network endpoint와 evidence의 잘못된 구조·타입은 계속 거부된다. 자유 형식 객체만 JSON 값·문자열 키를 허용하며 비유한 실수와 비JSON 값은 거부한다.
- 확정 계획의 완료 기준을 모두 충족했다. Base의 검증기 보완은 사용자 승인 후 계획의 “바뀐 점”에 기록한 변경이다. 그 밖의 범위 차이는 없다.
- 기존 데이터 소급 보완, 실제 ELK·LLM 연결 검증, GitHub 게시·push는 하지 않았다.
