"""권한 목록(#284). 이름은 `<자원>.<동작>`이다. admin은 항상 전부 갖는다.

라우트에 붙이는 이름은 이 목록에 있어야 한다. 이름을 바꾸거나 더하면 ANALYST_DEFAULT와
기존 analyst에게 줄 기본 조회 권한(마이그레이션)을 함께 고친다.
"""

READ = (
    "dashboard.read",
    "alert.read",
    "event.read",
    "ticket.read",
    "incident.read",
    "case.read",
    "hunt.read",
    "news.read",
    "policy.read",
)

# 가입 승인 때 analyst가 받는 권한
ANALYST_DEFAULT = READ

# 승인·반려는 #365가 라우트에 붙였다(D-076). admin만 기본으로 갖고 analyst 기본 권한에는 없다
APPROVAL = ("incident.approve", "incident.reject")

# 아직 적용할 라우트가 없는 권한. 부여만 할 수 있고 후속 이슈가 라우트에 붙인다
UNUSED = frozenset({"incident.close"})

PERMISSIONS = (
    *READ,
    "policy.update",
    "user.read",
    "user.approve",
    "user.permission",
    *APPROVAL,
    *sorted(UNUSED),
)
