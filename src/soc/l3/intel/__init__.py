"""L3 가설 재료 수집: 보안 뉴스 RSS, CISA KEV, MITRE ATT&CK(L3 위협 시나리오 입력, D-029).

    uv run python -m soc.l3.intel

에이전트는 이 계층을 거치지 않고는 웹에 접근하지 않는다. 수집한 제목·요약은 밖에서 온 문자열이라
데이터로만 다룬다(docs/security.md "밖에서 온 문자열").
"""
