"""도구 레지스트리(도구 구현 방식, D-023, #211).

파이썬 함수 도구를 ToolSpec으로 모으고, 실행마다 stage의 허용 목록에 있는 것만 Agents SDK 함수 도구
(FunctionTool)로 감싸 붙인다. 도구 한 번 호출의 순서:

1. SDK가 on_tool_start를 부르고, 기록기(LogRecorder)가 tool_call_id별로 Agent Log 줄(agl_)을 연다.
2. invoke가 같은 tool_call_id로 그 agl_을 받는다. 레지스트리는 ID를 만들지 않는다.
3. 허용 확인(방어선) → 연속 실패 차단 확인 → 인자 검사 → 실행.
4. 결과 자르기 → call_id 붙이기 → 구분자로 감싸기 → 장부에 넣기.
5. 자르기 전 전체 결과와 성공·실패를 기록기에 넘긴다(Agent Log output에는 전체).

도구 결과는 밖에서 온 문자열이다(docs/security.md). 예외 메시지·SQL·DB 주소는 모델에 보내지 않는다.
"""

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from agents import FunctionTool

ResultKind = Literal["records", "text", "aggregate"]
ArgType = Literal["string", "integer"]
ErrorCode = Literal["not_allowed", "invalid_argument", "unavailable", "timeout", "failed"]

ERROR_CODES: tuple[str, ...] = (
    "not_allowed",
    "invalid_argument",
    "unavailable",
    "timeout",
    "failed",
)
RESULT_OPEN = "<tool_result>"
RESULT_CLOSE = "</tool_result>"
# 같은 도구가 이만큼 연속으로 실패하면 남은 턴에서는 실행하지 않는다
MAX_CONSECUTIVE_FAILURES = 2
# 자른 문자열 끝에 붙이는 표시
CUT_MARK = "…"
# 레코드 하나를 줄일 때 이보다 짧은 문자열은 줄이지 않는다
_MIN_SHORTEN = 16


class ToolError(Exception):
    """핸들러가 오류 코드로 실패를 알린다. 메시지는 모델과 detail에 보내지 않는다.

    reason은 Agent Log tool 줄의 details.reason에만 남기는 짧은 사유 이름이다(예: auth, #212).
    모델에게 가는 문구는 reason과 상관없이 같다. 비밀 값이나 응답 본문을 넣지 않는다.
    """

    def __init__(self, code: ErrorCode, reason: str | None = None) -> None:
        if code not in ERROR_CODES:
            raise ValueError("알 수 없는 도구 오류 코드")
        if reason is not None and (not isinstance(reason, str) or not reason):
            raise ValueError("reason은 빈 값이 아닌 문자열이다")
        super().__init__(code)
        self.code = code
        self.reason = reason


class ToolConfigError(Exception):
    """레지스트리나 허용 목록 설정이 잘못됐다(이름 중복, 등록되지 않은 이름 등)."""


@dataclass(frozen=True)
class Arg:
    """도구 인자 하나의 모양. 정의에 없는 인자나 범위 밖 값은 invalid_argument다."""

    name: str
    type: ArgType
    required: bool = False
    enum: tuple[str, ...] | None = None
    minimum: int | None = None
    maximum: int | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None  # 문자열 전체가 맞아야 한다(fullmatch)
    description: str = ""


@dataclass(frozen=True)
class CallContext:
    """핸들러가 받는 호출 정보."""

    call_id: str  # 이 호출의 agl_(Agent Log tool 줄 id)
    tools_config: Mapping[str, Any]  # 설정의 [tools]
    max_result_chars: int
    fits: Callable[[dict[str, Any]], bool]  # aggregate 결과가 한도 안인지(call_id 포함해 셈)


Handler = Callable[[dict[str, Any], CallContext], Any]
Check = Callable[[dict[str, Any], Mapping[str, Any]], None]
CheckConfig = Callable[[Mapping[str, Any]], None]


