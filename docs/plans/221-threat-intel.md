---
issue: 221
date: 2026-11-04
owner: Pandyo
supersedes: []
---

# 보안 뉴스·CISA KEV·ATT&CK 수집 계층

## 목표

L3 가설의 재료(보안뉴스·The Hacker News RSS, CISA KEV, MITRE ATT&CK Enterprise)를 명령 하나로 가져와 L3 테이블 두 개(`threat_news`, `attack_techniques`)에 저장한다. 에이전트는 이 계층을 거치지 않고는 웹에 접근하지 않는다(L3 위협 시나리오 입력, D-029). ATT&CK 목록은 Hunt의 기법 ID가 실제로 있는지 L3 헌팅 코드가 확인하는 데 쓴다.

## 방법

### 1. 결정 목록 (`docs/decisions.md`)

- L3 위협 시나리오 입력(D-029)을 "담당자가 정함"에서 "확정"으로 옮긴다: 보안 뉴스(보안뉴스·The Hacker News RSS, CISA KEV)와 MITRE ATT&CK을 코드(`soc.l3.intel`)로 수집하고, 에이전트에는 웹 접근을 주지 않는다. 에이전트에는 L3 헌팅 코드가 `AgentTask.data`로만 넘긴다.
- D-039 HTTP 클라이언트 httpx(`httpx==0.28.1`). 리다이렉트는 따라가지 않는다. 메모: 응답 크기 상한은 스트리밍하면서 압축을 푼 바이트로 세고, 요청 단위 timeout과 별도로 출처별 전체 마감 시간을 둔다. openai 3.x가 끌어오는 `httpx2`와 따로 설치된다. httpx는 2024-12 이후 릴리스가 없어, 보안 수정이 필요한데 나오지 않으면 다시 논의한다.
- D-040 데이터셋 MITRE ATT&CK Enterprise(공식 STIX JSON, `mitre-attack/attack-stix-data`). 원본은 커밋하지 않고 실행할 때 받아, 폐기·대체되지 않은 기법의 ID·이름·전술·버전만 저장한다. 메모: 버전마다 쌓고 쓰는 쪽이 설정 버전으로 고른다. 이용 약관에 따라 README "제3자 데이터" 절에 MITRE 고지문을 싣는다.
- "기록"에 `#221 · …` 한 줄.

### 2. 설정 (`config/default.toml`의 `[l3.intel]`)과 L3 로더 (`src/soc/l3/config.py`)

- L3 로더는 `config/default.toml` 위에 `config/local.toml`을 덮어쓰고 `[l3]`만 돌려준다. 덮어쓰기 규칙은 에이전트 로더(`src/soc/agent/config.py`)와 같게 하되, 에이전트 로더는 바꾸지 않고 import하지도 않는다(같은 규칙을 L3 로더에 따로 둔다). 공통 설정 로더가 생기면 그쪽으로 옮긴다.
- 설정 값(비밀 값 없음, 모두 공개 피드)
  - 출처 목록: 이름, 종류(`rss`, `cisa_kev`), 주소
    - `boannews`, `rss`, `https://cdn.boannews.com/rss/gn_rss_allArticle.xml`
    - `thehackernews`, `rss`, `https://feeds.feedburner.com/TheHackersNews`
    - `cisa_kev`, `cisa_kev`, `https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json`
  - ATT&CK: `version = "20.0"`, 주소 `https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/enterprise-attack/enterprise-attack-20.0.json`
  - 요약 길이 상한 1000자
  - 응답 크기 상한: `rss` 5MB, `cisa_kev` 10MB, ATT&CK 100MB
  - 연결·읽기 제한 시간 10초, 출처별 전체 마감 시간: `rss`·`cisa_kev` 30초, ATT&CK 180초
- 설정 주석에 적는다: 출처 이름은 저장 키의 일부라 바꾸면 같은 기사가 새로 저장된다.

### 3. 수집 명령 (`uv run python -m soc.l3.intel`, 코드 `src/soc/l3/intel/`)

- DB 주소는 환경변수 `DATABASE_URL`(마이그레이션 실행기와 같음). 마이그레이션은 하지 않고, 마이그레이션이 끝난 DB를 전제로 한다.
- 설정의 출처를 차례로 가져와 저장하고, 마지막에 ATT&CK을 처리한다. 한 출처가 실패해도 나머지를 계속한다.
- 출력은 출처마다 이름, 가져온 건수, 새로 저장한 건수, 갱신한 건수, 실패 종류(없으면 없음)만. 본문·응답 내용·DB 주소는 출력하지 않는다.
- 실패 종류: `timeout`, `too_large`, `http_status`(3xx 포함), `network`, `doctype`, `parse`, `version_mismatch`.
- 종료 코드: 실패한 출처가 하나라도 있으면 나머지를 마친 뒤 1, 아니면 0.

