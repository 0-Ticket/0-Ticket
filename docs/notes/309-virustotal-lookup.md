---
issue: 309
date: 2026-11-13
owner: Pandyo
plan: 309-virustotal-lookup.md
supersedes: []
---

# 에이전트가 VirusTotal로 IP·도메인·해시 평판을 조회한다 (lookup_indicator)

## 한 일

- L1·L2 에이전트가 `lookup_indicator`(`src/soc/tools/threat_intel.py`)로 IP·도메인·해시의 VirusTotal API v3 평판을 읽는다. 결과는 `status`(`found`, `not_found`, `not_queried`, `rate_limited`, `error`), 엔진 수 4종, `reputation`, 최초·최근 분석 시각, `tags`, IP면 `asn`·`as_owner`·`country`, `queried_at`, `from_cache`다. `call_id`로만 인용한다.
- 외부로 나가는 것은 `GET /api/v3/{ip_addresses|domains|files}/<정규화한 값>`과 `x-apikey` 헤더뿐이다. 쿼리·본문·다른 헤더는 없다. URL·경로·포트·공백·IP 모양 도메인은 인자 검사에서 `invalid_argument`로 거부해 요청이 나가지 않는다.
- 공개 주소가 아닌 IP(`is_global`, 멀티캐스트·예약 포함), 비공개 이름(`localhost`, `.local`, `.internal`, `.lan`, `.corp`, `.home`, `.intranet`, `.arpa`, 점 없는 이름)과 설정 제외 목록(`exclude_cidrs`, `exclude_domains`)은 요청 없이 `not_queried`다.
- 캐시(`found`·`not_found`만, 기본 24시간, 최대 1000개, 오래된 것부터 버림)와 호출 한도(분당 4건, UTC 날짜 기준 일 500건)는 프로세스 메모리에 있다. 서비스 429도 `rate_limited`다.
- 키(`VT_API_KEY`)가 없으면 이 실행에서 도구를 등록하지 않는다. 허용 단계는 `l1`·`l2`이고 `l3`는 아니다. `l1.md`·`l2.md`에 평판은 증거 하나일 뿐이라는 한 줄을 더했다.

## 계획과 달라진 점

- 팩토리 이름은 `lookup_indicator_tool(transport, clock, now, is_public)`이고 `ToolSpec` 하나를 돌려준다(계획은 `threat_intel_tools(...)`). 도구가 하나라 튜플로 감쌀 이유가 없다. 벽시계 `now`를 인자로 더했다. 캐시 TTL·분당 한도·UTC 날짜 한도가 벽시계를 보고, `clock`(monotonic)은 응답 마감 시간에만 쓴다.
- `check_config`는 만들지 않았다. 허용 목록에 있는 도구에만 부르는 `configure`가 같은 설정 검사(`_settings`)를 먼저 하고, 틀리면 `ToolConfigError`로 실행이 `provider_error`로 끝난다. 효과는 계획과 같다(허용되지 않은 단계의 설정은 보지 않는다).
- 비공개 이름 목록에 `.home`, `.corp`, `.intranet`을 포함했다(계획 그대로). 점 없는 이름은 형식 오류가 아니라 `not_queried`다.
- `error`의 사유는 결과의 `reason` 필드(`auth`, `network`, `timeout`, `http_status`, `too_large`, `response_shape`)에 남긴다. `ToolError`를 내지 않으므로 Agent Log `details.reason`에는 남지 않고, tool 줄 `output`(모델에게 보인 결과)에 들어 있다. `rate_limited`의 사유는 `local_minute`, `local_day`, `service`다.
- 실제 VirusTotal 호출은 하지 못했다(아래).

## 다음 사람이 알아야 할 것

