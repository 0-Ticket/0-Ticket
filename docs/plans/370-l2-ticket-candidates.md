---
issue: 370
date: 2026-11-24
owner: Juhyeok0603
supersedes: [319-incident-graph.md, 329-l2-graph-join.md, 362-l2-candidate-environment.md]
---

# Ticket 유사도와 그래프 근거로 L2 Incident 후보를 분류한다

## 목표

새 Ticket과 유사한 기존 Ticket의 실제 소속 Incident를 L2 후보로 주고, 그래프 경로와 환경 문맥을 함께 보고 분류한다. 후보 개수 초과, 색인 누락, 출력 오류, 저장 경쟁만으로 새 Incident를 만들지 않는다. 같은 공격의 후보 누락을 줄이되 과거 Incident·Ticket 관계는 자동으로 고치지 않는다.

## 방법

1. **분류 전용 색인과 색인 대기 기록.** Qdrant에 `ticket_branch` 용도 컬렉션을 다시 만든다. 모든 Ticket의 생성·판정 갱신·Incident 연결을 PostgreSQL 트랜잭션과 같은 트랜잭션에서 Ticket별 색인 대기 기록으로 남긴다. 색인 워커가 기록을 읽어 point를 갱신하고 처리한 버전을 확인한다. 같은 Ticket의 오래된 쓰기가 새 point를 덮지 못하게 직렬화한다. 생성 때는 판정 전 문맥, L1 판정 뒤에는 늘어난 Event 문맥, 연결 뒤에는 `linked` 상태와 Incident ID를 반영한다. 초기 배포에서는 기존 Ticket 전체를 대기열에 넣고 색인 준비가 끝나야 분류한다. 별도 재색인·정합성 확인 명령을 둔다. Qdrant 쓰기는 PostgreSQL 트랜잭션 안에 넣지 않으며 PostgreSQL이 소속·상태의 기준이다. 기존 `ticket_verdicts` 컬렉션과 L1 색인은 바꾸지 않는다.
2. **임베딩 텍스트.** Ticket 제목, Alert 제목·룰, 타입·역할을 표시한 엔티티, L3 Hunt 가설, 길이를 제한한 Alert·Event 행위 요약을 일정한 순서로 합친다. 색인과 질의에 같은 함수를 쓴다. 원본 로그 전체, `verdict.reason`, `hunt.reason`, 모델이 쓴 분류 이유는 넣지 않는다. 판정 전에 없는 Event 요약은 판정 후 색인 갱신으로 채운다. 빈 내용은 Ticket 제목으로 처리한다. 기존 `branch/embed.py`와 테스트는 새 규칙에 맞게 수정하거나 제거한다.
3. **벡터 후보 수집.** 새 Ticket 자신을 빼고 `linked` point 중 분류용 유사도 하한 이상을 점수 순으로 끝까지 읽는다. 설치된 Qdrant 클라이언트의 `query_points`는 `score_threshold`와 `offset`을 지원한다. 페이지를 따라 읽고 Incident별 최고 점수와 대표 Ticket을 보존한다. PostgreSQL에서 hit Ticket의 실제 `linked` 상태·소속, Incident의 열린 상태·Ticket 수 상한(`max_incident_tickets = 10`)을 다시 확인한다. 오래된 point나 잘못된 payload는 후보로 쓰지 않는다. 열린 Incident이면 벡터 검색에 시간 제한을 두지 않는다. 그래프만 연결되고 유사도 하한 미달인 Incident는 후보에 넣지 않는다.
4. **그래프와 L2 입력.** 벡터 검증을 통과한 Incident에 대해 기존 Ticket·Alert·Entity 그래프 경로를 조회한다. 그래프의 `candidate_window_ms`는 유지하며 후보 수 초과 시 모두 버리는 규칙을 없앤다. 오래된 벡터 후보나 공유 `src`가 없는 후보에는 경로가 없어도 된다. 벡터 대표 Ticket ID·점수, 그래프 경로, Incident 요약, 후보 Alert의 구조화된 target host 문맥을 길이 제한해 L2에 보여 준다. `similar_ticket_ids` 검증은 벡터 대표 Ticket을 포함한 실제 입력 Ticket ID를 허용한다. `new`일 때 `similar_ticket_ids`는 빈 배열이라는 계약을 프롬프트에 명시한다. 한쪽 target host가 없다는 사실만으로 환경이 다르다고 판단하지 않는다.
5. **전체 후보 검토와 이어가기.** `[l2.branch] max_candidates = 5`는 한 번의 모델 입력에 담는 Incident 수로 의미를 바꾼다. 한 실행 주기에서 모델 호출은 최대 3회로 제한한다. 유사도 하한을 넘은 후보를 모두 검토할 때까지 Ticket에 후보 스냅샷·진행 위치·중간 판단을 저장하고 다음 주기에 이어간다. 각 묶음의 `new`는 그 묶음에서 선택할 후보가 없다는 뜻이며 즉시 Incident를 만들지 않는다. 모두 검토한 뒤 각 묶음에서 고른 후보들을 L2가 다시 비교해 최종 `existing` 또는 `new`를 결정한다. 최종 비교 후보가 5개를 넘으면 같은 방식으로 나눠 검토한다. 중간 출력은 형식·후보 ID를 검증하고 Agent Log에 남긴다. 정상적으로 모든 후보를 조회했는데 적격 후보가 0건이면 모델 호출 없이 `no_similar_candidate`를 기록하고 새 Incident를 만든다.
6. **준비·실패·저장.** 분류용 컬렉션이 없거나 연결된 Ticket의 색인 대기가 남았으면 검색 완료를 주장하지 않는다. 색인 워커의 실제 쓰기 실패는 오류로 기록하고 분류 재시도 횟수에 넣되, 아직 처리 중인 대기만으로는 실패를 세지 않는다. Qdrant·그래프 조회 실패, 모델 형식 오류, 근거 ID 오류, 저장 직전 선택한 Incident의 종료·상한 도달은 새 Incident로 바꾸지 않고 재조회·재시도한다. 최초 포함 최대 3회, 실패 사이 5분이다. 주기를 나눠 후보를 검토하는 정상 진행도 실패 횟수에 넣지 않는다. 오류 3회를 소진하면 Ticket을 `held`로 두고, 운영자 CLI는 L2 분류 때문에 보류한 Ticket만 `escalated`로 재개한다. `cancelled`는 실패로 세지 않는다. 저장 전 Ticket과 선택한 Incident를 잠가 상태·소속·상한을 재검증한다. 후보가 바뀌었으면 새 스냅샷으로 재검토하며 분류 오류를 근거로 신규 Incident를 만들지 않는다.
7. **기록과 표시.** `tickets.details.l2_branch`에 벡터 후보·점수·대표 Ticket, 그래프 경로, 색인 준비·탐색·진행 상태, 최종 결정의 출처와 실패 이유를 구분해 남긴다. Ticket 상세 API는 기존 Ticket 계약의 `details`로 이를 전달한다. Incident 상세 API와 화면은 벡터 전용 연결을 그래프 경로 없음과 구분해 표시한다. 로그 원문과 모델 출력은 화면에 텍스트로만 표시한다.

