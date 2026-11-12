# OCSF 1.9.0 클래스·객체 정의

정의의 원본은 OCSF 스키마(github.com/ocsf/ocsf-schema, Apache License 2.0)다.

`classes/<class_uid>.json`과 `objects.json`은 OCSF 서버(schema.ocsf.io)가 주는 1.9.0 정의를 줄여 둔 것이다.
OCSF가 클래스별 JSON Schema 파일을 따로 배포하지 않아, 이 정의로 `ocsf_schema.validate_ocsf`가 검사한다.

- 받은 곳: `https://schema.ocsf.io/api/1.9.0/classes/<이름>?profiles=`(프로필 없이),
  `https://schema.ocsf.io/api/1.9.0/objects/<이름>?profiles=`
- 클래스: base_event(0), detection_finding(2004), http_activity(4002), api_activity(6003)
- 객체: 정규화가 내보내는 속성의 객체만 담았다. metadata, product, finding_info, network_endpoint,
  http_request, url, http_response, actor, user, api, service, evidences
- 줄인 방법: 속성마다 `type`, `requirement`, `object_type`, `is_array`, `enum` 목록(값)만 남기고,
  클래스·객체의 `uid`, `name`, `constraints`를 남겼다. 설명 문장은 버렸다.
- 프로필 속성(cloud 등)은 담지 않았다. 필요해지면 해당 프로필로 다시 받는다.
- 새 속성을 내보내려면 그 속성의 객체 정의를 `objects.json`에 더한다. 정의에 없는 속성은 검사에서 실패한다.

- 목적지 IP 증거 객체: `https://schema.ocsf.io/api/1.9.0/objects/evidences?profiles=`
  (2026-11-12 확인). Detection Finding의 `evidences[].dst_endpoint`에 사용한다.
