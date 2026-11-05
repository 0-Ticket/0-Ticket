---
issue: 248
date: 2026-11-05
owner: Juhyeok0603
supersedes: [229-l2-decisions.md]
---

# 벡터 DB 범위·분류 후보 경로·임베딩 모델을 L2 분류에 맞게 정하기

## 목표

L2 분류가 벡터 검색으로 후보 Incident를 찾을 수 있도록 분류 후보 경로(D-027),
Qdrant 적재 범위(D-013), 임베딩 모델(D-031)을 함께 확정한다.

이번 이슈에서 기능 결정이 바뀌는 파일은 `docs/decisions.md` 하나다. 코드·의존성·설정·
Qdrant 컬렉션은 후속 L2-A 이슈에서 만든다.

## 방법

### 분류 후보 경로(D-027)

후보 조회 경로는 설정으로 고르고 기본은 벡터 검색으로 한다. 벡터 검색은 새 Ticket과
비슷한 `linked` Ticket의 `incident_id`를 모은 뒤, PostgreSQL에서 Incident의 상태와
`updated_at` 시간 창을 한 번 확인한다. Qdrant에서는 `ticket_time`으로 거르지 않는다.
과거 Ticket이 최근까지 열린 Incident의 참 후보일 수 있기 때문이다.

다음 경우 해당 Ticket 한 건은 기존 직접 조회 경로로 떨어진다.

- Qdrant 컬렉션이 없다.
- Qdrant 조회가 실패한다.
- PostgreSQL 확인을 통과한 유효 후보가 0건이다.

직접 조회 결과도 0건이면 기존 Incident 후보가 없는 것으로 처리하고 벡터 경로로 돌아가지
않는다. 어느 경로든 후보 Incident에는 기존 엔티티 정규화와 강한·보조·공용 신호 분류를
적용하고 Ticket과 겹치는 신호를 센다.

최종 Incident 선택, 에이전트 실패 때의 규칙 기본값, 보류하지 않는 동작, 저장할 Incident
한 행 잠금은 기존 D-027을 유지한다. 벡터 검색은 참 후보를 놓치거나 무관한 후보를 낼 수
있고 최종 선택은 에이전트가 한다. 잘못 연결된 Ticket을 자동으로 떼거나 재배정하는 기능은
없어 같은 공격의 상관관계가 나뉜 채 남을 수 있다는 한계도 D-027 메모에 적는다.

### Qdrant 적재 범위(D-013)

Qdrant에는 판정이 끝난 Ticket·Case를 용도별 컬렉션으로 나누어 넣는다. L2 분류 후보용
컬렉션에는 Incident에 붙은 `linked` Ticket만 넣고 payload에 `incident_id`를 둔다.
`closed`·`held` Ticket은 Incident payload가 없고 후보 검색에 쓰이지 않으므로 넣지 않는다.
유사 사례 검색용 Ticket·Case 컬렉션의 구체 범위는 그 컬렉션을 만드는 이슈에서 정한다.

Incident는 Ticket이 붙을수록 텍스트가 길어져 새 Ticket과 닮은 부분이 묻히거나 입력 길이에서
잘릴 수 있으므로 통째로 임베딩하지 않는다. Ticket 단위로 넣으면 같은 단위끼리 비교하고,
Incident에 Ticket이 많을수록 검색될 point도 늘어난다.

분류 후보용 컬렉션은 PostgreSQL을 베낀 파생 색인이다. payload의 Incident 관계는 복사본이고
권위 원본은 PostgreSQL이다. Qdrant 쓰기는 PostgreSQL 트랜잭션이나 outbox에 묶지 않는다.
일부 point 누락은 자동 감지하지 않고, PostgreSQL에서 컬렉션을 다시 만드는 명령으로 복구한다.
재구축 명령은 후속 L2-A 범위다.

### 임베딩 모델(D-031)

기본 임베딩 모델은 `BAAI/bge-m3`의 dense 표현으로 정하고 로컬 ONNX 경로로 실행한다.
기본 벡터는 1024차원이고 거리 방식은 Cosine이다. sparse·multi-vector는 쓰지 않고 torch를
설치하지 않는다.

