"""L3 가설 헌팅(#223): 가설 생성 run → pending Hunt 검증 run → confirmed면 L3 Ticket.

    uv run python -m soc.l3 hunt

가설 생성과 검증은 실행 함수(기본 run_agent)를 주입받는다.
뉴스·Case·가설 문장은 밖에서 온 문자열이라 AgentTask.data로만 넘기고,
명령 출력과 로그에는 건수만 남긴다(docs/security.md "밖에서 온 문자열").
"""
