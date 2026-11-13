"""도구 레지스트리의 공유 객체(services)와 number 인자(#313)."""

import asyncio
from typing import Any

import pytest
from test_agent_core import CONFIG
from tool_helpers import Caller, new_recorder, parse

from soc.tools import Arg, ToolRegistry, ToolSpec


def _spec(**kwargs: Any) -> ToolSpec:
    def handler(args: dict[str, Any], ctx: Any) -> dict[str, Any]:
        return {"seen": sorted(ctx.services), "score": args.get("score")}

    base: dict[str, Any] = {
        "name": "needs_service",
        "description": "테스트용",
        "handler": handler,
        "bundle": "test",
        "result_kind": "aggregate",
        "args": (Arg("score", "number", minimum=0, maximum=1),),
    }
    return ToolSpec(**{**base, **kwargs})


def _config() -> dict[str, Any]:
    tools = {**CONFIG["tools"], "allowed": {"l1": ["needs_service"]}}
    return {**CONFIG, "tools": tools}


def _session(spec: ToolSpec, services: dict[str, Any] | None):
    return ToolRegistry([spec]).session(
        stage="l1", config=_config(), recorder=new_recorder("l1"), services=services
    )


def _names(session: Any) -> list[str]:
    return [tool.name for tool in session.function_tools()]


def test_tool_with_required_service_is_hidden_without_it() -> None:
    spec = _spec(requires_service="similar")

    assert _names(_session(spec, None)) == []
    assert _names(_session(spec, {"other": 1})) == []
    assert _names(_session(spec, {"similar": object()})) == ["needs_service"]


def test_tool_without_requirement_is_always_registered() -> None:
    assert _names(_session(_spec(), None)) == ["needs_service"]


def test_handler_receives_services_through_context() -> None:
    caller = Caller(ToolRegistry([_spec()]), _config(), services={"similar": object()})

    out = asyncio.run(caller("needs_service", {"score": 0.5}))

    assert parse(out)["seen"] == ["similar"]


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("0.5", True),
        ("1", True),
        ("0", True),
        ("1.5", False),
        ("-0.1", False),
        ('"0.5"', False),
        ("true", False),
        ("NaN", False),
        ("Infinity", False),
    ],
)
def test_number_argument_accepts_only_finite_numbers_in_range(value: str, ok: bool) -> None:
    caller = Caller(ToolRegistry([_spec()]), _config())

    out = asyncio.run(caller("needs_service", f'{{"score": {value}}}'))

    assert out.startswith("<tool_result>") is ok
