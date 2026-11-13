---
issue: 305
date: 2026-11-13
owner: Juhyeok0603
supersedes: []
---

# L2 주변 기록 조회가 대소문자·공백이 다른 엔티티를 못 찾는다

## 목표

`_related`가 저장된 엔티티 원본을 조회 엔티티와 같은 규칙으로 비교한다. 대소문자가 섞인
host·user·domain과 흔한 앞뒤 공백 때문에 빠지던 Alert·Event를 주변 기록에 포함한다.
저장 값과 기존 데이터는 바꾸지 않는다.

## 방법

1. 손으로 만든 샘플과 테스트를 먼저 작성해 현재 조회에서 매치가 빠지는 것을 확인한다.
2. `src/soc/entities.py`에 `normalize_entity_value`와 같은 비교 규칙의 SQL 식을 돌려주는
   `entity_value_sql(entity_type)`을 추가한다. `_related`는 시드 엔티티 타입으로 그 식을
   받아 `EXISTS` 조건에 넣는다.

   ```python
   _BTRIM = r"btrim(item->>'value', E' \t\n\r\f\v')"


   def entity_value_sql(entity_type: str) -> str:
       """normalize_entity_value와 같은 비교 규칙의 SQL 식. ip 정규형은 맞추지 않는다."""
       return f"lower({_BTRIM})" if entity_type in _LOWER_TYPES else _BTRIM
   ```

   `EXISTS`에는 이미 `item->>'type' = %s`가 있으므로 SQL 안의 타입별 `CASE`는 필요하지 않다.
3. 오른쪽 인자는 기존처럼 `normalize_entity_value(type, value)`의 결과를 쓴다. 소문자 적용
   타입 목록은 `soc.entities._LOWER_TYPES` 하나뿐이라 SQL 쪽 목록과 갈라질 수 없다.
   `url`·`process`는 대소문자를 구분한다.
4. 실제 PostgreSQL 조회 테스트로 매칭을 확인한다. 기본 `uv run pytest`는 `db` 표식 테스트를
   제외하므로 해당 테스트를 별도로 실행한다.

`btrim`은 지정한 스페이스·탭·줄바꿈·캐리지 리턴·폼 피드·세로 탭을 제거한다. Python
`strip()`이 처리하는 모든 Unicode 공백과 완전히 같지는 않다.

## 바꿀 곳

- `src/soc/entities.py`: `normalize_entity_value` 옆에 `entity_value_sql()` 추가.
- `src/soc/l2/analyze/context.py`: `_related`의 비교 식에 함수 결과 사용.
- `tests/fixtures/l2/`: 대소문자 혼용·앞뒤 공백·대소문자를 구분해야 하는 값의 손 작성 샘플.
- `tests/test_l2_analyze.py`: `entity_value_sql`의 타입별 반환 식 검사.
- `tests/test_l2_branch_db.py`: Alert·Event의 실제 SQL 매칭과 기존 주변 기록 선택 동작 검사.

## 다른 코드와 맞물리는 곳

`_related`를 소비하는 L2 조사 입력에 이전에는 빠졌던 주변 기록이 들어올 수 있다. 기존의
4버킷 선택, 엔티티당 몫, 전체 80건 상한과 출력 형태는 유지한다. 계약·테이블·마이그레이션·
설정·API·화면은 바꾸지 않는다.

## 범위 밖

- 저장 값 정규화와 기존 데이터의 소급 변경.
- 비표준 IP 표기의 동일성 비교. 앞뒤 공백은 제거하지만 IPv6 축약형 등은 맞추지 않는다.
- 지정한 여섯 종류 외의 Unicode 공백과 DB collation에 따른 비ASCII 대소문자 차이.
- `_related`의 샘플링 방식과 #304의 역방향 체인 작업.

## 완료 기준

- [ ] 대소문자가 섞인 host·user·domain 값이 `_related`에서 매치한다.
- [ ] 앞뒤에 스페이스·탭·줄바꿈 등 지정한 공백이 붙은 값이 매치한다.
- [ ] `url`·`process`는 대소문자를 구분한다. 예를 들어 `/Admin`과 `/admin`을 같게 취급하지 않는다.
- [ ] 기존 4버킷 균등 선택, 엔티티당 몫, 전체 80건 상한 테스트가 통과한다.
- [ ] 계약·마이그레이션·API·화면 변경이 없다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과한다.
- [ ] 임시 PostgreSQL에서 관련 `db` 표식 테스트가 통과한다.

## 토론으로 정한 것

- 닫힌 #304의 계획만 담긴 브랜치는 이어 쓰지 않는다. #305가 매칭 수정을 전담하고,
  체인 작업은 필요해지면 새 이슈에서 계획한다.
- 이슈 본문의 한 인자 `btrim()`에 `E' \t\n\r\f\v'` 인자를 추가한다. 타입별 분기는
  SQL `CASE` 대신 Python에서 고른다. `EXISTS`가 이미 타입을 묶으므로 쿼리 안에서 분기
  결과는 일정하고, 타입 목록은 `_LOWER_TYPES` 한 곳에만 남는다.
- IP 정규형 비교는 제외한다. 잘못된 IP 값을 `inet`으로 변환하면 조회 전체가 실패할 수 있다.
- "GIN 인덱스가 없어 반드시 순차 스캔하므로 비용이 없다"는 근거는 쓰지 않는다. 엔티티 값의
  인덱스 경로를 잃지는 않지만 행별 문자열 처리 비용은 추가된다.
- 새 도구나 팀 공통 결정은 없다.

## 바뀐 점