@dataclass(frozen=True)
class ToolSpec:
    """도구 하나.

    result_kind
    - records: 핸들러가 레코드(dict) 목록을 돌려준다. id_fields 값이 장부에 들어간다.
      뒤 레코드부터 빼서 한도에 맞춘다.
    - text: 핸들러가 문자열을 돌려준다. 글자 수로 자른다.
    - aggregate: 핸들러가 집계 객체(dict)를 돌려준다. 한도는 핸들러가 ctx.fits로 맞춘다.
      장부에는 call_id만 들어간다.
    limit_argument: 이름을 주면 그 정수 인자(기본 [tools] default_limit, 1~max_limit)를 더한다.
    check: 인자 사이의 조건을 실행 전에 검사한다. 맞지 않으면 ToolError("invalid_argument").
    check_config: 설정의 [tools]를 실행 시작 전에 검사한다(#212). 허용 목록에 있는 도구만 부르고,
      틀리면 ToolConfigError를 낸다. 실행은 provider_error("도구 설정 오류")로 끝난다.
    """

    name: str
    description: str
    handler: Handler
    bundle: str
    result_kind: ResultKind
    id_fields: tuple[str, ...] = ()
    limit_argument: str | None = None
    args: tuple[Arg, ...] = ()
    check: Check | None = None
    check_config: CheckConfig | None = None


class ToolRecorder(Protocol):
    """레지스트리가 쓰는 기록기 쪽 함수(LogRecorder가 구현한다)."""

    def tool_log_id(self, tool_call_id: str) -> str | None: ...

    def report_tool(
        self,
        tool_call_id: str,
        output: Any,
        failure: str | None,
        blocked: bool,
        reason: str | None = None,
    ) -> None: ...


