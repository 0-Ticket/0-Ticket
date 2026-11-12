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