- **실제 VirusTotal 호출은 확인하지 못했다.** 이 PC에 `VT_API_KEY`가 없었다. 응답 필드 이름(`last_analysis_stats`, `reputation`, `last_analysis_date`, `first_submission_date`, `tags`, `asn`, `as_owner`, `country`)은 API v3 문서 기억 기준이고, 테스트 샘플도 그 모양으로 손으로 만들었다. 실제 응답이 다르면 `_summary`의 필드 이름만 고치면 된다. 틀리면 `found`인데 값이 `null`로 나온다. 아래 방법으로 사람이 한 번 돌려 건수·소요 시간을 여기에 채운다.
- IP·도메인은 `first_analysis`가 항상 `null`이다. 최초 분석 시각은 파일(`first_submission_date`)에만 있는 것으로 알고 있다. 실측으로 확인한다.
- 한도와 캐시는 프로세스 메모리다. 실행기 프로세스가 여럿이거나 재시작하면 따로 센다. 무료 키는 프로세스 사이에서 공유되므로 서비스 쪽 429가 나올 수 있고, 그것도 `rate_limited`다. 월 한도는 세지 않는다(서비스 429에 맡긴다).
- 같은 지표를 동시에 처음 부르면 요청이 둘 나간다(한도는 둘 다 쓴다). 에이전트 한 실행 안에서는 드물다.
- 회사의 공개 도메인(`db01.corp.example.com`처럼 공개 이름 아래의 내부 호스트)은 `exclude_domains`에 적지 않으면 VirusTotal로 나간다. 코드가 알 수 없다. `config/local.toml`(커밋 안 함)에 적는다.
- `config/local.toml`에서 `[tools.allowed]`의 `l1`·`l2`를 따로 정의한 사람은 `lookup_indicator`를 직접 더해야 한다. 이 PC의 `local.toml`은 `l1`이 5개 도구만 있어서 아직 도구가 보이지 않는다. 키도 `.env`에 넣어야 등록된다.
- 무료 키 약관은 상업 이용을 제한한다(PR "이유"에 적는다). 조회한 지표 값은 VirusTotal에 전달된다.
- `tags`는 10개·40자, `as_owner`는 120자, `country`는 8자까지만 담는다. `as_owner`는 지역 인터넷 등록기관(RIR)에 공격자가 등록할 수 있는 이름이고 `tags`도 신뢰할 수 없다. 둘 다 외부에서 온 문자열이다.
- 기존 테스트 기대값을 고쳤다(지우거나 건너뛴 것은 없다): `tests/test_agent_config.py::test_default_tools_config`, `tests/test_tools_registry.py::test_default_registry_has_the_five_tools`.
- `docs/decisions.md`에는 `<<<<<<<` 충돌 표식과 D-049·D-050 중복이 이미 있다(`origin/main` 기준). 이번에는 D-051과 기록 한 줄만 더했고 정리하지 않았다. 별도 이슈로 정리해야 한다.
- 이 이슈로 `siem.py`는 바꾸지 않았다. 응답 크기·마감 시간 방식은 같게 새 모듈에 따로 썼다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 1738건 통과, 483건 제외(`db`·`llm`·`qdrant`·`embedder`·`elk`·`ssh`·`virustotal` 마커). macOS에서 실행했다
- 새 테스트 `tests/test_tools_threat_intel.py`(네트워크 없음, `httpx.MockTransport` + `tests/fixtures/threat_intel/`): 세 종류의 결과 모양과 요청 경로·헤더, `not_found`, 서비스 429, 오류 사유 9가지(키·주소가 결과·Agent Log에 없음), 응답 크기·전체 마감 시간, 비공개 IP 16개·비공개 도메인 9개의 `not_queried`와 요청 없음, 기본 판정의 공개 IP, 제외 CIDR·도메인 접미사, 형식 오류 26가지와 인자 누락·추가, 정규화, 요청에 쿼리·본문·다른 헤더·키가 URL에 없음, 캐시(재조회·TTL·`not_found` 저장·실패 미저장·항목 수 상한·키 정규화), 분당·일 한도와 UTC 날짜 초기화, 스레드 8개 동시 호출, 키 없음(미등록·빈 키·핸들러 단독 `not_queried`), 키 노출 없음, 악성 문자열 상한·구분자 탈출 방지, 잘못된 타입 `null`, 설정 오류 11가지, 기본 설정(`l1`·`l2`만, `l3` 거부), `.env.example`, `virustotal` 마커
- `tests/test_agent_redact.py::test_threat_intel_key_is_redacted`: `[tools.threat_intel] api_key_env` 값 가림(`redact.py`를 고치지 않고 통과)
- `tests/test_tools_threat_intel_vt.py`(`virustotal` 마커): 실제 VirusTotal. 돌리지 않았다.

### 실제 VirusTotal 테스트 실행 방법

1. VirusTotal 무료 키를 `.env`에 `VT_API_KEY=`로 넣는다(커밋하지 않는다).
2. 환경변수를 불러와 실행한다. 테스트는 IP·도메인·해시를 한 번씩(분당 4건 한도 안) 조회하고 `status`·악성 엔진 수·걸린 시간만 출력한다.

   ```bash
   set -a; source .env; set +a; uv run pytest -m virustotal -s tests/test_tools_threat_intel_vt.py
   ```

3. 환경변수가 없으면 테스트는 건너뛰지 않고 실패한다. 결과는 건수와 시간만 이 문서에 적는다.

실측 결과: (아직 없음)
