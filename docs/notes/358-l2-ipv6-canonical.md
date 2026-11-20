---
issue: 358
date: 2026-11-20
owner: Pandyo
plan: 358-l2-ipv6-canonical.md
supersedes: []
---

# L2 그래프가 표기만 다른 같은 IPv6를 같은 IP로 연결한다 (#356의 결함 1c2·1c4 해결)

## 한 일

`graph.py`의 `_GRAPH_QUERY`가 `ip` 엔티티를 비교할 때, 마스크(`/`)가 없고 `pg_input_is_valid(…, 'inet')`가 참인 값끼리는 `inet`으로 비교한다. 그래서 저장 값이 `2001:0DB8:0:0:0:0:0:50`처럼 비정규 표기여도 지금 Ticket의 `2001:db8::50`과 이어진다. IP로 읽지 못하는 값이나 마스크가 붙은 값은 전과 같이 `btrim` 문자열 비교를 쓰고 쿼리는 오류를 내지 않는다. 호출하는 곳이 없던 `entity_value_sql`과 `_BTRIM`은 지웠다(별도 커밋). #356의 1c2·1c4는 `일치`로 바꿔 strict xfail을 지웠다.

## 계획과 달라진 점

없음. 샘플 이름은 `1d1`~`1d12`로 붙였다.

## 다음 사람이 알아야 할 것

- **`pg_input_is_valid`는 PostgreSQL 16 이상에서만 있다.** `compose.yaml`과 CI는 `postgres:17.6`이다. 새 환경이 17.x가 아니면 그래프 SQL이 오류를 낸다. 새 환경의 버전은 이 레포에서 확인할 수 없다.
- **`1.2.3`은 `inet`으로 유효하지 않다**(`pg_input_is_valid('1.2.3','inet')`가 거짓. 로컬 17.6에서 확인). 포트 붙은 값(`192.0.2.1:443`)과 앞뒤 공백이 남은 값도 같다(공백은 `btrim` 뒤에 검사한다). 마스크가 있는 값(`2001:db8::50/64`)은 `inet`으로는 유효하지만 일부러 `inet` 비교에서 뺐다.
- **`::inet` 변환은 `CASE`의 `WHEN`이 참인 가지에서만 계산된다.** `AND` 안의 항목은 계산 순서가 보장되지 않으므로 검사식(`pg_input_is_valid`)은 변환이 아니라 조건에만 두었다. 이 구조를 풀면 잘못된 문자열이 쿼리 전체를 오류로 만든다.
- **IPv4-mapped(`::ffff:192.0.2.1`)는 IPv4(`192.0.2.1`)와 다른 값이다.** 파이썬 `ipaddress`(3.13)와 Postgres `inet` 모두 같다. 이어 주려면 규칙 변경이다. 이번에는 현재 동작을 유지하는지만 테스트로 고정했다(1d10·1d11).
- **IP가 아닌 `ip` 값의 대소문자는 여전히 다르다.** 파이썬은 `lower()`하고 SQL은 `lower()`하지 않는다. 범위 밖으로 두었다.
- `entity_value_sql`은 #305가 `_related`용으로 만들고 #319가 호출을 지운 뒤 호출자가 없었다(`src`·`tests`·`scripts` 검색). 문서(`docs/plans/305…`, `docs/notes/305…`)의 언급은 지난 기록이라 고치지 않았다.
- 실제 IPv6 알럿 비율과 대량 데이터 성능은 측정하지 못했다. 행마다 `pg_input_is_valid`와 `inet` 변환이 들어간다.
- #356 기록(`docs/notes/356-l2-scenario-check.md`)의 1c2·1c4 두 행과 "다음 사람이 알아야 할 것"의 결함 항목만 "#358에서 해결"로 갱신했다. 사람이 정한 예외다(계획의 "토론으로 정한 것").

## 인덱스 사전 필터 확인

그래프 SQL에서 엔티티 값에 걸린 인덱스는 없다(`alerts`·`tickets`·`incidents`·`hunts`의 인덱스 중 `entities` jsonb 값에 대한 것이 없다). 인덱스를 타는 필터는 모두 `peers` 절에 있다(`incidents_status_idx`, `tickets_status_idx`, `alerts_pkey`, `hunts_pkey`). 새 `CASE`는 그 뒤 `matches` 절의 엔티티 비교에만 들어간다.

임시 DB에 케이스 1c2를 채우고 `enable_seqscan = off`로 바꾼 뒤 변경 전후 `EXPLAIN (COSTS OFF)`를 비교했다. 달라진 줄은 `Join Filter` 한 줄(새 `WHEN` 가지)뿐이고 `Index Cond`와 인덱스 스캔 노드는 같다. 즉 `CASE`가 인덱스를 무력화하지 않는다. 데이터가 몇 행뿐이라 계획의 비용이나 실제 시간은 의미가 없고 구조만 비교한 것이다.

## 확인 방법

- (#351 머지(`b90cbe1`) 위로 rebase한 뒤 다시 실행한 결과다. 충돌은 없었다.)
- `uv run ruff format --check .`: 467개 통과. `uv run ruff check .`: 통과.
- `uv run pytest`: 2652개 통과, 660개 제외.
- `uv run pytest -m db`(로컬 Postgres 17.6 컨테이너, 임시 DB를 만들고 지움): 623개 통과. 로컬 `.env`의 DB 이름이 컨테이너에 없어 DB 이름만 `postgres`로 바꿔 접속했다.
- 구현 전에 새 샘플을 넣은 `tests/test_l2_scenarios_db.py`를 돌려 4개 실패를 확인했다(1c2, 1c4, 1d9, 1d12). 나머지 새 샘플(오류 없이 문자열 비교로 되돌아가는 값, 연결되면 안 되는 값)은 구현 전에도 통과해 구현 뒤에도 같은 결과로 고정한다.
- 주요 테스트: `test_scenario_matches_the_graph_rules[1c2-ipv6-stored-noncanonical]`, `[1c4-ipv6-through-normalizer]`, `[1d1-not-an-ip-same-string]`~`[1d12-ipv4-mapped-same]`.
- `pg_input_is_valid` 직접 확인(로컬 17.6): `not-an-ip`·빈 문자열·`1.2.3`·`192.0.2.1:443`은 거짓, `2001:db8::50/64`·`2001:0DB8:0:0:0:0:0:50`·`::ffff:192.0.2.1`은 참.
