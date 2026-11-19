---
issue: 338
date: 2026-11-18
owner: Pandyo
supersedes: []
---

# Alert 저장 구조 정리: ocsf 문서를 원본으로, 파생 컬럼은 단일 쓰기 함수로

## 목표

`alerts.ocsf`를 순수 OCSF 1.9.0 문서(Detection Finding 2004, 폴백은 Base Event 0)로 두고 원본으로 삼는다. `title`·`time`·`severity`·`rule_id` 컬럼은 `ocsf`에서 파생하는 함수 한 곳(`mapping.py`)만 만들고, 정규화·재처리·시드 3종이 모두 이 함수를 쓴다. `entities`는 분석용 원본이고 `observables`·`evidences`는 entities에서만 만든다. 공통 계약(Alert)과 읽는 쪽 코드는 바꾸지 않는다.

## 방법

1. **샘플과 테스트 먼저.** 소스별 샘플은 `tests/fixtures/normalize/alert_skeleton.json`(18건: suricata 6, modsecurity 2, guardduty 4, unknown 1, 폴백 5)을 그대로 쓴다. 새 샘플과 실데이터 원본은 만들거나 커밋하지 않는다. 기대값을 먼저 쓰고 실패하는 것을 확인한 뒤 구현한다.
   - 일치 검사(DB 없는 단위 테스트, 위 18건 전체): `entities`와 `observables`·`evidences`, 파생 컬럼과 `ocsf` 값이 어긋나면 실패한다. 시각은 `start_time` 기준으로 비교한다(`ocsf.time`은 생성 시각이라 컬럼과 다른 것이 정상).
   - `details` 검사: OCSF 속성 이름과 같은 키가 없다(`ocsf`는 기존대로 OCSF 1.9.0 검증, unknown 키 0건).
   - 합성 `ocsf` 단위 테스트: `severity_id` 99는 컬럼 0으로 접힌다. 현재 정규화는 알럿에서 99를 만들지 않는다(`SEVERITY_IDS`는 2~5, 없으면 0).
2. **파생 함수.** `mapping.py`에 함수를 둔다.
   - `ocsf`에서 컬럼을 파생: `time` = `start_time`(없으면 `time`), `title` = `finding_info.title`(없으면 `message`), `rule_id` = `finding_info.analytic.uid`(없으면 null), `severity` = `severity_id`(99는 0).
   - entities에서 `observables`·`evidences`를 만든다. 같은 `(type, 값)`은 한 번만 둔다. 다른 컬럼 값은 만들지 않는다.
3. **`evidences` 규칙.** 엔티티 하나당 요소 하나다.

   | 엔티티 | 요소 |
   |---|---|
   | `ip`/`src` | `{src_endpoint: {ip}}` |
   | `ip`/`dst` | `{dst_endpoint: {ip}}` |
   | `user`/`actor` | `{actor: {user: {name}}}` |
   | `domain`/`dst` | `{dst_endpoint: {domain}}` |
   | `url`/`dst` | `{url: {url_string}}` |

   role이 `target`이거나 null이거나 위 표에 없는 type은 `evidences`에서 제외하고 `observables`와 entities에는 유지한다. 중복 제거 키는 `(속성, 값)`이다. 기존 `destination.ip` 단일 dst 출력은 같은 모양으로 유지된다.