class ToolRegistry:
    """ToolSpec을 이름으로 모은다. 실행마다 session()으로 허용 목록만 묶는다."""

    def __init__(self, specs: Iterable[ToolSpec] = ()) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            self.add(spec)

    def add(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ToolConfigError(f"같은 이름의 도구가 있다: {spec.name}")
        names = [a.name for a in spec.args] + ([spec.limit_argument] if spec.limit_argument else [])
        if len(names) != len(set(names)):
            raise ToolConfigError(f"인자 이름이 겹친다: {spec.name}")
        self._specs[spec.name] = spec

    def names(self) -> list[str]:
        return list(self._specs)

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def session(
        self, *, stage: str, config: Mapping[str, Any], recorder: ToolRecorder
    ) -> "ToolSession":
        """stage의 허용 목록으로 실행 하나의 도구 묶음을 만든다. 설정이 잘못되면 ToolConfigError."""
        tools = config.get("tools", {})
        allowed = list(tools.get("allowed", {}).get(stage, []))
        unknown = [name for name in allowed if name not in self._specs]
        if unknown:
            raise ToolConfigError("허용 목록에 등록되지 않은 도구 이름이 있다")
        try:
            max_chars = int(config["agent"][stage]["max_tool_result_chars"])
            strict = bool(config["llm"]["strict_mode"])
        except (KeyError, TypeError, ValueError):
            raise ToolConfigError("도구 결과 한도나 strict_mode 설정이 없다") from None
        specs = [self._specs[name] for name in dict.fromkeys(allowed)]
        for spec in specs:
            if spec.check_config is None:
                continue
            try:
                spec.check_config(tools)
            except ToolConfigError:
                raise
            except Exception:  # 검사 코드의 예외도 설정 오류로 본다. 메시지는 남기지 않는다
                raise ToolConfigError("도구 설정을 검사하지 못했다") from None
        return ToolSession(
            specs=specs,
            tools_config=tools,
            max_chars=max_chars,
            strict=strict,
            recorder=recorder,
        )


class ToolSession:
    """실행 하나의 도구 묶음. 연속 실패 수와 근거 장부(evidence_ids)를 가진다."""

    def __init__(
        self,
        *,
        specs: list[ToolSpec],
        tools_config: Mapping[str, Any],
        max_chars: int,
        strict: bool,
        recorder: ToolRecorder,
    ) -> None:
        self._specs = {spec.name: spec for spec in specs}
        self._tools_config = tools_config
        self._max_chars = max_chars
        self._strict = strict
        self._recorder = recorder
        self._failures: dict[str, int] = {}
        self.evidence_ids: set[str] = set()

    def function_tools(self) -> list[FunctionTool]:
        """허용 목록의 도구만 SDK 함수 도구로 감싼다. 목록 밖 도구는 모델에게 보이지 않는다."""
        return [self._function_tool(spec) for spec in self._specs.values()]

    def _function_tool(self, spec: ToolSpec) -> FunctionTool:
        async def on_invoke(ctx: Any, arguments: str) -> str:
            return await self.invoke(spec.name, arguments, getattr(ctx, "tool_call_id", ""))

        return FunctionTool(
            name=spec.name,
            description=spec.description,
            params_json_schema=_json_schema(spec, self._tools_config),
            on_invoke_tool=on_invoke,
            strict_json_schema=self._strict,
        )

    async def invoke(self, name: str, arguments: str, tool_call_id: str) -> str:
        """레지스트리 함수. 모델에게 보낼 문자열을 돌려주고, 예외를 밖으로 내지 않는다."""
        spec = self._specs.get(name)
        if spec is None:
            # 허용 목록 밖에서 불렸다(방어선). SDK에는 등록하지 않으므로 보통은 오지 않는다.
            return self._fail(name, tool_call_id, "not_allowed")
        if self._failures.get(name, 0) >= MAX_CONSECUTIVE_FAILURES:
            return self._fail(name, tool_call_id, "not_allowed", blocked=True)
        call_id = self._recorder.tool_log_id(tool_call_id)
        if call_id is None:
            # 기록기에 이 호출의 줄이 없다(빈·중복 tool_call_id). call_id를 줄 수 없으므로 실패다.
            return self._fail(name, tool_call_id, "failed")
        try:
            args = _parse_arguments(spec, arguments, self._tools_config)
            if spec.check is not None:
                spec.check(args, self._tools_config)
        except ToolError as exc:
            return self._fail(name, tool_call_id, exc.code, reason=exc.reason)
        ctx = CallContext(
            call_id=call_id,
            tools_config=self._tools_config,
            max_result_chars=self._max_chars,
            fits=lambda body: self._fits({"call_id": call_id, **body}),
        )
        try:
            raw = spec.handler(args, ctx)
            body, shown_ids = self._shape(spec, call_id, raw)
        except ToolError as exc:
            return self._fail(name, tool_call_id, exc.code, reason=exc.reason)
        except Exception:  # 메시지에 SQL·주소가 들어 있을 수 있어 종류도 남기지 않는다
            return self._fail(name, tool_call_id, "failed")
        self._failures[name] = 0
        self.evidence_ids.add(call_id)
        self.evidence_ids.update(shown_ids)
        self._recorder.report_tool(tool_call_id, raw, None, False)
        return _wrap(_dump(body))

    def _fail(
        self,
        name: str,
        tool_call_id: str,
        code: str,
        *,
        blocked: bool = False,
        reason: str | None = None,
    ) -> str:
        text = tool_error_text(name, code)
        if name in self._specs:
            self._failures[name] = self._failures.get(name, 0) + 1
        self._recorder.report_tool(tool_call_id, text, code, blocked, reason)
        return text

    def _fits(self, body: dict[str, Any]) -> bool:
        return len(_dump(body)) <= self._max_chars

    def _shape(self, spec: ToolSpec, call_id: str, raw: Any) -> tuple[dict[str, Any], list[str]]:
        """(모델에게 보낼 본문, 장부에 넣을 레코드 ID)."""
        if spec.result_kind == "records":
            if not isinstance(raw, list) or not all(isinstance(r, dict) for r in raw):
                raise TypeError("records 도구는 dict 목록을 돌려준다")
            return self._shape_records(spec, call_id, raw)
        if spec.result_kind == "text":
            if not isinstance(raw, str):
                raise TypeError("text 도구는 문자열을 돌려준다")
            return self._shape_text(call_id, raw), []
        if not isinstance(raw, dict) or "call_id" in raw:
            raise TypeError("aggregate 도구는 call_id 없는 dict를 돌려준다")
        body = {"call_id": call_id, **raw}
        if not self._fits(body):
            raise ToolError("failed")  # 핸들러가 ctx.fits로 맞추지 못했다
        return body, []

    def _shape_records(
        self, spec: ToolSpec, call_id: str, records: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], list[str]]:
        total = len(records)
        shown = list(records)
        body: dict[str, Any] = {"call_id": call_id, "records": shown, "truncated": False}
        body["omitted"] = 0
        # JSON 중간은 자르지 않는다. 뒤 레코드부터 뺀다.
        while shown and not self._fits(body):
            shown.pop()
            body["truncated"] = True
            body["omitted"] = total - len(shown)
        if not shown and total:
            first, paths = _shorten(records[0], spec.id_fields, self._fits_record(call_id, total))
            if first is not None:
                shown.append(first)
                body["omitted"] = total - 1
                body["truncated_fields"] = paths
        ids = [r[f] for r in shown for f in spec.id_fields if isinstance(r.get(f), str)]
        return body, ids

    def _fits_record(self, call_id: str, total: int) -> Callable[[dict[str, Any], list[str]], bool]:
        def fits(record: dict[str, Any], paths: list[str]) -> bool:
            body = {
                "call_id": call_id,
                "records": [record],
                "truncated": True,
                "omitted": total - 1,
                "truncated_fields": paths,
            }
            return self._fits(body)

        return fits

    def _shape_text(self, call_id: str, text: str) -> dict[str, Any]:
        body: dict[str, Any] = {"call_id": call_id, "text": text, "truncated": False}
        if self._fits(body):
            return body
        body["truncated"] = True
        low, high = 0, len(text)
        # 본문이 한도에 맞는 가장 긴 앞부분을 찾는다(이스케이프로 글자 수가 늘 수 있다)
        while low < high:
            mid = (low + high + 1) // 2
            body["text"] = text[:mid] + CUT_MARK
            if self._fits(body):
                low = mid
            else:
                high = mid - 1
        body["text"] = text[:low] + CUT_MARK
        return body


