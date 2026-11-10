"""로그인·사용자 관리 API의 요청·응답 모델(#284). API 전용이고 contracts/의 계약이 아니다.

요청 본문 검사 오류는 필드 이름만 돌려준다(errors.py). 비밀번호는 응답에 담지 않는다.
사용자가 쓴 문자열(아이디, 표시 이름)은 가공하지 않고 돌려주며 화면은 텍스트로만 보인다(D-019).
"""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from soc.auth.passwords import MAX_LENGTH, MIN_LENGTH
from soc.auth.permissions import ANALYST_DEFAULT, PERMISSIONS

Role = Literal["admin", "analyst"]
UserStatus = Literal["pending", "active", "rejected", "disabled"]
PermissionName = Literal[*PERMISSIONS]  # type: ignore[valid-type]
NewPassword = Annotated[str, Field(min_length=MIN_LENGTH, max_length=MAX_LENGTH)]

_USERNAME = re.compile(r"[a-z0-9._-]{3,64}")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LoginBody(_Model):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    password: Annotated[str, Field(min_length=1, max_length=MAX_LENGTH)]

    @field_validator("username")
    @classmethod
    def lower(cls, value: str) -> str:
        return value.lower()


class SignupBody(_Model):
    username: Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)]
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    password: NewPassword

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        value = value.lower()
        if not _USERNAME.fullmatch(value):
            raise ValueError("아이디 형식이 맞지 않다")
        return value

    @field_validator("display_name")
    @classmethod
    def printable(cls, value: str) -> str:
        if not value.isprintable():
            raise ValueError("표시 이름에 제어 문자를 쓸 수 없다")
        return value


class PasswordBody(_Model):
    current_password: Annotated[str, Field(min_length=1, max_length=MAX_LENGTH)]
    new_password: NewPassword


class ApproveBody(_Model):
    role: Role


class RoleBody(_Model):
    role: Role


class ResetBody(_Model):
    temporary_password: NewPassword


class PermissionsBody(_Model):
    permissions: Annotated[list[PermissionName], Field(max_length=64)]


class Me(_Model):
    id: str
    username: str
    display_name: str
    role: Role
    must_change_password: bool
    permissions: list[str]


class SignupResult(_Model):
    username: str
    status: Literal["pending"]


class UserItem(_Model):
    id: str
    username: str
    display_name: str
    role: Role | None
    status: UserStatus
    must_change_password: bool
    permissions: list[str]
    created_at: int
    approved_at: int | None


class UserList(_Model):
    items: list[UserItem]
    next_cursor: str | None


class PermissionItem(_Model):
    name: str
    analyst_default: bool


class PermissionList(_Model):
    permissions: list[PermissionItem]


ANALYST_DEFAULTS = frozenset(ANALYST_DEFAULT)
