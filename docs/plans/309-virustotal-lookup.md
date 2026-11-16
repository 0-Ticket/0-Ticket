---
issue: 309
date: 2026-11-13
owner: Pandyo
supersedes: []
---

# VirusTotal 위협 인텔 조회 도구 추가

## 목표

L1·L2 에이전트가 IP·도메인·파일 해시의 외부 평판을 `lookup_indicator`로 조회할 수 있게 한다. 첫 서비스는 VirusTotal API v3 무료 키다. 외부로 나가는 값은 지표 값뿐이고, 무엇을 보내고 보내지 않는지를 코드와 테스트로 고정한다.

## 방법

- 새 모듈 `src/soc/tools/threat_intel.py`에 도구 하나를 만든다. 팩토리 `threat_intel_tools(transport=None, clock=time.monotonic, is_public=None)`가 `ToolSpec`을 만든다(`siem_tools`와 같은 방식). 캐시·한도 카운터는 이 팩토리 클로저의 프로세스 메모리에 두고 락으로 지킨다(핸들러는 호출마다 별도 스레드, D-049). 어댑터 등록 구조는 만들지 않고, "요청 → 요약" 함수만 분리한다.
- 인자: `indicator_type`(`ip`·`domain`·`hash`, enum), `value`(문자열). 결과는 `aggregate`이고 `call_id`로 인용한다.
- 입력 검증과 정규화(요청이 나가기 전, 틀리면 `invalid_argument`)
  - IP: `ipaddress`로 해석한다. 도메인: 소문자, 끝의 점 제거, punycode, FQDN 형식. URL·경로·포트·공백·IP 리터럴이 들어 있으면 자르지 않고 거부한다.
  - 해시: 소문자, 16진수, 길이 32·40·64만.
- 보내지 않는 값(`not_queried`, 사유 포함, 요청 없음)
  - IP: `is_global`이 아닌 것(RFC 1918, 루프백, 링크 로컬, 문서용, CGNAT, ULA, IPv4 매핑 등)과 설정 `exclude_cidrs`.
  - 도메인: 코드 상수의 비공개 이름(`localhost`, `.local`, `.internal`, `.lan`, `.corp`, `.home`, `.intranet`, `.arpa`)과 설정 `exclude_domains`(접미사 일치). 기본 제외 목록은 비어 있다.
  - 공개 여부 판정은 팩토리 인자 `is_public`으로 바꿀 수 있어, `found`·캐시 테스트가 문서용 대역 IP를 쓴다. 제외 테스트는 기본 판정으로 한다.
- 요청: VirusTotal v3 `GET /ip_addresses/{ip}`, `/domains/{domain}`, `/files/{hash}`. 키는 `x-apikey` 헤더로만 보내고 URL에 넣지 않는다. 리다이렉트는 따라가지 않고, 요청 timeout·전체 마감 시간·압축을 푼 응답 크기 상한을 `siem.py`와 같은 방식으로 둔다.
- 응답 매핑: 200 `found`, 404 `not_found`, 429 `rate_limited`, 그 밖의 401·403·네트워크 오류·크기 초과·마감 초과·모양 오류는 `error`다. 모두 정상 결과로 돌려주고(`ToolError`를 내지 않음) 사유는 Agent Log `details.reason`에 남기지 못하므로 결과의 짧은 `reason` 이름(`auth`, `network`, `too_large`, `timeout`, `http_status`, `response_shape`)으로 둔다. 키·주소·응답 본문은 넣지 않는다.
- 출력: `status`, `source`, `malicious`·`suspicious`·`harmless`·`undetected`, `reputation`, 최초·최근 분석 시각(없으면 `null`), `tags`, IP면 `asn`·`as_owner`·`country`, `queried_at`, `from_cache`. 시각은 ISO 8601 UTC 문자열이다. 밖에서 온 문자열이므로 `tags`는 개수·길이, `as_owner`는 길이에 상한을 둔다. 응답에 `status`가 `found`여도 안전·악성 판정은 하지 않는다.
- 캐시: 키 `(종류, 정규화한 값)`, `found`·`not_found`만 TTL(기본 24시간) 동안 저장하고 `from_cache=true`로 돌려준다. `error`·`rate_limited`·`not_queried`는 저장하지 않는다. 최대 항목 수를 설정값으로 둬서 넘으면 오래된 것부터 버린다.
- 한도: 분당·일(UTC 날짜) 호출 수를 설정값으로 두고 넘으면 호출하지 않고 `rate_limited`를 돌려준다. 캐시에서 돌려준 호출은 세지 않는다.
- 키가 없으면 `configure`가 `None`을 돌려줘 이 실행에서 도구를 등록하지 않는다(`run_host_check`와 같다). 핸들러를 직접 부르면 `not_queried`(사유 `no_key`)를 돌려준다.
- 설정 `[tools.threat_intel]`(`config/default.toml`): `api_key_env = "VT_API_KEY"`, 요청·마감 timeout, `max_bytes`, `per_minute`, `per_day`, `cache_ttl_seconds`, `cache_max_entries`, `exclude_cidrs`, `exclude_domains`. `check_config`로 값 모양을 실행 시작 전에 검사한다.
- 허용 단계: `[tools.allowed]`의 `l1`·`l2`에만 넣는다. `l3`는 넣지 않는다.
- 프롬프트: `l1.md`, `l2.md`에 한 줄만 더한다. 평판은 증거 하나이지 판정이 아니고, 악성 0건이나 `not_found`는 안전이 아니다.
- 결정 목록에 D-051을 올린다.

