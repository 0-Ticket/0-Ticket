-- 로컬 ATT&CK·KEV 조회 도구(#311, D-052)가 읽는 필드와 수집 상태.
-- 0300은 고치지 않고 더하기만 한다. attack_techniques의 새 열은 비어 있을 수 있다(NULL):
-- 이 마이그레이션 전에 저장한 행은 다음 수집(soc.l3.intel)이 같은 버전을 다시 받아 채운다.
-- 열 모양과 CHECK 기준은 0300과 같다(행 하나만 봐도 깨진 레코드인지 알 수 있는 것).
-- 다른 번호의 테이블은 0300의 attack_techniques만 참조한다.

ALTER TABLE attack_techniques
    -- 정리한 평문(밖에서 온 문자열). 지시로 해석하지 않는다
    ADD COLUMN description text,
    -- 기법 ← detects ← 탐지 전략 → analytic → data component 이름. 중복 없이 이름순
    ADD COLUMN detection_sources text[]
        CHECK (detection_sources IS NULL OR array_position(detection_sources, NULL) IS NULL),
    -- 이 행을 마지막으로 받은 시각. NULL이면 새 열을 채우기 전의 행이다
    ADD COLUMN collected_at timestamptz;

-- CISA KEV 항목 상세. threat_news(뉴스와 KEV 공용)는 그대로 두고 get_cve가 이 표만 읽는다.
-- 제목·요약·조치 문구는 밖에서 온 문자열이다
CREATE TABLE kev_entries (
    -- PostgreSQL 정규식의 $는 문자열 끝에만 맞아 끝에 \n이 붙은 값도 거부한다
    cve_id text PRIMARY KEY CHECK (cve_id ~ '^CVE-[0-9]{4}-[0-9]{4,}$'),
    vulnerability_name text NOT NULL CHECK (vulnerability_name <> ''),
    short_description text NOT NULL,
    vendor_project text NOT NULL,
    product text NOT NULL,
    date_added date NOT NULL,
    -- 값이 없거나 날짜 모양이 아니면 NULL
    due_date date,
    -- CISA의 Known | Unknown 문구 그대로. 새 값이 생겨도 수집이 멈추지 않게 값 목록은 검사하지 않는다
    known_ransomware_use text NOT NULL CHECK (known_ransomware_use <> ''),
    required_action text NOT NULL,
    -- 내용이 마지막으로 바뀐 시각
    updated_at timestamptz NOT NULL
);

-- 출처(설정의 이름)별 마지막 성공 수집. KEV 카탈로그 정보를 담는다
CREATE TABLE intel_source_state (
    source text PRIMARY KEY CHECK (source <> ''),
    catalog_version text NOT NULL CHECK (catalog_version <> ''),
    -- 카탈로그의 dateReleased. 읽지 못하면 NULL
    released_at timestamptz,
    collected_at timestamptz NOT NULL
);
