"""GET/PUT /api/ticketing-policy(#246). 조회는 policy.read, 변경은 policy.update 권한이다(#284)."""

from fastapi import APIRouter, Depends, Request

from soc.api import db
from soc.api.auth import require_permission
from soc.api.config import ApiSettings
from soc.api.models import TicketingPolicyBody, TicketingPolicyResponse
from soc.ticketing import load_policy, parse_policy, read_active_policy, replace_active_policy

router = APIRouter()


@router.get(
    "/ticketing-policy",
    response_model=TicketingPolicyResponse,
    dependencies=[Depends(require_permission("policy.read"))],
)
def get_ticketing_policy(request: Request) -> TicketingPolicyResponse:
    """활성 DB 정책을 돌려주고, 행이 없으면 TOML 기본·로컬 정책을 돌려준다."""
    settings: ApiSettings = request.app.state.settings
    with db.connect(settings) as conn:
        policy = read_active_policy(conn)
    if policy is None:
        policy = load_policy()
    return TicketingPolicyResponse(**policy.as_dict())


@router.put(
    "/ticketing-policy",
    response_model=TicketingPolicyResponse,
    dependencies=[Depends(require_permission("policy.update"))],
)
def put_ticketing_policy(request: Request, body: TicketingPolicyBody) -> TicketingPolicyResponse:
    """활성 정책을 요청 전체 값으로 원자적으로 바꾼다."""
    settings: ApiSettings = request.app.state.settings
    policy = parse_policy(body.model_dump())
    with db.connect_write(settings) as conn:
        with conn.transaction():
            replace_active_policy(conn, policy)
    return TicketingPolicyResponse(**policy.as_dict())