4. **쓰기 지점 통일.** 정규화(`store.py`), 재처리(`reprocess.py`), 시드 3종(`agent/dev_l1.py`, `l3/hunt/dev_seed.py`, `api/dev_seed.py`)이 같은 파생 함수를 쓴다. `_finding`·`fallback_alert`의 행 만들기도 이 함수를 거친다. 비OCSF 값은 `details`에 둔다.
5. **재처리 확장.** `reprocess`에 기존 행 전체를 대상으로 하는 옵션을 더한다. 대상은 이 옵션이 있으면 `outcome`과 관계없이 모든 알럿이고, 폴백 결과와 `outcome` 하락은 기존대로 건너뛰며 건수를 출력한다. 알럿 id·`raw_id`·`triage`·`assets`는 바꾸지 않는다. 적용은 머지 후 사람이 개발 DB 사본에서 돌리고 소스별 건수를 PR 초안에 적는다.
6. **마이그레이션.** `0303_alert_ocsf_class.sql`: `alerts`에 `CHECK (ocsf ->> 'class_uid' IN ('2004', '0'))`를 더한다. `severity` CHECK(0~6)는 그대로 둔다. 생성 컬럼은 쓰지 않는다. 기존 행이 어긋나면 마이그레이션 전에 알리고 멈춘다.
7. **시드 픽스처.**
   - `tests/fixtures/l1_e2e/dev_seed.json`, `tests/fixtures/l3_hunt/dev_seed.json`: `ago_ms`는 유지하고 `title`·`severity`·`rule_id`·`time` 컬럼 값은 지운다. `ocsf`는 OCSF 검증을 통과하는 형태로 보강한다. 시드 코드가 `now - ago_ms`로 `ocsf.start_time`과 `time`을 채우고 파생한다.
   - `tests/fixtures/api/ui_seed.json`(알럿 7건), `tests/fixtures/l3_hunt/seed.json`(알럿 1건): `ago_ms`가 없고 시각이 고정이다. 컬럼 값을 지우고 `ocsf.start_time`·`time`에 고정 시각을 넣는다. `api/dev_seed.py`는 기존 행이 샘플과 다르면 되돌리므로 파생 결과가 매번 같아야 한다. `ui_seed.json`의 최상위 `src_endpoint`·`dst_endpoint`는 `evidences`로 옮긴다.
8. **결정 기록.** `docs/decisions.md`에 D-065를 더한다. D-059의 시각·`rule_id` 규칙은 유지하고, D-062의 "`evidences`는 `destination.ip`로 채우는 그대로"와 D-063의 "`ocsf`·`details` 갱신" 서술 중 해당 부분을 대체한다.

## 바꿀 곳

- `src/soc/normalize/mapping.py`: 파생 함수, `evidences` 규칙, `_finding`·`fallback_alert`
- `src/soc/normalize/store.py`, `src/soc/normalize/reprocess.py`, `src/soc/normalize/__main__.py`: 파생 함수 사용, 재처리 전체 대상 옵션
- `src/soc/agent/dev_l1.py`, `src/soc/l3/hunt/dev_seed.py`, `src/soc/api/dev_seed.py`: 시드가 파생 함수 사용
- `src/soc/db/migrations/0303_alert_ocsf_class.sql`
- `tests/normalize/`: 일치 검사, `details` 검사, `severity` 99 접힘, 재처리 옵션. 깨지는 정규화·DB 테스트 정리
- `docs/decisions.md`, `docs/plans/338-alert-ocsf-source.md`, 개발 중 `docs/notes/338-alert-ocsf-source.md`

## 다른 코드와 맞물리는 곳

**다른 사람 파일 변경.** 아래는 L1·L2·L3 담당자가 쓰거나 읽는 것이라 PR 전에 담당자 확인을 받는다.

- 시드 픽스처 4개: `tests/fixtures/l1_e2e/dev_seed.json`, `tests/fixtures/l3_hunt/dev_seed.json`, `tests/fixtures/api/ui_seed.json`, `tests/fixtures/l3_hunt/seed.json`
- 시드 코드 3개: `src/soc/agent/dev_l1.py`, `src/soc/l3/hunt/dev_seed.py`, `src/soc/api/dev_seed.py`
- 시드를 쓰는 테스트: `tests/test_api_ui.py`, `tests/test_api_db.py`, `tests/test_agent_dev_l1.py`, `tests/test_l3_dev_seed.py`, `tests/test_l3_dev_seed_db.py`, `tests/test_l3_hunt_db.py`. 알럿의 `title`·`severity`·`rule_id`를 픽스처 값과 직접 비교하는 단언은 찾지 못했다. 시각(`test_agent_dev_l1.py:151`, `test_l3_dev_seed.py:90`)과 엔티티(`test_l3_hunt_db.py:48`) 단언만 있고, 깨지는 것만 고친다. 실행 결과로 범위를 확정한다.
- `alerts.ocsf` 내용: 에이전트 도구 `get_alert`(`src/soc/tools/internal.py`)가 `ocsf` 전체를 모델에게 돌려준다. `evidences`에 src·actor·domain·url 요소가 더해지고, ModSecurity는 dst 요소가 `destination.ip`·`host_ip`·`request.hostname` 기준으로 늘 수 있다. 건수를 PR 초안에 적는다.
- Alert 계약(`contracts/alert.schema.json`)과 컬럼 이름·타입은 바뀌지 않는다.