### 4. 가져오기 (httpx)

- 주소는 설정에서만 온다. 응답 안의 링크를 따라가 다시 요청하지 않고, HTTP 리다이렉트도 따라가지 않는다.
- 응답은 스트리밍으로 받으며, 압축을 푼 뒤의 바이트를 세어 상한을 넘으면 그 자리에서 끊고 `too_large`. `Content-Length`는 믿지 않는다.
- 요청 단위 timeout(연결·읽기)과 별도로 출처별 전체 마감 시간을 받는 동안 확인해, 넘으면 `timeout`.
- 2xx가 아니면 `http_status`. 테스트는 `httpx.MockTransport`로 가짜 응답을 준다.

### 5. 파싱

- **RSS**: 표준 `xml.etree`(expat)로 파싱한다. 파서에 `StartDoctypeDeclHandler`를 달아 DOCTYPE을 만나면 `doctype` 실패로 처리한다(인코딩과 상관없이 막는다. 바이트 검색은 UTF-16 문서를 놓친다). 그 밖의 XML 오류는 `parse`.
  - 항목마다: `source_ref` = `guid`, 없으면 `link`. 둘 다 없는 항목은 버린다.
  - 제목 = `title`, 요약 = `description`, 링크 = `link`, 발행 시각 = `pubDate`(RFC 822). `pubDate`가 없거나 읽지 못하면 null.
  - `content:encoded`(본문)는 읽지 않는다.
- **CISA KEV**: JSON의 `vulnerabilities[]`. `source_ref` = `cveID`, 제목 = `vulnerabilityName`, 요약 = `shortDescription`, 링크 = null, 발행 시각 = `dateAdded`의 00:00 UTC.
- **ATT&CK**: STIX 번들의 `objects`.
  - `x-mitre-collection`의 `x_mitre_version`이 설정 버전과 다르면 `version_mismatch`.
  - `type = attack-pattern`이고 `revoked`·`x_mitre_deprecated`가 참이 아닌 것만.
  - 기법 ID = `external_references`에서 `source_name = mitre-attack`인 항목의 `external_id`. Hunt 계약과 같은 모양(`^T[0-9]{4}(\.[0-9]{3})?$`)이 아니면 `parse` 실패.
  - 전술 = `kill_chain_phases`에서 `kill_chain_name = mitre-attack`인 `phase_name` 목록(예: `initial-access`).
- 형식이 기대와 다르면(필수 키 없음, 타입 다름) 그 출처를 `parse` 실패로 처리한다.

### 6. 문자열 정리 (밖에서 온 문자열은 데이터다)

- 제목·요약: 표준 `html.parser`로 텍스트만 남기고 엔티티를 풀고, NUL과 제어 문자(줄바꿈·탭은 공백으로)를 지우고, 공백을 하나로 줄인다.
- 요약이 상한(1000자)을 넘으면 자른다. 정리 뒤 제목이 비면 그 항목을 버린다.
- 수집한 제목·요약·링크는 로그 원문과 같은 '데이터'다. 지시로 해석하지 않고, 실패 기록에는 출처 이름과 실패 종류만 남기며 응답 본문은 넣지 않는다.

### 7. 저장 (`src/soc/db/migrations/0300_threat_intel.sql`, L3 대역의 첫 파일)

- 다른 번호의 테이블을 참조하지 않는다. 컬럼 모양(목록 `text[]`, 시각 `timestamptz`)과 CHECK 기준(행 하나만 봐도 깨진 레코드인지 알 수 있는 것)은 0001·0002를 따른다.
- `threat_news`
  - `id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY`
  - `source text NOT NULL`(설정의 출처 이름), `kind text NOT NULL CHECK (kind IN ('rss', 'cisa_kev'))`, `source_ref text NOT NULL`
  - `title text NOT NULL`, `summary text NOT NULL`(빈 문자열 가능), `link text`, `published_at timestamptz`
  - `fetched_at timestamptz NOT NULL`(처음 받은 시각, 바꾸지 않음), `updated_at timestamptz NOT NULL`(내용이 마지막으로 바뀐 시각, 처음에는 `fetched_at`과 같음)
  - `UNIQUE (source, source_ref)`. 빈 문자열 `source`·`source_ref`·`title`은 CHECK로 막는다.
  - 다시 받으면: 제목·요약·링크·발행 시각 중 하나라도 다를 때만 그 네 칸과 `updated_at`을 갱신한다. 같으면 손대지 않는다. 새로 저장·갱신 건수를 따로 센다.
