---
issue: 221
date: 2026-11-04
owner: Pandyo
plan: 221-threat-intel.md
supersedes: []
---

# 보안 뉴스·CISA KEV·ATT&CK을 명령 하나로 받아 L3 테이블에 저장하게 했다

## 한 일

L3 가설의 재료를 코드가 모은다. 에이전트는 웹에 접근하지 않는다(L3 위협 시나리오 입력, D-029).

- `uv run python -m soc.l3.intel`은 설정(`[l3.intel]`)의 출처를 차례로 받는다. 보안뉴스 RSS, The Hacker News RSS, CISA KEV를 받은 뒤 마지막에 ATT&CK Enterprise를 받는다. 출처마다 가져온 건수, 새로 저장한 건수, 갱신한 건수, 실패 종류만 출력한다. 실패한 출처가 있으면 나머지를 마친 뒤 종료 코드 1이다.
- 뉴스와 KEV는 `threat_news`에 들어간다. `(출처 이름, 출처 쪽 ID)`가 같으면 한 행이고, 제목·요약·링크·발행 시각이 달라졌을 때만 갱신한다(`updated_at`). ID는 L3 안에서만 쓰는 일련번호다.
- ATT&CK은 `attack_techniques`에 들어간다. 폐기·대체되지 않은 기법만 저장하고 버전마다 쌓는다. 같은 버전이 있으면 내려받지 않는다.
- 받을 때 리다이렉트를 따라가지 않는다. 크기 상한은 압축을 푼 바이트로 세고 출처별 전체 마감 시간을 둔다. DOCTYPE이 든 XML은 거부한다. 제목·요약은 태그와 제어 문자를 지운 평문으로 저장한다.
- L3 설정 로더 `soc.l3.config.load_config()`는 `{"l3": ...}`만 돌려준다.

## 계획과 달라진 점

- 계획에 없던 설정 검사를 더했다. 출처 주소는 `https://`만 받는다. 출처 이름은 겹치면 안 되고, `attack`은 ATT&CK 결과 줄 이름이라 쓸 수 없다. 설정이 틀리면 `ConfigError`로 멈추고 종료 코드 2다.
- DB 오류는 출처 실패 종류에 넣지 않았다. 출처 데이터는 저장 전에 모두 검사하므로 DB 오류는 환경 문제다. 그래서 수집을 멈추고, 예외 종류만 출력하고 종료 코드 1이다. 주소가 들어 있을 수 있어 예외 메시지는 출력하지 않는다.
- 모듈을 `errors`·`fetch`·`parse`·`clean`·`store`·`collect`로 나눴다.
- `tests/test_db_tables.py`에서 계획에 적은 테스트 말고도 `test_migrate_twice_does_not_reapply`의 `schema_migrations` 행 수 기대값을 2에서 3으로 바꿨다.
- 요약뿐 아니라 제목과 ATT&CK 기법 이름에도 같은 정리(`clean_text`)를 한다. 정리한 제목이 빈 RSS 항목은 버린다. KEV 항목의 제목이 비면 그 출처 전체를 `parse` 실패로 처리한다.
- RSS `pubDate`가 `-0000`(시간대 모름)이면 RFC 5322대로 UTC로 본다.
- ATT&CK은 컬렉션 객체가 정확히 하나여야 한다. 한 기법에 `mitre-attack` 참조가 여러 개이거나, 살아 있는 기법끼리 ID가 겹치면 `parse` 실패다.

## 다음 사람이 알아야 할 것

