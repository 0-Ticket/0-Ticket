---
issue: 302
date: 2026-11-12
owner: uptime-zero
supersedes: [234-ocsf-alert-event.md]
---

# 정규화 결과에 목적지 IP를 보존한다

## 목표

원본에 목적지 IP가 있으면 Alert·Event의 공통 엔티티와 OCSF 본문에 함께 보존한다.
기존 데이터가 없으므로 소급 보완 없이 손으로 만든 테스트 샘플로 검증한다.

## 방법

- 공통 엔티티 추출에 `destination.ip` → `{type: ip, value: 원본 값, role: dst}`를 추가한다.
- OCSF 1.9.0 클래스 정의가 허용하는 위치에 목적지 IP를 매핑한다. HTTP Activity(4002)와 API Activity(6003)는 `dst_endpoint.ip`를 쓴다. Detection Finding(2004)과 Base Event(0)는 각 클래스가 지원하는 증거·관측 객체를 공식 정의와 대조해 사용한다. 클래스에 없는 `dst_endpoint`를 최상위에 추가하지 않는다.
- 새로 쓰는 OCSF 객체는 공식 1.9.0 정의를 기존 축약 방식으로 `ocsf/objects.json`에 추가하고 출처를 기록한다. 라이브러리·OCSF 버전·검증기는 바꾸지 않는다.
- 기존 추출 규칙을 유지한다: 평평한 점 키 우선, 없으면 중첩 키. 비어 있지 않은 문자열만 사용하고 IP 형식 검사나 배열 확장은 추가하지 않는다. 원본은 수정하지 않는다.
- 출발지와 목적지가 같아도 역할별 엔티티를 각각 유지한다. 자산 조회는 기존처럼 역할 없이 type/value로 중복 제거한다.
- 합성 fixture와 테스트를 먼저 작성해 누락으로 실패하는 것을 확인한 다음 구현한다.

## 바꿀 곳

- `src/soc/normalize/mapping.py`: 목적지 엔티티와 클래스별 OCSF 매핑
- `src/soc/normalize/ocsf/objects.json`, `src/soc/normalize/ocsf/SOURCE.md`: 새로 사용하는 공식 객체 정의와 출처
- `tests/fixtures/normalize/`: 목적지 IP와 기대 결과를 가진 손 작성 샘플
- `tests/normalize/`: 매핑·계약·OCSF 검사 및 DB 저장·자산 조회 확인
- `docs/notes/302-destination-ip.md`: 구현 선택과 검증 결과

## 다른 코드와 맞물리는 곳

- Alert·Event의 기존 `entities` 목록에 `dst` IP가 추가되고 기존 `ocsf` 객체의 내용이 보완된다. Entity 계약은 이미 `dst`를 허용한다. 계약·생성 코드·DB 스키마 변경은 없다.
- 자산 조회가 목적지 IP도 조회하고, 새 Ticket은 Alert 엔티티를 그대로 받는다. L2가 받는 Alert·Event의 OCSF 본문에도 목적지 정보가 보존된다.
- 기존 L2의 엔티티 병합·검색 규칙은 바꾸지 않는다.

## 범위 밖

- 성공한 정규화 결과·기존 Ticket·Incident의 소급 보완과 재처리 명령
- 목적지 외 필드의 OCSF 매핑 확대, OCSF에서 엔티티를 역추출하는 구조 변경
- 새로운 IP 검증·정규화 정책, 배열 필드 지원, 자산·L2 중복 제거 규칙 변경
- 실제 ELK·LLM 호출, 새 도구·라이브러리·환경변수, GitHub 쓰기

## 완료 기준

- [ ] Alert·HTTP·API·Base Event 샘플의 목적지 IP가 공통 엔티티와 클래스에 맞는 OCSF 본문에 보존된다.
- [ ] 평평한 키·중첩 키·키 충돌 우선순위·IPv6·목적지만 있는 경우·같은 src/dst를 확인한다.
- [ ] 누락·빈 문자열·공백·null·숫자·배열·객체는 목적지 항목을 만들지 않으며 기존 출발지 등은 유지된다.
- [ ] 원본이 바뀌지 않고 결과가 공통 계약 및 OCSF 검증을 통과한다. 새 중첩 객체의 잘못된 모양도 거부된다.
- [ ] DB 테스트로 목적지 엔티티·OCSF·일치하는 자산이 저장되고 반복 실행에 중복이 없는지 확인한다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m db`가 통과한다.
- [ ] 개발 기록에 클래스별 실제 매핑 위치와 테스트 결과·미검증 범위를 남긴다.

## 토론으로 정한 것

- 원래 이슈는 공통 엔티티 목록의 누락만 제시했다. 다른 레이어가 OCSF도 읽으므로 OCSF 본문 보완을 함께 포함하기로 확정했다.
- 사용자가 기존 데이터가 없다고 확인했다. 소급 보완 대신 합성 샘플을 통한 검증으로 범위를 정했다.
- 사용자가 2026-11-12에 “확정하고 진행해”라고 승인했다.
- 새로운 도구나 팀 공통 정책 변경이 없어 `docs/decisions.md`에 추가할 결정은 없다.

## 바뀐 점

- 2026-11-12 · 사용자가 Base Event의 목적지 IP를 `ocsf.unmapped.destination.ip`에 보존하고 그 이유를 명시하는 안을 승인했다. Base Event에는 목적지 전용 필드가 없으므로 OCSF 표준의 자유 형식 `unmapped` 객체 안에 원본 경로로 남긴다. 이는 임의 접두사나 새 표준 목적지 필드가 아니다.
- 위 방법의 “검증기는 바꾸지 않는다”를 이 범위에서 대체한다. `src/soc/normalize/ocsf_schema.py`가 공식 `object_t`/`object` 자유 형식 객체의 JSON 값을 허용하도록 보완한다. 정의가 있는 다른 객체와 클래스의 필수 속성·타입·알 수 없는 속성 검사는 그대로 유지한다. JSON이 아닌 값·문자열 아닌 객체 키·비유한 숫자는 거부한다.
- 구현 위치는 HTTP·API `ocsf.dst_endpoint.ip`, Alert `ocsf.evidences[].dst_endpoint.ip`, Base `ocsf.unmapped.destination.ip`로 명시한다. Base의 목적지 외 필드나 새 OCSF 클래스 매핑은 추가하지 않는다. 테스트에는 Base 저장·조회와 자유 형식 객체 허용/거부 경계를 포함한다.