- `attack_techniques`
  - `attack_version text NOT NULL`, `technique_id text NOT NULL CHECK (technique_id ~ '^T[0-9]{4}(\.[0-9]{3})?$')`, `name text NOT NULL`, `tactics text[] NOT NULL`(NULL 원소 거부)
  - `PRIMARY KEY (attack_version, technique_id)`
  - 버전마다 쌓는다. 한 버전은 트랜잭션 하나로 모두 넣으므로 "그 버전 행이 있다" = "그 버전을 다 받았다". 같은 버전 행이 있으면 내려받지 않는다.
- 한 출처의 저장은 트랜잭션 하나다. 실패하면 그 출처만 되돌린다.
- 두 테이블은 L3만 읽는다(공통 계약이 아니다). 에이전트에게는 L3 헌팅 코드가 `AgentTask.data`로만 넘긴다.

### 8. 출처 표기 (`README.md`)

- "제3자 데이터" 절을 더하고 MITRE ATT&CK 이용 약관이 요구하는 고지문을 싣는다: "© 2026 The MITRE Corporation. This work is reproduced and distributed with the permission of The MITRE Corporation."

### 순서

샘플(`tests/fixtures/l3_intel/`) → 테스트 → 설정·로더 → 가져오기·파싱·정리 → 마이그레이션·저장 → 명령 → 문서.

## 바꿀 곳

- `pyproject.toml`, `uv.lock`: `httpx==0.28.1`
- `config/default.toml`: `[l3.intel]`
- `src/soc/l3/__init__.py`, `src/soc/l3/config.py`: L3 로더
- `src/soc/l3/intel/`: 가져오기, 파싱, 정리, 저장, `__main__.py`
- `src/soc/db/migrations/0300_threat_intel.sql`: 새 파일
- `tests/fixtures/l3_intel/`: 손으로 만든 RSS 2종(보안뉴스·THN 모양), KEV, ATT&CK 샘플과 틀린 샘플(DOCTYPE, UTF-16 DOCTYPE, 형식 오류). 실제 기사 문장은 옮기지 않는다
- `tests/test_l3_config.py`, `tests/test_l3_intel.py`, `tests/test_l3_intel_db.py`: 새 테스트
- `tests/test_db_tables.py`: `test_migrate_creates_all_tables_on_empty_db`의 기대값에 `0300_threat_intel.sql`과 테이블 두 개를 더한다(지우거나 건너뛰지 않음)
- `docs/decisions.md`: D-029 이동, D-039·D-040 추가, 기록 한 줄
- `README.md`: "제3자 데이터" 절
- `docs/notes/221-threat-intel.md`: 개발 기록

## 다른 코드와 맞물리는 곳

- **새 테이블 `threat_news`, `attack_techniques`.** L3 전용이며 공통 계약이 아니다.
- **L3 헌팅 코드(이후 이슈)**: ATT&CK은 버전마다 쌓이므로 L3 로더의 `[l3.intel.attack] version`으로 골라 조회해야 한다. 뉴스는 다시 받으면 내용이 갱신되므로, Hunt가 어떤 내용을 근거로 했는지 남기려면 그 시점의 제목·요약을 Hunt `details`에 복사해야 한다. 뉴스는 `threat_news.id`(숫자)로 가리킨다.
- **#211(에이전트 DB 읽기 역할)**: 그 역할에 두 테이블 권한을 주지 않는다. 역할이 아직 없어 이번에는 확인할 수 없고, 기록에 남긴다.
- **설정 키 `[l3]`**가 새로 생긴다. 에이전트 로더(`[llm]`·`[agent]`·`[tools]`)는 바꾸지 않는다.
- **공통 테스트 `tests/test_db_tables.py`**의 기대값 하나가 바뀐다.
- **마이그레이션 번호 `0300`.** L3 대역의 첫 번호다. 다른 PR이 같은 번호를 쓰면 실행기가 멈추므로 머지 직전에 확인한다.
- **의존성 `httpx`**가 늘어난다. `httpx2`(openai)와 따로 설치된다.

## 범위 밖

