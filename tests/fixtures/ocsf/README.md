# OCSF 1.9.0 Detection Finding 스키마 (테스트용)

6 OCSF가 C3를 원형 JSON으로 내보낸 결과를 검증할 때 쓴다(K6).

| 항목 | 값 |
|---|---|
| 파일 | `detection_finding_1.9.0.schema.json` |
| 출처 | <https://schema.ocsf.io/schema/1.9.0/classes/detection_finding?profiles=> |
| OCSF 버전 | 1.9.0 (D-017) |
| 클래스 | Detection Finding, `class_uid` 2004 |
| 프로필 | 없음 (`?profiles=`). 기본 주소는 cloud·osint 등 프로필을 켜서 `cloud`, `osint`가 필수가 된다 |
| 형식 | JSON Schema draft-07, `$ref`는 파일 안의 `$defs`만 가리킨다 (네트워크 참조 없음) |
| 받은 날 | 2026-10-19 |
| 라이선스 | Apache-2.0 (OCSF 스키마, <https://github.com/ocsf/ocsf-schema>) |

내용은 바꾸지 않았다. 읽기 쉽게 키를 정렬하고 들여쓰기만 했다.
OCSF 버전을 바꾸면 같은 주소의 새 버전으로 다시 받고 이 표를 고친다.