- **`uv.lock`은 최신 uv로 고친다.** 로컬 uv 0.6.6으로 `uv add`를 하면 lock 형식을 옛 방식으로 다시 써서 약 1700줄이 바뀐다. 이번에는 `uvx uv@latest add`(uv 0.13.7)로 넣어 `revision`이 3에서 5로 오르고 httpx·httpcore만 더해졌다. CI(setup-uv 최신)와 uv 0.6.6 모두 `uv lock --check`를 통과한다.
- **압축 폭탄은 조각 하나만큼은 메모리에 들어온다.** httpx는 받은 조각을 한 번에 풀기 때문에, 상한 검사는 푼 조각을 받은 다음에 일어난다. 64KiB 조각 하나가 크게 부풀면 상한을 넘은 만큼 잠깐 메모리를 쓴 뒤 끊는다. 전체 마감 시간도 조각 사이에서 확인하므로, 최대 읽기 제한 시간(10초)만큼 넘칠 수 있다.
- **태그처럼 보이는 글자가 남을 수 있다.** 실제 KEV 설명에 `If: <http://…` 같은 글자가 있다. HTML 태그가 아니라 문자열이라 그대로 남는다. 화면은 텍스트로만 보이므로(D-019) 문제없다. 반대로 KEV 설명에 `<b>`처럼 태그 모양의 글자가 있으면 지워진다.
- **이중 인코딩된 RSS 설명**(`&lt;em&gt;`)은 태그처럼 보이는 것이 남아 있으면 최대 3번까지 다시 푼다.
- **DOCTYPE 검사는 문서를 두 번 파싱한다.** 먼저 expat(DOCTYPE 핸들러)로 읽고, 그다음 ElementTree로 읽는다. RSS만 그렇고 크기가 작아 문제없다.
- **헌팅 코드(이후 이슈)가 볼 것**
  - ATT&CK은 버전마다 쌓이므로 `load_config()["l3"]["intel"]["attack"]["version"]`으로 골라 조회한다.
  - 뉴스는 다시 받으면 내용이 바뀔 수 있다. Hunt가 어떤 내용을 근거로 했는지 남기려면 그 시점의 제목·요약을 Hunt `details`에 복사한다. 뉴스는 `threat_news.id`(숫자)로 가리킨다.
  - 한 피드 안에 같은 guid가 두 번 나오면 두 번째는 내용이 다를 때 갱신 1건으로 센다.
- **#211(에이전트 DB 읽기 역할)**: 이 두 테이블의 권한을 주지 않는다. 0300 헤더에도 적었다.
- **출처 이름은 바꾸지 않는다.** 저장 키의 일부라서, 바꾸면 같은 기사가 새로 저장된다.
- 보안뉴스 피드(`gn_rss_allArticle.xml`)에는 본문(`content:encoded`)이 함께 와서 약 330KB다. 본문은 읽지 않는다. RSS 상한 5MB 안이다.
- 보안뉴스·The Hacker News RSS의 이용 조건은 확인하지 않았다(계획 "범위 밖").
- 보관 기간(오래된 뉴스·지난 ATT&CK 버전 지우기)은 아직 없다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 439건 통과
- `DATABASE_URL=… uv run pytest -m db`: 114건 통과(로컬 PostgreSQL 17.6)
- 주요 테스트
  - `tests/test_l3_intel.py`: 가져오기(헤더 없는 상한 초과, 압축을 푼 크기, 전체 마감, 요청 timeout, 3xx 미추적), RSS 2종, UTF-8·UTF-16 DOCTYPE 거부, KEV, ATT&CK 폐기·대체 제외와 버전 불일치, 문자열 정리
  - `tests/test_l3_intel_db.py`: 같은 항목 두 번(새로 저장 0, 갱신 0, `updated_at` 그대로), 제목 변경 갱신, 실패 출처 건너뛰기와 종료 코드, 출력에 건수만, 같은 ATT&CK 버전 건너뛰기, 새 버전 누적, CHECK
  - `tests/test_l3_config.py`: `local.toml` 덮어쓰기, `[l3]`만 반환, 틀린 설정 거부
- 실제 출처로 실행(임시 DB, 2026-11-04)
  - 첫 실행: 종료 코드 0, 약 8초. 보안뉴스 50건, The Hacker News 50건, CISA KEV 1767건, ATT&CK 20.0 706건(하위 기법 479건)을 모두 새로 저장했다.
  - 두 번째 실행: 종료 코드 0, 약 3초. 새로 저장 0건, 갱신 0건이었고 ATT&CK은 같은 버전이라 건너뛰었다.
  - 저장된 요약의 최대 길이: 보안뉴스 300자, The Hacker News 397자, KEV 821자