분류용 점수 하한은 기존 `ticket_verdicts`의 0.6을 옮겨 쓰지 않는다. 손제작 같은 사건·다른 사건 사례를 고정하고 실제 bge-m3 점수를 측정해 **같은 사건 사례가 모두 후보에 남는** 가장 높은 하한을 정한다. 다른 사건 후보가 일부 들어오면 L2가 분리한다. 이 기준을 만족시키지 못하면 임의의 값을 확정하지 않고 사람과 다시 논의한다. 모델 호출과 임베딩 비용·처리 시간은 로컬 실행 결과를 건수와 범위로 기록한다.

## 바꿀 곳

- `src/soc/db/migrations/`: 현재 최고 번호보다 큰 새 마이그레이션에 Ticket별 분류 색인 대기 기록을 만들고 기존 Ticket을 백필한다.
- `src/soc/l1/ticketing.py`, `src/soc/l1/judge.py`, `src/soc/l3/hunt/store.py`, `src/soc/l2/branch/store.py`: Ticket 생성·판정·연결 트랜잭션에서 색인 대기 버전을 기록한다.
- `src/soc/l2/branch/`: 분류 텍스트·색인 워커·재색인/정합성/재개 CLI, 후보 검색·그래프 제한 조회, L2 묶음 판단·진행 기록·저장 전 재검증을 구현한다.
- `src/soc/store/qdrant.py`: 기존 호출을 유지하면서 분류용 점수 하한·페이지 조회에 필요한 인자를 더한다.
- `src/soc/agent/executor.py`, `config/default.toml`, `src/soc/l2/config.py`: 색인 워커 순서와 분류용 설정(점수 하한, 한 주기 호출 상한, 실패 횟수·간격)을 연결한다. 그래프 `candidate_window_ms`와 Incident의 `max_incident_tickets`는 유지한다.
- `src/soc/l2/prompts/l2_classify.md`, `src/soc/l2/branch/decide.py`, `contracts/branch_decision.schema.json`과 생성 코드: 벡터 대표 Ticket 근거, 묶음 판단·최종 판단, `new` 출력 형식을 맞춘다. 계약 변경은 원본에서 생성한다.
- `src/soc/api/routes/workflow.py`, `src/soc/api/ui_models.py`, `frontend/src/`: Incident 상세의 분류 근거·탐색 상태를 갱신한다. 화면 변경이면 전·후 스크린샷을 사람이 붙인다(D-075).
- `tests/fixtures/`, 관련 L1·L2·L3·Qdrant·API·화면 테스트, `docs/decisions.md`, 개발 후 `docs/notes/370-l2-ticket-candidates.md`.

## 다른 코드와 맞물리는 곳

