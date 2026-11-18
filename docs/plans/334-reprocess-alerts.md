---
issue: 334
date: 2026-11-18
owner: Pandyo
supersedes: []
---

# 기존 알럿을 id를 유지한 채 다시 정규화하는 재처리 명령

## 목표

`python -m soc.normalize reprocess`로 이미 정규화된 알럿을 새 로직으로 다시 처리한다. 알럿 `id`·`raw_id`·`triage`와 연결된 Ticket은 바꾸지 않고, 정규화가 만드는 값만 갱신한다. 평소 정규화(`run`)는 그대로 새 행을 INSERT한다.

## 방법

1. **테스트 먼저.** `tests/fixtures/normalize/`의 손으로 만든 샘플로 옛 형식 알럿(`outcome` NULL, ModSecurity dst 없음)을 DB에 넣고, 재처리 전후를 비교하는 DB 테스트를 먼저 쓴다.
2. **명령.** `soc.normalize`에 `reprocess` 하위 명령을 더한다. 옵션은 `--source`, `--since`, `--limit`, `--dry-run`이다. 설정(`Settings`)·연결·매핑표 로드는 `run`과 같은 것을 쓴다.
3. **대상 선택.** 임대 경로(`claim_*_batch`)는 쓰지 않는다. `alerts`와 `normalize_status`를 직접 읽는다. 대상은 `normalize_status.result_kind = 'alert'`이고 `result_id`가 있는 행이다(pending·failed 제외).
   - 기본: `outcome IS NULL`.
   - `--source`를 주면 `outcome`과 관계없이 모든 알럿을 읽고, 새 결과의 `source`로 정규화한 뒤에 거른다(저장된 `source`가 NULL인 옛 행도 고를 수 있다).
   - `--since`는 `alerts.time` 기준이다. `--limit`은 읽은(정규화한) 행 수이고, 순서는 `alerts.time`, `id` 오름차순이다.
4. **행마다 처리.** 행 하나마다 트랜잭션을 연다. 알럿 행과 `normalize_status` 행을 `FOR UPDATE`로 잠그고, 원본(`raw_records.original_text`)을 `normalize`와 `run._checked_row`로 다시 정규화(변환·OCSF·계약 검증·마스킹)한 뒤 아래 규칙으로 비교·갱신한다.
   - 새 결과가 폴백이거나 오류면 건너뛴다(기존이 `fallback`이어도 같다).
   - 기존 `outcome`이 있고 새 `outcome`이 `ok > partial > fallback` 순서에서 낮아지면 건너뛴다. 기존이 NULL이면 비교 없이 갱신한다.
   - 갱신 컬럼 `time`, `severity`, `title`, `rule_id`, `entities`, `ocsf`, `details`와 `normalize_status`의 `outcome`, `source`, `missing_fields`, `error_code`를 새 값과 비교해 달라진 행만 UPDATE한다. `assets`는 `entities`가 바뀐 행만 다시 조회해 함께 갱신한다.
   - `id`, `raw_id`, `triage`와 `status`, `result_id`, `result_kind`, 임대·시도 컬럼은 건드리지 않는다.
   - 같은 `raw_id`의 `result_id`가 아닌 알럿은 갱신하지 않고 수만 보고한다.
5. **`--dry-run`.** 어떤 테이블에도 쓰지 않는다. 소스별로 바뀔 건수, 바뀌는 컬럼 이름, 엔티티 type·role 추가/제거 건수만 출력한다. 원문 값은 출력하지 않는다.
6. **출력과 종료 코드.** 소스별 읽음·갱신·변경 없음·건너뜀(사유별)·오류 건수와 중복 알럿 수를 출력한다. 건너뜀은 종료 코드 0이다. 행 하나의 DB 오류는 그 행만 롤백하고 계속하며, 오류 건수를 출력하고 종료 코드 1로 끝낸다. 설정·환경변수 오류는 2다(`run`과 같다).

## 바꿀 곳

- `src/soc/normalize/reprocess.py`(새): 대상 선택, 행 단위 비교·갱신, 집계
- `src/soc/normalize/__main__.py`: `reprocess` 하위 명령과 옵션, 출력
- `src/soc/normalize/run.py`: `_checked_row` 재사용(동작 변경 없음)
- `tests/normalize/`, `tests/fixtures/normalize/`: 재처리 테스트와 샘플
- `docs/decisions.md`: D-063

## 다른 코드와 맞물리는 곳

- `alerts`의 `entities`·`title` 등이 바뀌면 L1·L2·L3가 읽는 값이 바뀐다. `entities`가 바뀌어도 이미 만든 Incident·그래프 묶음은 다시 만들지 않는다(D-027, 소급 변경 없음).
- 유사 사례·분기 임베딩(`similar/index.py`, `l2/branch/embed.py`)은 갱신하지 않아 옛 `title`·엔티티 기준일 수 있다. 개발 기록에 적는다.
- `alerts.triage`는 L1(`l1/judge.py`, `l1/ticketing.py`)이 UPDATE한다. 재처리는 `triage`를 쓰지 않고 행 잠금으로 순서만 맞춘다.
- `run`의 잠금(`_LOCK_HELD`)은 `status <> 'succeeded'`만 잡는다. 재처리 대상은 모두 `succeeded`라 겹치지 않는다.
- 새 환경변수·설정 키·테이블·계약 변경은 없다.