## 바꿀 곳

- `src/soc/tools/threat_intel.py`: 새 모듈(도구, 검증, 캐시, 한도, VirusTotal 요청·요약)
- `src/soc/tools/__init__.py`: `default_registry()`에 도구를 더하고 docstring의 도구 개수를 고친다
- `config/default.toml`: `[tools.threat_intel]` 추가, `[tools.allowed]`의 `l1`·`l2`에 `lookup_indicator` 추가
- `src/soc/agent/prompts/l1.md`, `l2.md`: 사용법 한 줄
- `.env.example`: `VT_API_KEY` 이름만
- `pyproject.toml`: 실제 호출 테스트용 마커(`virustotal`)를 만들고 기본 제외 목록(`addopts`)에 더한다
- `tests/test_tools_threat_intel.py`(`httpx.MockTransport` + `tests/fixtures/threat_intel/`), `tests/test_tools_threat_intel_vt.py`(`virustotal` 마커, 실제 호출)
- 기존 테스트 기대값: `tests/test_agent_config.py::test_default_tools_config`, `tests/test_tools_registry.py`의 기본 레지스트리 기대 목록(지우거나 건너뛰지 않고 기대값만 고친다)
- `docs/decisions.md`: D-051과 기록 줄
- `docs/notes/309-virustotal-lookup.md`: 개발 기록(개발 단계에서)

## 다른 코드와 맞물리는 곳

- `default_registry()`의 도구 목록과 `[tools.allowed]` 기본값이 바뀐다. 이를 기대하는 기존 테스트 둘을 고친다.
- `config/local.toml`에서 `[tools.allowed]`의 `l1`·`l2`를 따로 정의한 사람은 `lookup_indicator`를 직접 추가해야 한다(기록에 적는다).
- 새 설정 키 `[tools.threat_intel]`과 새 환경변수 `VT_API_KEY`. 다른 코드가 읽는 함수·테이블·데이터 형식은 바꾸지 않는다.
- `siem.py`의 요청 도우미는 SIEM 전용이라 건드리지 않고, 같은 방식을 새 모듈에 둔다.

## 범위 밖

- l3 허용, 다른 서비스(AbuseIPDB·OTX·GreyNoise)와 어댑터 등록 구조
- 별도 GeoIP DB, WHOIS
- PostgreSQL 캐시, 프로세스 사이 공유 한도, 월 한도 추적
- 자산 표(`assets`)를 제외 목록에 연결하기
- URL·파일 업로드·분석 요청(조회만 한다)
- 회사 공개 도메인 자동 제외(설정 목록으로만)

## 완료 기준

