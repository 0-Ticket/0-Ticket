"""사용자 관리와 권한 부여(#284). 권한은 라우트마다 다르고, 권한 상승 방지 규칙은 store에 있다."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from soc.api import db
from soc.api.auth import require_permission
from soc.api.auth_models import (
    ANALYST_DEFAULTS,
    ApproveBody,
    PermissionItem,
    PermissionList,
    PermissionsBody,
    ResetBody,
    RoleBody,
    UserItem,
    UserList,
    UserStatus,
)
from soc.api.errors import NotFound
from soc.auth import store
from soc.auth.permissions import PERMISSIONS
from soc.auth.store import User

router = APIRouter()

Reader = Annotated[User, Depends(require_permission("user.read"))]
Approver = Annotated[User, Depends(require_permission("user.approve"))]
RoleSetter = Annotated[User, Depends(require_permission("user.role"))]
PermissionSetter = Annotated[User, Depends(require_permission("user.permission"))]


def _id(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(user_id)
    except ValueError:
        raise NotFound from None


def _write(request: Request, action, actor: User, user_id: str, *args) -> dict:
    with db.connect_write(request.app.state.settings) as conn:
        return action(conn, actor, _id(user_id), *args)


@router.get("/users", response_model=UserList)
def list_users(
    request: Request,
    actor: Reader,
    status: Annotated[UserStatus | None, Query()] = None,
) -> dict:
    with db.connect(request.app.state.settings) as conn:
        return {"items": store.list_records(conn, status)}


@router.get("/permissions", response_model=PermissionList)
def list_permissions(actor: Reader) -> dict:
    return {
        "permissions": [
            PermissionItem(name=name, analyst_default=name in ANALYST_DEFAULTS)
            for name in sorted(PERMISSIONS)
        ]
    }


@router.post("/users/{user_id}/approve", response_model=UserItem)
def approve(
    request: Request,
    user_id: str,
    body: ApproveBody,
    actor: Approver,
) -> dict:
    return _write(request, store.approve, actor, user_id, body.role)


@router.post("/users/{user_id}/reject", response_model=UserItem)
def reject(request: Request, user_id: str, actor: Approver) -> dict:
    return _write(request, store.reject, actor, user_id)


@router.post("/users/{user_id}/disable", response_model=UserItem)
def disable(request: Request, user_id: str, actor: Approver) -> dict:
    return _write(request, store.disable, actor, user_id)


@router.post("/users/{user_id}/reset-password", response_model=UserItem)
def reset_password(
    request: Request,
    user_id: str,
    body: ResetBody,
    actor: Approver,
) -> dict:
    return _write(request, store.reset_password, actor, user_id, body.temporary_password)


@router.patch("/users/{user_id}", response_model=UserItem)
def change_role(
    request: Request,
    user_id: str,
    body: RoleBody,
    actor: RoleSetter,
) -> dict:
    return _write(request, store.set_role, actor, user_id, body.role)


@router.put("/users/{user_id}/permissions", response_model=UserItem)
def replace_permissions(
    request: Request,
    user_id: str,
    body: PermissionsBody,
    actor: PermissionSetter,
) -> dict:
    names = list(dict.fromkeys(body.permissions))
    return _write(request, store.set_permissions, actor, user_id, names)
