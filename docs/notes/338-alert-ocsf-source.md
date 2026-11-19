---
issue: 338
date: 2026-11-18
owner: Pandyo
plan: 338-alert-ocsf-source.md
supersedes: []
---

# Alert 저장 구조: ocsf를 원본으로, 파생 컬럼은 단일 함수로

## 한 일

`mapping.py`에 `finding_ocsf`(2004 문서 만들기), `derive_columns`(ocsf → `time`·`severity`·`title`·`rule_id`), `alert_row`(행 만들기), `with_derived_columns`(ocsf만 가진 행에 컬럼 채우기)를 두었다. 정규화(`_finding`·`fallback_alert`)와 시드 3종이 같은 함수를 쓴다. `observables`·`evidences`는 entities에서만 만든다. `evidences`는 엔티티 하나당 요소 하나이고 `ip`/`src`·`ip`/`dst`·`user`/`actor`·`domain`/`dst`·`url`/`dst`만 대응하며 `target`·null role은 뺀다. `reprocess --all`은 `outcome`이 있는 행도 읽는다. 마이그레이션 `0303`은 `alerts.ocsf`의 `class_uid`를 2004 또는 0으로 제한한다. 재처리는 `reprocess`가 이미 `ocsf`·`title`·`time`·`severity`·`rule_id`를 갱신하므로 코드 변경 없이 새 파생 결과를 쓴다.

## 계획과 달라진 점

- 계획 "다른 사람 파일 변경"에 없던 소비자가 있었다. `tests/test_l3_dev_seed_db.py`(`l3_hunt/seed.json`을 직접 읽음)와 프런트엔드 테스트 3개(`frontend/src/test-utils.tsx`, `App.test.tsx`, `incident-graph.test.tsx`가 `ui_seed.json`을 import). 프런트 테스트는 알럿 컬럼을 읽지 않아 그대로 통과한다(vitest 86건). `test_l3_dev_seed_db.py`는 파생 컬럼을 채우도록 고쳤다.
- 시드 4종 중 고정 시각 픽스처(`ui_seed.json`, `l3_hunt/seed.json`)는 컬럼을 지우고 `ocsf`만 두며, 읽는 쪽(`api/dev_seed.py`, `test_api_ui.py`, `test_l3_hunt_db.py`, `test_l3_dev_seed_db.py`)이 `with_derived_columns`로 컬럼을 채운다. 계약 검증은 채운 뒤에 한다.
- 정규화 결과의 `title`은 `mask_headers`를 거친 `ocsf`에서 파생한다(이전엔 거치기 전 값). 규칙이 `title`이 헤더 모양 텍스트일 때만 다르며 샘플 18건에는 차이가 없다.

## 다음 사람이 알아야 할 것

- `evidences`가 늘어 에이전트 도구 `get_alert`가 모델에게 주는 `ocsf`가 바뀐다. `alert_skeleton.json` 기준 폴백을 뺀 13건의 `evidences` 요소 수: suricata 6건(0개 3, 4개 3), modsecurity 2건(3개), guardduty 4건(1개 1, 2개 3), unknown 1건(1개). L1·L2·L3 담당자 확인이 필요하다.
- CHECK `alerts_ocsf_class_check`는 `class_uid`가 없는 옛 행(NULL)을 통과시킨다. 일부러 막지 않았다(재처리 테스트가 `ocsf = '{}'`인 옛 행을 만든다).
- 파생 컬럼 `severity`는 `severity_id` 99(Other)를 0으로 접는다. 현재 정규화는 알럿에서 99를 만들지 않는다.
- 이미 저장된 알럿에 새 `evidences`·`observables`를 반영하려면 머지 후 개발 DB 사본에서 `uv run python -m soc.normalize reprocess --all`(먼저 `--dry-run`)을 돌린다. 이 개발에서는 개발 DB에 쓰지 않았다. 임베딩·Incident·그래프 묶음은 다시 만들지 않는다(D-063).
- 로컬 `.env`의 `DATABASE_URL`이 가리키는 `zt_dev`가 컨테이너에 없다(`zt`가 있다). DB 테스트는 `DATABASE_URL`의 DB 이름만 `zt`로 바꿔 돌렸고, 테스트는 임시 DB를 만들고 지운다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`(2195건 통과)
- DB 테스트: `-m "db and not qdrant and ..."` 534건 통과(재처리 `--all`, `class_uid` CHECK, 마이그레이션 목록 포함)
- 프런트: `npx vitest run` 86건 통과(변경 없음)
- 일치 검사: `tests/normalize/test_alert_columns.py`(샘플 18건 전체와 시드 4종)