def tool_error_text(name: str, code: str) -> str:
    """모델에게 보내는 오류 문구. 예외 메시지·SQL·DB 주소·call_id는 넣지 않는다."""
    return f"TOOL_ERROR tool={name} code={code}\n다른 도구를 쓰거나 지금까지의 근거로 답하라"


def _dump(body: dict[str, Any]) -> str:
    """모델에게 보낼 JSON 본문. '<'·'>'를 바꿔 구분자를 닫지 못하게 한다(wrap_data와 같다)."""
    text = json.dumps(body, ensure_ascii=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e")


def _wrap(body: str) -> str:
    return f"{RESULT_OPEN}\n{body}\n{RESULT_CLOSE}"


def _shorten(
    record: dict[str, Any],
    id_fields: tuple[str, ...],
    fits: Callable[[dict[str, Any], list[str]], bool],
) -> tuple[dict[str, Any] | None, list[str]]:
    """레코드 하나를 긴 문자열 값부터 줄여 한도에 맞춘다. 못 맞추면 (None, [])."""
    current = json.loads(json.dumps(record))  # 원본(Agent Log에 쓸 전체)은 바꾸지 않는다
    paths: list[str] = []
    while not fits(current, paths):
        leaves = [
            (len(value), path, keys)
            for path, keys, value in _string_leaves(current)
            # 이미 최소 길이까지 줄인 값(_MIN_SHORTEN + 표시)은 더 줄이지 않는다
            if len(value) > _MIN_SHORTEN + len(CUT_MARK)
            and not (len(keys) == 1 and keys[0] in id_fields)
        ]
        if not leaves:
            return None, []
        _, path, keys = max(leaves, key=lambda leaf: leaf[0])
        value = _get(current, keys)
        keep = max(_MIN_SHORTEN, len(value.rstrip(CUT_MARK)) // 2)
        _set(current, keys, value[:keep].rstrip(CUT_MARK) + CUT_MARK)
        if path not in paths:
            paths.append(path)
    return current, paths


def _string_leaves(value: Any, path: str = "", keys: tuple[Any, ...] = ()) -> Iterable[Any]:
    if isinstance(value, str):
        yield path, keys, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _string_leaves(item, f"{path}.{key}" if path else str(key), (*keys, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _string_leaves(item, f"{path}[{index}]", (*keys, index))


def _get(value: Any, keys: tuple[Any, ...]) -> Any:
    for key in keys:
        value = value[key]
    return value


def _set(value: Any, keys: tuple[Any, ...], new: Any) -> None:
    for key in keys[:-1]:
        value = value[key]
    value[keys[-1]] = new


# 인자


def _all_args(spec: ToolSpec, tools_config: Mapping[str, Any]) -> list[Arg]:
    args = list(spec.args)
    if spec.limit_argument:
        args.append(
            Arg(
                spec.limit_argument,
                "integer",
                minimum=1,
                maximum=int(tools_config.get("max_limit", 100)),
                description="돌려받을 최대 건수",
            )
        )
    return args


def _json_schema(spec: ToolSpec, tools_config: Mapping[str, Any]) -> dict[str, Any]:
    """strict 모드 모양: 모든 속성이 required이고, 선택 인자는 null을 허용한다."""
    properties: dict[str, Any] = {}
    for arg in _all_args(spec, tools_config):
        prop: dict[str, Any] = {"type": arg.type if arg.required else [arg.type, "null"]}
        if arg.description:
            prop["description"] = arg.description
        if arg.enum is not None:
            prop["enum"] = list(arg.enum) if arg.required else [*arg.enum, None]
        if arg.minimum is not None:
            prop["minimum"] = arg.minimum
        if arg.maximum is not None:
            prop["maximum"] = arg.maximum
        if arg.min_length is not None:
            prop["minLength"] = arg.min_length
        if arg.max_length is not None:
            prop["maxLength"] = arg.max_length
        if arg.pattern is not None:
            prop["pattern"] = arg.pattern
        properties[arg.name] = prop
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _parse_arguments(
    spec: ToolSpec, arguments: str, tools_config: Mapping[str, Any]
) -> dict[str, Any]:
    """인자 JSON을 읽고 모양을 검사한다. 선택 인자가 없거나 null이면 None(limit은 기본값)."""
    try:
        data = json.loads(arguments) if arguments else {}
    except ValueError:
        raise ToolError("invalid_argument") from None
    if not isinstance(data, dict):
        raise ToolError("invalid_argument")
    defined = {arg.name: arg for arg in _all_args(spec, tools_config)}
    if set(data) - set(defined):
        raise ToolError("invalid_argument")  # 정의에 없는 인자
    out: dict[str, Any] = {}
    for name, arg in defined.items():
        value = data.get(name)
        if value is None:
            if arg.required:
                raise ToolError("invalid_argument")
            out[name] = None
            continue
        _check_value(arg, value)
        out[name] = value
    if spec.limit_argument and out[spec.limit_argument] is None:
        out[spec.limit_argument] = int(tools_config.get("default_limit", 20))
    return out


def _check_value(arg: Arg, value: Any) -> None:
    if arg.type == "integer":
        if type(value) is not int:  # bool·float·문자열 숫자는 받지 않는다
            raise ToolError("invalid_argument")
        if arg.minimum is not None and value < arg.minimum:
            raise ToolError("invalid_argument")
        if arg.maximum is not None and value > arg.maximum:
            raise ToolError("invalid_argument")
    else:
        if not isinstance(value, str):
            raise ToolError("invalid_argument")
        if arg.min_length is not None and len(value) < arg.min_length:
            raise ToolError("invalid_argument")
        if arg.max_length is not None and len(value) > arg.max_length:
            raise ToolError("invalid_argument")
        if arg.pattern is not None and not re.fullmatch(arg.pattern, value):
            raise ToolError("invalid_argument")
    if arg.enum is not None and value not in arg.enum:
        raise ToolError("invalid_argument")
