---
issue: 349
date: 2026-11-20
owner: uptime-zero
plan: 349-event-mapping-tables.md
supersedes: []
---

# Filebeat 스트림의 nginx·ModSecurity 요청을 HTTP Activity로 정규화한다

## 한 일

- 이벤트의 소스 표를 이름 순서로 대조한 뒤, 일치하는 표가 없으면 기존 인덱스 규칙으로 분류한다. 합성 Filebeat 스트림에서 nginx와 ModSecurity가 4002가 된다.
- 클래스 표에서 공통 ECS 필드와 엔티티를 읽고 소스 표에서 값을 보완한다. 4002는 센서 호스트를 엔티티에서 빼고 도메인과 URL에 목적지 역할을 준다. HTTP 메서드, 요약, 필수 HTTP 객체의 검증 경계는 기존과 같다.
- ModSecurity는 요청 시각·요청 ID·요청·응답·엔드포인트를 읽는다. 응답 본문, 룰 매치, 전체 헤더는 정규화 문서에 복사하지 않는다. 요청 ID는 metadata.correlation_uid에 저장한다.
- 클래스 표가 읽는 경로 23개를 ECS 허용 목록에 두고 OCSF target·필수 경로·enum과 함께 검사한다.

## 계획과 달라진 점

- ModSecurity 시각의 두 입력은 형식이 달라 소스 표에서 ctime, 클래스 표에서 ISO 시각을 각각 읽는다. 필드가 없을 때만 클래스 표의 시각을 채택한다. 빈 문자열·명시적인 null·잘못된 형식은 validation_failed다.
- ECS의 http.response.bytes는 전체 응답 길이(length), http.response.body.bytes는 본문 길이(body_length)로 구분했다. ModSecurity Content-Length는 이슈의 대응대로 length로 저장하므로 이 값은 헤더가 보고한 길이이며 전체 응답의 실측값으로 해석할 수 없다.
- 기존 #302 웹 이벤트 계약을 따라 source.ip·destination.ip의 비어 있지 않은 원문 문자열을 엔티티에 보존한다. 알럿과 type·role은 같고 추가 IP 유효성 검사는 적용하지 않는다.

## 다음 사람이 알아야 할 것

- 시간대 없는 ModSecurity 시각은 확인한 샘플을 근거로 UTC로 해석한다. 서버가 다른 시간대를 쓰면 그 차이만큼 어긋난다. 시각 필드가 없을 때 대체한 @timestamp는 수집 시각일 수 있다.
- 소스 판별 조건은 확정 계획대로 event.module이다. nginx 모듈에 접근 로그 외의 데이터셋도 수집한다면 4002 분류 범위를 확인해야 한다. 설정 class를 원본에 저장하는 작업은 후속이다.
- 기존 행은 재처리 전까지 그대로다. 개발 DB 사본의 재처리 전후 건수와 4002 전용 조회 결과는 사람이 확인한다. L2·L3·UI의 엔티티·OCSF 출력 확인과 알럿 담당의 동일 요청 ID 존재 확인은 PR 전에 필요하다.
- 6003·Base Event는 기존 방식으로 host.name을 읽는다. CloudTrail의 호출자 계정·서비스 호스트명, Suricata의 flow·http·tls·alert별 분류와 Kibana 알럿 수집 경로는 후속 이슈에서 다룬다.

## 확인 방법

- 개발 전 합성 Filebeat hit가 4002 대신 0이 되는 실패와, 임시 PostgreSQL에서 해당 원본을 재처리해도 클래스가 바뀌지 않는 실패를 확인했다.
- uv run ruff format --check . 및 uv run ruff check . 통과. uv run pytest 결과 2,509건 통과, 마커 제외 578건, Qdrant 버전 조회 경고 2건.
- 별도의 PostgreSQL 17.6 컨테이너에서 uv run pytest -m db tests/normalize 결과 54건 통과. test_event_reprocess_reclassifies_filebeat_base_event가 두 소스의 기존 class 0 행을 같은 ID로 갱신하는지 확인한다.
- tests/normalize/test_web_event_samples.py는 접근 시각과 수집 시각, 잘못된 시각, 필드 충돌, OCSF 검증 및 민감 필드 제외를 검사한다. test_event_tables.py·test_event_transforms.py는 표 정의와 변환의 경계값을 검사한다.

## 마무리 점검

- 구현 커밋 `f6424e8`에서 포맷을 실행한 결과 447개 파일에 변경이 없었다. 포맷 검사·린트와 기본 pytest를 다시 실행해 2,509건이 통과했다(마커 제외 578건, Qdrant 버전 조회 경고 2건).
- 새 PostgreSQL 17.6 컨테이너에서 정규화 DB 테스트 54건이 다시 통과했다. 합성 데이터로 확인한 범위는 기존 행 ID 보존과 4002 재분류까지다.
- PR 전 사람이 확인할 항목: 개발 DB 사본의 재분류 건수, L2의 엔티티 변경, L3·UI의 OCSF 출력, 알럿 원문과의 요청 ID 일치 여부.
