---
issue: 358
date: 2026-11-20
owner: Pandyo
supersedes: []
---

# L2 그래프: IPv6 표기 차이로 같은 IP가 연결되지 않는 문제 수정

## 목표

L2 그래프 SQL이 `ip` 엔티티를 정규형 기준으로 비교해, 표기만 다른 같은 IPv6(`2001:0DB8:0:0:0:0:0:50`과 `2001:db8::50`)가 후보 경로로 이어지게 한다. #356의 케이스 1c2·1c4가 통과하고 1c3·IPv4 결과는 그대로다.

## 방법

`src/soc/l2/branch/graph.py`의 `_GRAPH_QUERY` `matches` 절 WHERE의 `CASE`에 `ip` 가지를 더한다. 나머지 타입은 지금 그대로다.

- 저장 값 `btrim(entity->>'value')`가 `pg_input_is_valid(v, 'inet')`이고 `/`를 포함하지 않으면 `v::inet = seed.entity_value::inet`로 비교한다. seed 값은 파이썬이 이미 정규형으로 만든 문자열이다.
- 그 밖의 값(IP 모양이 아님, 마스크가 붙은 값)은 기존 `btrim(...) = seed.entity_value` 문자열 비교로 되돌린다.
- seed 쪽도 IP로 안 읽히는 값일 수 있으므로 같은 검사를 거친 뒤에만 `inet`으로 변환한다. `CASE`로 검사가 통과한 가지에서만 변환을 평가하게 해 오류를 막는다.
- 2단계 구조(SQL이 후보 행 조회 → `classify_graph`가 파이썬 `normalize_entity_value`로 재비교)는 바꾸지 않는다. SQL이 행을 놓치지만 않으면 파이썬이 정규형으로 맞춘다.
- IPv4-mapped(`::ffff:192.0.2.1`)는 `inet` 비교에서도 IPv4(`192.0.2.1`)와 다른 값이라 지금 동작이 유지된다.
- 개발 단계에서 그래프 SQL에 인덱스를 타는 사전 필터가 있는지 확인하고, 있으면 새 `CASE`가 그것을 무력화하지 않는지 `EXPLAIN`으로 확인한다. 결과는 notes에 적는다.
- 별도 커밋: `src/soc/entities.py`에서 `entity_value_sql`과 `_BTRIM`을 삭제한다. 호출자가 없다(`src`·`tests`·`scripts` 검색, #319가 호출을 지운 뒤 함수만 남음).

## 바꿀 곳

- `src/soc/l2/branch/graph.py`: `_GRAPH_QUERY`의 ip 비교
- `src/soc/entities.py`: `entity_value_sql`, `_BTRIM` 삭제(별도 커밋)
- `tests/fixtures/l2/scenarios/cases.json`: 1c2·1c4의 `classification`을 `일치`로 바꿔 strict xfail을 지우고, 아래 새 케이스를 추가한다
- `tests/test_l2_scenarios_db.py`: 새 케이스가 기존 파라미터화에 들어가도록 필요하면 보정
- `docs/notes/356-l2-scenario-check.md`: 결함 행(1c2·1c4)의 분류와 근거를 "#358에서 해결"로 갱신한다(표의 두 행과 "다음 사람이 알아야 할 것"의 결함 항목만)
- `docs/plans/358-l2-ipv6-canonical.md`, `docs/notes/358-l2-ipv6-canonical.md`

## 다른 코드와 맞물리는 곳

그래프 SQL의 비교 규칙이 바뀐다(원칙 7). L2 담당이 계획 확정 전에 승인했다. 함수·테이블·데이터 형식·설정 키는 새로 만들거나 바꾸지 않는다. `entity_value_sql` 삭제는 호출자가 없어 다른 코드에 영향이 없다.

## 범위 밖

- 정규화 계약, 저장 방식(#302 원본 값 보존), `alert_model_input`, `[l2.branch]` 설정 키
- `ip` 외 타입(`_LOWER_TYPES`)의 비교 규칙
- IP가 아닌 `ip` 값의 대소문자 비대칭(파이썬 `lower()`, SQL 없음). 기존 `btrim` 비교를 유지한다
- IPv4-mapped와 IPv4를 같은 값으로 묶는 것
- 대량 데이터 성능 측정과 새 환경의 Postgres 버전 전환

## 완료 기준

- [ ] 1c2·1c4가 `일치`로 통과하고 xfail 표시가 없다
- [ ] 1c3과 IPv4 케이스, 기존 `tests/test_l2_branch_db.py`가 그대로 통과한다
- [ ] 아래 샘플이 쿼리 오류 없이 동작하고 기대대로 연결 여부가 정해진다(손으로 만든 문서용 대역 값, `tests/fixtures/l2/scenarios/`):
  - `not-an-ip`, 빈 문자열, `1.2.3`: 저장 값이 이런 값이어도 쿼리가 성공하고 같은 문자열일 때만 연결된다
  - `192.0.2.1:443`(포트 붙은 값): `inet`로 읽지 못해 문자열 비교이고, 같은 문자열일 때만 연결된다
  - `2001:db8::50/64`(CIDR): 기존 `btrim` 문자열 비교로 되돌아가 같은 문자열일 때만 연결되고, 마스크 없는 `2001:db8::50`과는 연결되지 않는다
  - `2001:0DB8:0:0:0:0:0:50`(대소문자 혼합·0 채움): `2001:db8::50`과 연결된다(양방향)
  - IPv4-mapped `::ffff:192.0.2.1`: `192.0.2.1`과 연결되지 않는 현재 동작이 유지된다
- [ ] `entity_value_sql`·`_BTRIM` 삭제 뒤 `src`·`tests`에서 참조가 없다
- [ ] 그래프 SQL의 인덱스 사전 필터 유무와, 있으면 `CASE`가 그것을 무력화하지 않는다는 확인 결과가 notes에 있다
- [ ] `docs/notes/356-l2-scenario-check.md`의 결함 행(1c2·1c4)이 "#358에서 해결"로 갱신됐다
- [ ] L2 담당 승인(받음)
- [ ] 새 환경변수 없음
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m db` 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록이 있다

## 토론으로 정한 것

- `entity_value_sql`은 호출자가 없는 죽은 코드라(#305 이후 #319가 호출을 지움) 이슈의 "함께 고칠지 검토"를 "삭제"로 바꾼다. 별도 커밋으로 분리한다.
- IP 판별은 `pg_input_is_valid(text, 'inet')`(PG 16 이상)로 한다. `compose.yaml`과 CI가 `postgres:17.6`으로 고정돼 있고 운영·개발 서버는 삭제됐으며 새 환경은 17.x로 맞출 예정이라서다. 16 미만이면 정규식 방식으로 바꿔야 한다.
- 마스크가 있는 값(CIDR)은 `inet` 비교에서 빼고 기존 `btrim` 문자열 비교를 쓴다. 파이썬 `normalize_entity_value`의 `ip_address`도 CIDR를 거부하므로 같은 결과다.
- IPv4-mapped는 지금처럼 IPv4와 다른 값으로 둔다(파이썬·`inet` 모두 같음).
- L2 담당 승인은 담당 본인이 이미 했다(2026-11-20, 댓글 없이 진행).
- #356 기록의 결함 행을 이 이슈에서 "#358에서 해결"로 갱신한다. 사람이 정했다. `AGENTS.md` 원칙 8(지난 기록은 고쳐 쓰지 않는다)과 `docs/notes/README.md`("오타와 깨진 링크만 예외")에서 벗어나는 예외이므로, 갱신은 위 두 행과 결함 항목에 한정하고 나머지는 고치지 않는다.
- 그래프 SQL에 인덱스를 타는 사전 필터가 있으면 새 `CASE`가 그것을 무력화하지 않는지 개발 단계에서 확인하고 결과를 notes에 적는다.
- 성능(대량 데이터)은 측정하지 못했다(아래 "확인하지 못한 것").
- `docs/decisions.md`에 올릴 새 결정은 없다.

## 확인하지 못한 것

- 행마다 `pg_input_is_valid`와 `inet` 변환이 들어가는 쿼리의 대량 데이터 성능을 측정하지 못했다(#305 기록의 같은 경고).
- 실제 IPv6 알럿 비율은 측정하지 않았다.
- 새 환경의 Postgres 버전(17.x 전제). 17.x가 아니면 `pg_input_is_valid`가 없을 수 있어 쿼리가 오류가 난다.
- `pg_input_is_valid(…, 'inet')`가 `1.2.3` 같은 값을 받아들이는지는 로컬 DB로 확인하지 않았다. 개발 단계에서 샘플로 확인하고 예상과 다르면 "바뀐 점"에 적는다.

## 바뀐 점