모델 ID와 revision은 설정 값이며 revision은 반드시 고정한다. 컬렉션 이름은 용도·모델 ID·
revision에서 파생해 서로 다른 임베딩 공간이 한 컬렉션에 섞이지 않게 한다. 안전한 컬렉션
이름 변환, ONNX 실행 라이브러리, 정확한 revision 문자열은 L2-A에서 정한다.

임베더가 출력 차원을 알려 주고 컬렉션은 그 값을 사용한다. 그래서 테스트는 작은 차원의
가짜 임베더로 적재·검색 흐름을 확인할 수 있다.

### 결정 상태와 기록

「담당자가 정함」에서 D-031을 빼고 D-025·D-030만 남긴다. 「기록」 맨 위에는 분류 후보
경로(D-027)와 Qdrant 범위(D-013)는 팀 합의로 바꿨고, 기본 임베딩 모델(D-031)은 L2 담당이
정했다는 것을 한 줄 안에서 구분해 적는다.

## 바꿀 곳

- `docs/decisions.md`: D-027 후보 경로와 메모, D-013 적재 범위와 메모, D-031 확정 위치,
  「담당자가 정함」과 「기록」
- `docs/plans/248-l2-vector-decisions.md`: 확정 계획
- `docs/notes/248-l2-vector-decisions.md`: 개발 기록

기능 결정 내용이 바뀌는 파일은 `docs/decisions.md` 하나다. 계획·기록 파일은 작업 절차상
추가한다.

## 다른 코드와 맞물리는 곳

- #226이 만든 Incident 직접 조회와 엔티티 겹침 계산은 직접 조회 경로와 fallback으로 유지된다.
- 이 결정이 머지된 뒤에도 벡터 경로 구현이 없는 동안은 직접 조회만 동작한다.
- 벡터 경로와 후보 경로 설정 키는 후속 L2-A가 만든다.
- 후속 L2-A는 모델 ID·revision 설정, 목적별 컬렉션 이름, 재구축 명령을 만든다.
- 기존 계약·테이블·함수·설정 키는 이번 이슈에서 바꾸지 않는다.

## 범위 밖

- 후보 조회 경로의 설정 키 이름과 설정 절 위치
- `qdrant-client`와 ONNX 임베딩 라이브러리 선정·설치
- Qdrant 컬렉션 생성과 payload의 구체 형식
- Ticket 임베딩 텍스트 합성 규칙
- 벡터 적재·검색 코드
- PostgreSQL에서 Qdrant 색인을 재구축하는 명령
- 모델 ID·revision 설정 키와 기본값 구현
- 컬렉션 이름의 안전한 인코딩 방식
- Qdrant CI 서비스와 실제 BGE-M3 테스트
- 유사 사례용 Ticket·Case 컬렉션
- Incident 병합과 Ticket 재배정
- 잘못 연결된 Ticket을 자동 복구하는 기능
- 기존 #226 직접 조회 코드 변경

## 완료 기준