## 범위 밖

- Event 재처리
- `alerts.raw_id` 유니크 제약 추가, 중복 알럿 정리
- 이미 만든 Incident·그래프 연결과 임베딩의 재계산
- 정규화 로직 자체의 변경, 일반 정규화 흐름(`run`)의 쓰기 동작 변경

## 완료 기준

- [ ] `reprocess`가 기존 알럿의 정규화 컬럼을 갱신하고, 알럿 `id`·`raw_id`·`triage`·연결된 Ticket은 바꾸지 않는다는 DB 테스트가 있다.
- [ ] 재처리 전후로 `alerts`와 `tickets` 행 수가 같다는 테스트가 있다.
- [ ] 같은 명령을 두 번 실행하면 두 번째는 변경이 0건이다.
- [ ] `--dry-run`은 어떤 테이블에도 쓰지 않는다는 테스트가 있다.
- [ ] 새 결과가 폴백이거나 오류인 행은 갱신하지 않고 건너뛴 건수가 출력된다는 테스트가 있다.
- [ ] 기존 `outcome`보다 낮아지는 결과는 건너뛰고, 기존이 NULL이면 비교 없이 갱신한다는 테스트가 있다.
- [ ] `--source`가 새 결과의 `source`로 대상을 고르고(`source`가 NULL인 옛 행 포함), `outcome`이 있는 행은 달라진 것만 갱신한다는 테스트가 있다.
- [ ] Event 행은 `alerts`·`normalize_status`·`events` 어디에서도 바뀌지 않는다는 테스트가 있다.
- [ ] `outcome`, `source`, `missing_fields`, `error_code`가 갱신된다.
- [ ] 같은 `raw_id`의 `result_id`가 아닌 알럿은 갱신하지 않고 수만 보고한다는 테스트가 있다.
- [ ] 행 하나의 DB 오류가 다른 행의 갱신을 막지 않고 종료 코드 1이 된다는 테스트가 있다.
- [ ] 일반 정규화(`run`)의 동작과 기존 테스트가 변경 없이 통과한다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과한다.
- [ ] 개발 DB 사본에서 실행한 건수 결과(소스별 변경·건너뜀)를 PR에 적었다(사람이 돌려 알린다).

## 토론으로 정한 것

답은 2026-11-18에 사람이 정했다.

- **기본 대상과 `--source`.** 기본은 `result_kind='alert'` + `outcome IS NULL`이다. `--source`를 주면 `outcome`과 관계없이 그 소스의 모든 알럿이 대상이다. 서버에서 #326 이후 #332 이전에 처리된 ModSecurity 4건이 `outcome=ok`인데 dst가 없다는 것을 확인했기 때문이다. 이슈는 기본 대상만 말했다.
- **`--source`는 새 결과의 `source`로, 정규화 뒤에 거른다.** 옛 행은 저장된 `source`가 NULL이라서다. 새 `source`가 기존과 다르면 `source`도 갱신한다. `--limit`은 읽은(정규화한) 행 수이고 순서는 `alerts.time`, `id` 오름차순이다. `--since`는 `alerts.time` 기준이다.
- **낮아지는 결과는 건너뛴다.** 이슈는 폴백·오류만 건너뛰었다. 기존 `outcome`이 있으면 `ok > partial > fallback` 순서에서 낮아질 때도 건너뛴다. 기존이 NULL이면 비교 없이 갱신하고, 기존·새 결과가 모두 `fallback`이면 건너뛴다.
- **갱신하는 알럿은 `result_id`가 가리키는 한 건.** 같은 `raw_id`의 나머지는 수만 보고한다. `result_id`가 없는 행(pending·failed)은 대상이 아니다.
- **임베딩은 갱신하지 않는다.** 옛 `title`·엔티티 기준일 수 있음을 개발 기록에 적는다.
- **달라진 행만 UPDATE.** 갱신 컬럼 전체와 `normalize_status` 3개를 새 값과 비교한다. `assets`는 `entities`가 바뀐 행만 다시 조회한다. `ocsf`·`details`에 실행마다 달라지는 값이 있어 "두 번째 실행은 0건"이 깨지면 계획의 "바뀐 점"에 적고 멈추며, 그 필드를 비교에서 제외할지 사람이 정한다.
- **종료 코드.** 건너뜀은 0이다. 행 단위 DB 오류는 그 행만 롤백하고 계속하며 종료 코드 1이다.
- **임대 경로를 쓰지 않는다.** `claim_*_batch`는 Alert·Event를 구분하지 않고 `status`·임대 컬럼을 바꾼다. `alerts`와 `normalize_status`를 직접 읽고, 같은 트랜잭션에서 `FOR UPDATE`로 잠근 뒤 비교·갱신한다.
- **`--dry-run` 출력.** 건수, 바뀌는 컬럼 이름, 엔티티 type·role 추가/제거만 낸다(원문 값 없음).
- **결정 목록.** D-063을 추가한다.

## 바뀐 점