- [ ] `lookup_indicator`가 IP·도메인·해시에 대해 위 필드로 요약된 결과를 돌려주고, 가짜 HTTP 응답으로 확인하는 테스트가 있다
- [ ] 사설·예약 대역, 비공개 도메인 이름, 제외 목록 값은 HTTP 요청이 나가지 않고 `not_queried`가 되는 테스트가 있다
- [ ] 잘못된 지표 형식(URL·경로·포트·IP 리터럴 도메인 포함)은 요청 없이 거부되는 테스트가 있다
- [ ] 로그 원문·URL 경로·페이로드가 요청에 실리지 않는 테스트가 있다(요청 URL·헤더·본문을 검사하고 키가 URL에 없음을 확인)
- [ ] 한도 초과(자체 한도와 서비스 429)가 `rate_limited`로, VirusTotal에 없는 지표가 `not_found`로, 네트워크 오류가 `error`로 구분되는 테스트가 있다
- [ ] 같은 지표를 TTL 안에 다시 조회하면 외부 호출 없이 `from_cache`로 돌아오고, TTL이 지나면 다시 조회하며, `error`는 캐시하지 않는 테스트가 있다
- [ ] 캐시 최대 항목 수를 넘으면 오래된 것부터 버려지는 테스트가 있다
- [ ] 키가 없으면 도구가 등록되지 않고, 핸들러를 직접 부르면 죽지 않고 `not_queried`를 돌려주는 테스트가 있다
- [ ] `tags`·`as_owner` 상한과 구분자 이스케이프 테스트가 있다
- [ ] 키가 Agent Log, 로그, 테스트 출력, PR에 나오지 않는다(가림 테스트 포함). `.env.example`에 환경변수 이름만 있다
- [ ] 허용 목록에서 `l1`·`l2`만 쓸 수 있고 `l3` 호출이 거부된다
- [ ] 실제 VirusTotal 호출 확인은 기본 제외 마커 테스트로 두고, 실측 건수·소요 시간을 `docs/notes/`에 적는다
- [ ] 새 의존 라이브러리가 없다(httpx는 D-039). 무료 키 약관(상업 이용 제한)을 PR "이유"에 적는다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

- 캐시와 한도 카운터는 PostgreSQL이 아니라 프로세스 메모리에 둔다. 에이전트 도구는 읽기 전용 계정만 쓴다는 규칙(`docs/security.md`)을 지키기 위해서다. 재시작하거나 프로세스가 여럿이면 따로 센다.
- 키가 없으면 `not_queried`를 돌려주는 대신 도구를 등록하지 않는다(이슈의 두 문장이 양립하지 않아 후자를 골랐다). 핸들러 단독 동작은 `not_queried`다.
- 공개 여부 판정을 팩토리 인자로 주입한다. 테스트 샘플은 `docs/security.md`대로 문서용 대역을 쓰는데 이 도구는 그 대역을 막기 때문이다.
- 내부 도메인은 코드 상수 + 설정 목록으로 거른다. 회사의 공개 도메인은 설정에 적지 않으면 VirusTotal로 나간다.
- l3에는 허용하지 않는다. 무료 키 분당 4건을 l3 헌팅이 소진하지 않게 하기 위해서다.
- 서비스별 어댑터 구조는 만들지 않는다(AGENTS.md 원칙 4). 두 번째 서비스가 올 때 만든다.
- 이슈의 `rate_limited`·`error` 같은 상태는 `ToolError`가 아니라 정상 결과로 돌려준다(이슈 그대로). 연속 실패 차단(2회)은 걸리지 않는다.
- 결정 목록: D-051(VirusTotal 조회 도구)을 올렸다. 처음 제안 문구에 키가 없을 때의 동작, 약관, 도메인 한계 메모를 더했다. `decisions.md`에 이미 있는 머지 충돌 표식과 D-049·D-050 중복은 건드리지 않았다(별도 이슈로 정리).
- VirusTotal 응답 필드(IP·도메인에는 최초 분석 시각이 없을 수 있음)와 무료 키 한도는 개발 중 실측으로 확인한다.

## 바뀐 점