## 범위 밖

- 생성 컬럼(PostgreSQL), `severity` CHECK 범위 변경, 계약 변경
- `alerts`를 비우고 새 id로 재수집하는 방식(재처리로 대신한다)
- 임베딩·Incident·그래프 묶음의 재생성(D-063 그대로)
- Event 정규화 변경

## 완료 기준

- [ ] 결정 기록: 문서 원본 / 파생 컬럼 / entities 원본 / `details` 용도 / 폴백 파생 규칙(D-065, D-059·D-062·D-063 해당 부분 대체)
- [ ] 파생 함수 한 곳이 `title`·`time`·`severity`·`rule_id`를 만들고(폴백 포함) 정규화·재처리·시드 3종이 모두 이를 사용
- [ ] entities → `observables`·`evidences` 규칙(`ip`/`src`·`ip`/`dst`·`user`/`actor`·`domain`/`dst`·`url`/`dst`, role `target`·null 제외, 중복 제거)이 코드와 테스트로 고정됨
- [ ] 일치 검사 테스트(DB 없음, `alert_skeleton.json` 18건 전체, `start_time` 기준): entities와 `observables`·`evidences`, 파생 컬럼과 `ocsf` 값이 어긋나면 실패
- [ ] `ocsf`가 OCSF 1.9.0 검증 통과(unknown 키 0건). `details`에는 OCSF 속성 이름과 같은 키가 없음을 테스트로 확인
- [ ] `severity_id` 99가 컬럼 0으로 접히는 단위 테스트
- [ ] 새 마이그레이션(`class_uid` CHECK), 재처리 전체 대상 옵션으로 개발 DB 사본을 처리하고 소스별 결과 확인
- [ ] 시드 픽스처 4개와 시드 코드 3개가 파생 함수를 쓰고, 깨지는 정규화·DB·시드 테스트 정리
- [ ] 읽는 쪽(L1·L2·L3·UI)의 동작이 바뀌지 않았음을 확인. `ocsf` 안 `evidences` 변화 건수는 별도로 적는다
- [ ] L1·L2·L3 담당자 확인(PR 전)
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과

## 토론으로 정한 것

이슈 본문과 달라진 점:

- **재수집 방식**: "alerts를 비우고 재수집" 대신 `reprocess`를 확장해 id를 유지한 채 갱신한다. 새 id는 L1 판정·Ticket을 중복시킨다(D-063). 기존 행 전체를 대상으로 하는 옵션을 더한다.
- **`details` 검증**: 이슈의 "`details`도 OCSF 1.9.0 검증"은 `details`가 비OCSF 값을 두는 곳이라는 정의와 맞지 않아, "OCSF 속성 이름과 같은 키가 없음" 테스트로 바꿨다.
- **`severity`**: CHECK는 0~6 그대로(계약 변경 없음)이고 파생 시 `severity_id` 99는 0으로 접는다. 현재 정규화는 알럿에서 99를 만들지 않아 방어 규칙이다.
- **마이그레이션 범위**: 추가 CHECK는 `class_uid IN (2004, 0)`만이다. 생성 컬럼은 시드·테스트 INSERT를 깨뜨려 제외한다.
- **`evidences`**: 엔티티 하나당 요소 하나로 만든다. 이슈가 요구한 "entities에서 파생"을 따르되 기존 단일 dst 출력은 유지한다. D-062의 해당 서술을 대체한다.
- **시드**: 픽스처의 컬럼 값을 지우고 `ocsf`만 원본으로 둔다. `ago_ms`가 있는 픽스처는 시드 코드가 `now - ago_ms`로 시각을 채우고, 고정 시각 픽스처(`ui_seed.json`, `l3_hunt/seed.json`)는 `ocsf`에 고정 시각을 넣는다(제가 가정한 처리이고 사람이 이의 없이 확정).
- **일치 검사**: DB 없는 단위 테스트로 `alert_skeleton.json` 전체에 적용하고 `start_time` 기준으로 비교한다.
- **담당자 확인**: 시드 픽스처·시드 코드·시드 테스트와 `ocsf` 내용 변화를 PR 전 L1·L2·L3 담당자 확인 대상에 포함한다.

## 바뀐 점