- 수집한 뉴스로 가설을 세우는 L3 헌팅 코드, Hunt 기법 ID를 `attack_techniques`로 확인하는 코드
- 주기 실행(L3 실행 방식, D-030은 이번에 정하지 않는다)
- 오래된 뉴스·지난 ATT&CK 버전 지우기(보관 기간)
- 기사 본문 수집, 응답 안 링크 따라가기
- 에이전트 DB 읽기 역할 권한 설정(#211)
- 보안뉴스·The Hacker News RSS 이용 조건 확인(사람이 따로 본다)

## 완료 기준

- [ ] 손으로 만든 RSS 2종·KEV·ATT&CK 샘플(`tests/fixtures/`, `httpx.MockTransport`)로 파싱·저장 테스트가 있다
- [ ] 같은 항목을 그대로 두 번 가져오면 한 행이고, 두 번째에 새로 저장 0건·갱신 0건이며 `updated_at`이 바뀌지 않는다(`db` 마커)
- [ ] 제목을 바꿔 다시 가져오면 갱신 1건이고 `id`·`fetched_at`은 그대로, `updated_at`은 새 시각이다(`db` 마커)
- [ ] 크기 상한 초과(헤더 없이 큰 응답 포함), 시간 초과(전체 마감 포함), 2xx가 아닌 응답(3xx 포함), 형식 오류인 출처는 건너뛰고 나머지는 저장되며, 종료 코드는 1이다
- [ ] `<!DOCTYPE`이 든 XML은 UTF-8·UTF-16 모두 `doctype`으로 거부된다
- [ ] 폐기·대체된 ATT&CK 기법은 저장되지 않고, 같은 버전이 있으면 내려받기를 건너뛰고, 받은 버전이 설정과 다르면 `version_mismatch`다
- [ ] 다른 ATT&CK 버전을 받으면 이전 버전 행이 남은 채 새 버전 행이 더해진다(`db` 마커)
- [ ] 요약에 HTML 태그·NUL·제어 문자가 남지 않고 길이 상한을 넘지 않는다
- [ ] 명령 출력에 본문·응답 내용이 나오지 않는다
- [ ] L3 로더가 `local.toml` 덮어쓰기를 반영하고 `[l3]`만 돌려준다
- [ ] D-029가 확정으로 옮겨지고 D-039(httpx)·D-040(ATT&CK) 행과 기록 한 줄이 추가됐다
- [ ] README에 MITRE ATT&CK 고지문이 있다
- [ ] 실제 출처로 한 번 실행해 출처별 건수를 PR에 적는다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과(`db` 마커 테스트도 실행)
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

1. **HTTP 클라이언트는 이슈대로 httpx(`httpx==0.28.1`)다.** AI는 openai 3.x가 이미 끌어오고 Starlette TestClient도 옮겨 간 `httpx2`를 추천했지만, 사람이 이슈대로 httpx로 정했다. `httpx2`와 함께 풀리는 것은 확인했다. httpx는 2024-12 이후 릴리스가 없어 D-039 메모에 다시 논의할 조건을 적는다. 이슈의 "FastAPI 테스트 클라이언트도 httpx를 쓴다"는 지금 사정과 맞지 않아 결정 메모에서 뺀다.
2. **보안뉴스 피드는 `cdn.boannews.com/rss/gn_rss_allArticle.xml`이다.** `www.boannews.com/rss/allArticle.xml`은 `pubDate`에 시간대가 없고 `guid`가 없다. 고른 피드는 본문(`content:encoded`)이 함께 오지만 읽지 않는다.
3. **DOCTYPE은 바이트 검색이 아니라 expat 핸들러로 거부한다.** 바이트 검색은 UTF-16 문서를 놓친다.
4. **크기 상한은 압축을 푼 바이트로 스트리밍하며 세고, 출처별 전체 마감 시간을 따로 둔다.** `Content-Length`와 요청 단위 timeout만으로는 지킬 수 없다.
5. **`threat_news.id`는 테이블 안 일련번호다.** 공통 파일(`soc.ids`)을 바꾸지 않는다.
6. **ATT&CK은 버전마다 쌓는다.** 쓰는 쪽이 설정 버전으로 고른다. 받은 파일의 버전이 설정과 다르면 실패로 둔다.
7. **같은 뉴스를 다시 받으면 내용이 달라졌을 때만 갱신한다.** `fetched_at`(처음 받은 시각)과 `updated_at`(마지막 갱신 시각)을 따로 두고, 출력에 갱신 건수를 따로 센다.
8. **`threat_news.kind`(`rss`, `cisa_kev`)를 둔다.** 헌팅 코드가 출처 이름에 기대지 않고 뉴스와 KEV를 구분하게 한다.
9. **KEV는 제목 `vulnerabilityName`, 요약 `shortDescription`, 링크 null, 발행 시각 `dateAdded` 00:00 UTC.** 없는 링크를 만들어 내지 않는다.
10. **보관 기간은 이번에 정하지 않는다(지우지 않음).**
11. **ATT&CK 출처 표기는 README "제3자 데이터" 절에 이용 약관의 고지문을 싣는다.**
12. **상한 기본값**: 요약 1000자, 응답 RSS 5MB·KEV 10MB·ATT&CK 100MB, 연결·읽기 10초, 전체 마감 RSS·KEV 30초·ATT&CK 180초. 실측(RSS 약 330KB, KEV 1.8MB, ATT&CK 20.0 55MB, KEV 요약 최대 821자)에 여유를 둔 값이다.
13. **결정 번호는 D-039(httpx), D-040(ATT&CK)이다.**
14. **실패한 출처가 있으면 종료 코드 1, `published_at`은 null 허용, 마이그레이션 파일은 `0300_threat_intel.sql`.** 이슈에 없던 빈칸을 정했다.

## 바뀐 점
