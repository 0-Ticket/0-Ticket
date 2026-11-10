"""로그인·로그아웃·가입·내 정보·비밀번호 변경(#284).

login·signup만 인증 없이 열린다(public). 나머지는 session 라우터이고, 임시 비밀번호를 바꾸기 전에도
쓸 수 있다(me, logout, password). 응답에는 비밀번호와 토큰을 담지 않는다. 쿠키로만 간다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from soc.api import db
from soc.api.auth import session_user
from soc.api.auth_models import (
    LoginBody,
    Me,
    PasswordBody,
    SignupBody,
    SignupResult,
)
from soc.api.config import ApiSettings
from soc.auth import store
from soc.auth.store import User

public = APIRouter()
session = APIRouter()


def _me(record: dict) -> Me:
    keys = Me.model_fields
    return Me(**{k: record[k] for k in keys})


def _set_cookie(response: Response, settings: ApiSettings, token: str) -> None:
    auth = settings.auth
    response.set_cookie(
        auth.cookie_name,
        token,
        max_age=auth.absolute_timeout_seconds,
        httponly=True,
        samesite="lax",
        secure=auth.cookie_secure,
        path="/",
    )


@public.post("/auth/login", response_model=Me)
def login(body: LoginBody, request: Request, response: Response) -> Me:
    settings: ApiSettings = request.app.state.settings
    with db.connect_write(settings) as conn:
        token, record = store.login(
            conn,
            body.username,
            body.password,
            settings.auth.idle_timeout_seconds,
            settings.auth.absolute_timeout_seconds,
        )
    _set_cookie(response, settings, token)
    return _me(record)


@public.post("/auth/signup", response_model=SignupResult, status_code=201)
def signup(body: SignupBody, request: Request) -> SignupResult:
    with db.connect_write(request.app.state.settings) as conn:
        store.signup(conn, body.username, body.display_name, body.password)
    return SignupResult(username=body.username, status="pending")


@session.get("/auth/me", response_model=Me)
def me(user: Annotated[User, Depends(session_user)]) -> Me:
    return Me(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,  # type: ignore[arg-type]
        must_change_password=user.must_change_password,
        permissions=sorted(user.permissions),
    )


@session.post("/auth/logout", status_code=204, response_class=Response)
def logout(request: Request) -> Response:
    settings: ApiSettings = request.app.state.settings
    token = request.cookies.get(settings.auth.cookie_name)
    if token:
        with db.connect_write(settings) as conn:
            store.logout(conn, token)
    response = Response(status_code=204)
    response.delete_cookie(settings.auth.cookie_name, path="/")
    return response


@session.post("/auth/password", response_model=Me)
def change_password(
    body: PasswordBody,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(session_user)],
) -> Me:
    settings: ApiSettings = request.app.state.settings
    with db.connect_write(settings) as conn:
        token, record = store.change_password(
            conn,
            user,
            body.current_password,
            body.new_password,
            settings.auth.idle_timeout_seconds,
            settings.auth.absolute_timeout_seconds,
        )
    _set_cookie(response, settings, token)
    return _me(record)