- [ ] D-027에 벡터 검색·직접 조회 경로와 설정 선택이 적혀 있고 기본은 벡터 검색이다
- [ ] D-027에 구체적인 설정 키 이름은 적혀 있지 않다
- [ ] 컬렉션 부재·조회 실패·PostgreSQL 확인 후 유효 후보 0건은 직접 조회로 떨어진다
- [ ] 직접 조회 결과도 0건이면 후보 없음으로 끝나며 벡터 경로로 돌아가지 않는다
- [ ] 두 후보 경로 모두 PostgreSQL에서 Incident 상태와 `updated_at` 시간 창을 확인한다
- [ ] Qdrant의 Ticket 시각으로 후보를 필터링하지 않는다
- [ ] D-027의 엔티티 등급, 에이전트 선택, 규칙 기본값, 저장 잠금은 유지된다
- [ ] 참 후보 누락·무관한 후보·Ticket 재배정 부재의 한계가 D-027에 적혀 있다
- [ ] D-013에 용도별 컬렉션과 분류 후보용 `linked` Ticket 적재가 적혀 있다
- [ ] PostgreSQL이 관계의 권위 원본이고 Qdrant payload는 파생 복사본이다
- [ ] Incident 대신 Ticket을 임베딩하는 이유가 D-013에 적혀 있다
- [ ] 일부 point 누락은 자동 감지하지 않고 PostgreSQL 재구축으로 복구한다
- [ ] D-013과 D-027 메모가 같은 내용을 반복하지 않는다
- [ ] D-031에 기본 BGE-M3 dense·로컬 ONNX·1024차원·Cosine이 적혀 있다
- [ ] 모델 ID·revision이 설정 값이고 revision을 고정한다
- [ ] 컬렉션 이름이 용도·모델 ID·revision에서 파생된다
- [ ] 「담당자가 정함」에서 D-031이 빠지고 D-025·D-030만 남는다
- [ ] 「기록」 맨 위에서 팀 합의와 L2 담당 결정을 구분한다
- [ ] D-013·D-027·D-031이 서로 충돌하지 않는다
- [ ] 결정 ID 표기가 설명을 먼저 쓰고 괄호에 ID를 쓰는 규칙을 따른다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과한다
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록이 있다

## 토론으로 정한 것

1. D-013만 바꾸면 기존 분류 후보 방법(D-027)과 충돌하므로 D-027도 이번 이슈에서 함께
   바꾼다.
2. 분류 후보 컬렉션에는 Incident 관계가 있는 `linked` Ticket만 넣는다.
3. Incident 전체 임베딩은 사용하지 않는다. 긴 Incident 입력에서 개별 Ticket 신호가 묻히거나
   잘릴 수 있기 때문이다.
4. Qdrant는 PostgreSQL의 파생 색인으로 두고 트랜잭션·outbox는 만들지 않는다. 대신
   PostgreSQL에서 전체 색인을 다시 만드는 명령을 L2-A에 둔다.
5. 컬렉션 부재, 조회 오류, PostgreSQL 확인 후 유효 후보 0건은 해당 Ticket을 직접 조회로
   떨어뜨린다.
6. 유효 후보가 한 건 이상 있지만 일부 point가 누락된 상태는 자동으로 감지하지 않는다.
   이 누락은 재구축 명령으로 복구한다.
7. 벡터 검색은 후보를 놓칠 수도 있고 무관한 후보를 제시할 수도 있다. 최종 선택은 기존
   D-027대로 에이전트가 한다.
8. 벡터 후보도 PostgreSQL에서 `Incident.updated_at` 시간 창을 한 번 확인한다. Qdrant
   `ticket_time` 필터는 참 후보를 제거할 수 있어 두지 않는다.
9. 후속 구현에서 후보 경로 값은 `vector`와 `direct`로 통일한다. 구체적인 설정 키 이름과
   위치는 L2-A에서 정한다.
10. 잘못 연결된 Ticket은 자동으로 복구되지 않는다. Incident를 종결하는 것은 병합이나
    Ticket 재배정이 아니다.
11. BGE-M3의 dense 표현과 Cosine을 사용한다. sparse·multi-vector는 사용하지 않는다.
12. BAAI/bge-m3는 기본 모델이고 모델 ID·revision은 설정 값이다. 이는 모델처럼 환경마다
    바뀌는 값을 설정으로 둔다는 구조 원칙을 따른다.
13. 컬렉션 이름을 용도·모델 ID·revision에서 파생해 서로 다른 임베딩 공간이 섞이는 것을
    구조적으로 막는다.
14. ONNX 실행 라이브러리와 정확한 revision 문자열은 L2-A에서 정한다. 이번 결정에는 실행
    경로와 호환 조건만 확정한다.
15. 테스트용 임베더가 작은 차원을 쓸 수 있도록 컬렉션 차원은 임베더가 알려 준 값을 사용한다.

## 바뀐 점
