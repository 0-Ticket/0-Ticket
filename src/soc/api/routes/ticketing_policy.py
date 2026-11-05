"""GET/PUT /api/ticketing-policy(#246). 현재 두 경로에는 인증·인가가 없다."""

from fastapi import APIRouter, Request

from soc.api import db
from soc.api.config import ApiSettings
from soc.api.models import TicketingPolicyBody, TicketingPolicyResponse
from soc.ticketing import load_policy, parse_policy, read_active_policy, replace_active_policy

router = APIRouter()


@router.get("/ticketing-policy", response_model=TicketingPolicyResponse)
def get_ticketing_policy(request: Request) -> TicketingPolicyResponse:
    """활성 DB 정책을 돌려주고, 행이 없으면 TOML 기본·로컬 정책을 돌려준다."""
    settings: ApiSettings = request.app.state.settings
    with db.connect(settings) as conn:
        policy = read_active_policy(conn)
    if policy is None:
        policy = load_policy()
    return TicketingPolicyResponse(**policy.as_dict())


@router.put("/ticketing-policy", response_model=TicketingPolicyResponse)
def put_ticketing_policy(request: Request, body: TicketingPolicyBody) -> TicketingPolicyResponse:
    """활성 정책을 요청 전체 값으로 원자적으로 바꾼다.

    이 엔드포인트는 D-020 인증·인가가 연결되기 전까지 네트워크 접근 제어를 하지 않는다.
    """
    settings: ApiSettings = request.app.state.settings
    policy = parse_policy(body.model_dump())
    with db.connect_write(settings) as conn:
        with conn.transaction():
            replace_active_policy(conn, policy)
    return TicketingPolicyResponse(**policy.as_dict())