- PostgreSQL: 새 색인 대기 테이블과 Ticket 상태/상세. 기존 Ticket 작성 경로와 L1·L2·L3 워커가 영향을 받는다. L2의 `held`는 `details.l2_branch`로 구분해 L1 보류 Ticket을 재개하지 않는다.
- Qdrant: 분류용 `ticket_branch` 컬렉션을 새로 채운다. `ticket_verdicts`(D-053)와 재색인 명령은 유지한다. 분류용 색인이 비어 있거나 미완성이면 `new`로 가지 않는다.
- 설정: `[l2.branch] max_candidates` 의미가 전체 후보 상한에서 모델 호출당 입력 상한으로 바뀌고 새 키가 생긴다. 로컬 설정 파일이 같은 표를 덮어쓰는 경우 갱신이 필요하다.
- 출력·표시: 후보 입력, 출력 검증, `details.l2_branch`, Incident 상세 API·생성 TypeScript 계약과 화면 문구가 바뀐다. 기존 저장 경로와 과거 `public_ip_only` 표시는 유지한다.
- 결정: Qdrant(D-013)의 분류용 색인 범위·대기 기록과 Incident 분류(D-027)의 후보·실패 규칙을 바꾼다. L2 분석 재시도(D-028)와 유사 사례 검색(D-053)은 그대로다.

## 범위 밖

- 이미 저장된 Incident·Ticket 관계의 자동 병합·재분류, 과거 그래프 경로 생성.
- Case 확정·대응 실행, L1 유사 사례 검색 정책 변경, 새 임베딩 모델·라이브러리 도입.
- 임계값 미달 그래프 단독 후보의 자동 연결.

## 완료 기준

- [ ] 손제작 픽스처에서 같은 사건의 기존 Incident가 분류용 점수 하한을 모두 통과하고, 반복 제목·같은 IP의 다른 사건은 L2가 분리한다. 벡터 전용·오래된 열린 Incident도 확인한다.
- [ ] 후보가 6개 이상이어도 모두 버리거나 즉시 새 Incident를 만들지 않는다. 여러 주기에 걸친 중단·재시작 뒤 남은 후보를 끝까지 검토하며 주기당 호출 상한 3회를 지킨다.
- [ ] 그래프 단독·유사도 미달 후보는 제외되고, 벡터 후보의 대표 Ticket ID가 모델 입력·출력 검증에 들어간다. 한쪽 target host 누락은 환경 불일치 근거가 되지 않는다.
- [ ] 정상 조회의 후보 0건은 `no_similar_candidate` 신규 생성이고, 색인 대기·Qdrant 장애·그래프 장애·모델 형식 오류·저장 경쟁은 신규 생성이 아니다.
- [ ] Ticket 생성·판정·Incident 연결의 색인 대기 기록이 같은 DB 트랜잭션으로 저장된다. 늦은 쓰기, 낡은 payload, 누락 point, 컬렉션 재생성·재색인 및 초기 백필을 검증한다.
- [ ] 실패는 최초 포함 3회·5분 간격으로 재시도하고, 소진하면 L2 보류 Ticket만 CLI로 재개할 수 있다. `cancelled`와 정상 이어가기는 실패로 세지 않는다.
- [ ] 기존 Incident 선택 시 PostgreSQL의 Ticket 소속·Incident 상태·Ticket 10개 상한을 저장 직전에 재확인한다.
- [ ] 기존 `ticket_verdicts`, 과거 Incident 관계, API의 과거 그래프 표시는 유지한다. 실제 모델 회귀 사례와 토큰·점수 측정 결과는 건수·범위로 notes에 기록한다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, 관련 `db`·`qdrant` 검사와 화면의 `pnpm contracts:check`, `pnpm lint`, `pnpm test`, `pnpm build`가 통과한다.
- [ ] 새 환경변수가 있으면 `.env.example`에 이름만 적고, `docs/notes/`에 개발 기록을 남긴다.

## 토론으로 정한 것

- 이슈의 모든 Ticket 색인 범위를 유지하고, PostgreSQL 색인 대기 기록을 더한다. 그래프 단독 후보는 유사도 하한을 통과하지 못하면 제외한다. Qdrant가 분류의 후보 진입 조건이므로 색인 미준비·장애를 정상적인 후보 0건과 구분한다(D-013·D-027 변경).
- 벡터 후보는 열린 Incident면 시간 제한 없이 검색하고, 그래프의 기존 24시간 창은 유지한다. 벡터 전용 후보도 L2가 판단한다.
- 한 번의 모델 입력에는 후보 5개, 한 실행 주기에는 모델 호출 3회까지 둔다. 전체 적격 후보는 주기를 이어 끝까지 검토하고, 마지막에 L2가 선택한다. 개수 한도는 신규 Incident 생성 근거가 아니다.
- 분류 실패는 3회·5분 뒤 L2 Ticket을 보류하고 운영자 CLI로 재개한다. 색인 대기와 정상 이어가기는 실패가 아니다.
- 점수 하한은 높은 후보 재현율로 실제 bge-m3·손제작 사례에서 정한다. 후보 0건은 색인이 준비되고 조회가 정상 완료됐을 때만 신규 생성한다.
- 이슈의 ‘후보군을 합친다’는 표현은 벡터 기준을 통과한 후보의 그래프 근거를 합친다는 뜻으로 좁혔다. 모델 판정 이유를 임베딩하지 않고 Alert·Event 행위 요약을 포함한다.

## 바뀐 점
