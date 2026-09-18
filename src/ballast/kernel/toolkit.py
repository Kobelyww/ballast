"""Tool layer: schema inference, argument validation, and structured failures.

Three deliberate choices:

1. **Schemas come from type hints.** One source of truth; the Python signature, the
   JSON-Schema the model sees and the validator that checks the call cannot drift.
2. **Model-authored arguments are untrusted input.** They are type-checked, coerced
   where the intent is unambiguous (`"12.5"` -> 12.5), and otherwise bounced back as
   a readable error. A model that gets a stack trace improvises; a model that gets
   `{"error": "unknown_argument", "did_you_mean": "order_id"}` corrects itself.
3. **Policy lives in code, not in the prompt.** A mutating tool refuses to act on
   arguments it cannot re-derive from its own deterministic engine, which is what
   turns "the agent should not over-refund" from a hope into an invariant.
"""

from __future__ import annotations

import enum
import inspect
import json
import re
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, get_args, get_origin

from .hitl import Interrupt

JSON_TYPE = {str: "string", int: "integer", float: "number", bool: "boolean"}


class ToolError(Exception):
    """A refusal that should reach the model as a readable, actionable message."""

    def __init__(self, code: str, message: str, *, hint: str = "", retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.retryable = retryable

    def as_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, "hint": self.hint, "retryable": self.retryable}


@dataclass(slots=True)
class Param:
    name: str
    json_type: str
    description: str = ""
    required: bool = True
    enum: list[Any] | None = None
    items: str | None = None
    default: Any = None

    def as_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": self.json_type}
        if self.items:
            schema["items"] = {"type": self.items}
        if self.enum is not None:
            schema["enum"] = list(self.enum)
        if self.description:
            schema["description"] = self.description
        if not self.required and self.default is not None:
            schema["default"] = self.default
        return schema


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]
    params: list[Param] = field(default_factory=list)
    mutating: bool = False
    tags: list[str] = field(default_factory=list)

    def schema(self) -> dict[str, Any]:
        required = [p.name for p in self.params if p.required]
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {p.name: p.as_schema() for p in self.params},
                    "required": required,
                },
            },
        }

    def validate(self, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Return (coerced args, problems). Problems are model-facing correction strings."""
        problems: list[str] = []
        if not isinstance(args, dict):
            return {}, [f"arguments must be a JSON object, got {type(args).__name__}"]
        by_name = {p.name: p for p in self.params}
        out: dict[str, Any] = {}

        for key, value in args.items():
            param = by_name.get(key)
            if param is None:
                near = _closest(key, by_name)
                problems.append(f"unknown_argument: '{key}' is not accepted by {self.name}" + (f" (did you mean '{near}'?)" if near else ""))
                continue
            try:
                out[key] = _coerce(value, param, key)
            except ValueError as exc:
                problems.append(str(exc))

        for param in self.params:
            if param.required and param.name not in out:
                problems.append(f"missing_required_argument: '{param.name}' ({param.json_type}) — {param.description}".rstrip(" —"))
            elif not param.required and param.name not in out and param.default is not None:
                out[param.name] = param.default
        return out, problems

    def call(self, args: dict[str, Any]) -> Any:
        return self.fn(**args)


def _closest(token: str, candidates: dict[str, Param]) -> str | None:
    norm = re.sub(r"[^a-z0-9]", "", token.lower())
    best: tuple[int, str] | None = None
    for name in candidates:
        cmp = re.sub(r"[^a-z0-9]", "", name.lower())
        if cmp == norm:
            return name
        dist = _levenshtein(norm, cmp)
        if dist <= 3 and (best is None or dist < best[0]):
            best = (dist, name)
    return best[1] if best else None


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _coerce(value: Any, param: Param, key: str) -> Any:
    want = param.json_type

    if want == "string":
        out = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    elif want == "boolean":
        if isinstance(value, bool):
            out = value
        elif isinstance(value, str) and value.strip().lower() in {"true", "1", "yes"}:
            out = True
        elif isinstance(value, str) and value.strip().lower() in {"false", "0", "no"}:
            out = False
        else:
            raise ValueError(f"invalid_type: '{key}' expected boolean, got {value!r}")
    elif want in {"integer", "number"}:
        out = _coerce_number(value, key, want)
    elif want == "array":
        out = _coerce_array(value, key, param.items or "string")
    elif want == "object":
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise ValueError(f"invalid_type: '{key}' expected a JSON object string") from None
        if not isinstance(value, dict):
            raise ValueError(f"invalid_type: '{key}' expected object, got {type(value).__name__}")
        out = value
    else:
        out = value

    if param.enum is not None and out not in param.enum:
        raise ValueError(f"invalid_enum: '{key}'={out!r} not in {list(param.enum)}")
    return out


def _coerce_number(value: Any, key: str, want: str) -> int | float:
    if isinstance(value, bool):
        raise ValueError(f"invalid_type: '{key}' expected {want}, got boolean")
    if isinstance(value, (int, float)):
        pass
    elif isinstance(value, str):
        cleaned = re.sub(r"[,\s¥$￥]", "", value)
        try:
            value = int(cleaned) if want == "integer" else float(cleaned)
        except ValueError:
            raise ValueError(f"invalid_type: '{key}' expected {want}, got {value!r}") from None
    else:
        raise ValueError(f"invalid_type: '{key}' expected {want}, got {type(value).__name__}")
    if want == "integer":
        as_int = int(round(float(value)))
        if abs(float(value) - as_int) > 1e-9:
            raise ValueError(f"invalid_type: '{key}' expected integer, got fractional {value}")
        return as_int
    return float(value)


def _coerce_array(value: Any, key: str, item_type: str) -> list[Any]:
    if isinstance(value, str):
        stripped = value.strip()
        try:
            parsed = json.loads(stripped) if stripped.startswith(("[", "{")) else re.split(r"[,，;；\s]+", stripped)
        except json.JSONDecodeError:
            parsed = re.split(r"[,，;；\s]+", stripped)
        value = [p for p in parsed if p != ""] if isinstance(parsed, list) else parsed
    if isinstance(value, (dict, set, tuple)):
        value = list(value)
    if not isinstance(value, list):
        value = [value]
    return [_coerce(item, Param(name=key, json_type=item_type), key) for item in value]


def _describe(annotation: Any) -> tuple[str, str | None, list[Any] | None]:
    """-> (json type, array item type, enum values)"""
    if isinstance(annotation, str):
        # `from __future__ import annotations` leaves strings behind when a forward
        # ref cannot be resolved; map the handful that ever appear on a tool signature.
        names = {"str": str, "int": int, "float": float, "bool": bool, "list[str]": list, "List[str]": list, "dict": dict}
        mapped = names.get(annotation)
        if mapped is list:
            return "array", "string", None
        if mapped is None:
            return "string", None, None
        annotation = mapped
    if annotation is inspect.Parameter.empty or annotation is Any:
        return "string", None, None
    origin = get_origin(annotation)
    if origin is Literal:
        values = list(get_args(annotation))
        return _json_type_of(values[0] if values else ""), None, values
    if origin in (list, set, tuple, typing.List):  # noqa: UP006
        inner = (get_args(annotation) or (str,))[0]
        inner_t, _, inner_enum = _describe(inner)
        if inner_enum and origin is list:
            return "array", inner_t, None
        return "array", inner_t, inner_enum if False else None
    if origin is typing.Union or origin is types.UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return _describe(args[0])
        if all(get_origin(a) is Literal for a in args):
            values = sorted({v for a in args for v in get_args(a)})
            return "string", None, values
        return "string", None, None
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return _json_type_of(annotation.__mro__[1] if annotation.__mro__[1] not in (enum.Enum, annotation) else str), None, [m.value for m in annotation]
    if annotation is dict or origin is dict:
        return "object", None, None
    return _json_type_of(annotation), None, None


def _json_type_of(annotation: Any) -> str:
    if annotation in JSON_TYPE:
        return JSON_TYPE[annotation]
    if isinstance(annotation, type):
        for python_type, json_name in JSON_TYPE.items():
            if issubclass(annotation, python_type):
                return json_name
    return "string"


_ARG_DOC = re.compile(r"^\s{0,8}(\w+)\s*(?:\(([^)]*)\))?\s*:\s*(.+?)\s*$")


def _parse_arg_docs(doc: str) -> dict[str, str]:
    """Read Google-style `Args:` sections so descriptions need no second source."""
    out: dict[str, str] = {}
    in_args = False
    current: str | None = None
    for line in doc.splitlines():
        stripped = line.strip()
        if re.match(r"^(Args|Arguments|Parameters)\s*:$", stripped, re.I):
            in_args = True
            continue
        if in_args and re.match(r"^(Returns|Raises|Yields|Examples|Note|Warning)s?\s*:$", stripped, re.I):
            break
        if not in_args:
            continue
        match = _ARG_DOC.match(line)
        if match and match.group(1) != "self":
            current = match.group(1)
            out[current] = match.group(3).strip()
        elif current and stripped:
            out[current] += " " + stripped
        elif not stripped:
            current = None
    return out


def tool(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    mutating: bool = False,
    tags: list[str] | None = None,
    enums: dict[str, list[Any]] | None = None,
) -> Any:
    """Build a `Tool` from a plain function's signature + docstring."""

    def wrap(func: Callable[..., Any]) -> Tool:
        doc = inspect.getdoc(func) or ""
        lines = [ln.strip() for ln in doc.splitlines() if ln.strip()]
        summary = lines[0] if lines else func.__name__
        arg_docs = _parse_arg_docs(doc)
        hints = _resolve_hints(func)
        params: list[Param] = []
        for pname, pobj in inspect.signature(func).parameters.items():
            if pname in ("self", "cls") or pobj.kind in (pobj.VAR_POSITIONAL, pobj.VAR_KEYWORD):
                continue
            json_type, items, inferred_enum = _describe(hints.get(pname, pobj.annotation))
            enum_values = (enums or {}).get(pname) or inferred_enum
            params.append(
                Param(
                    name=pname,
                    json_type=json_type,
                    description=arg_docs.get(pname, ""),
                    required=pobj.default is inspect.Parameter.empty,
                    enum=enum_values,
                    items=items,
                    default=None if pobj.default is inspect.Parameter.empty else pobj.default,
                )
            )
        return Tool(
            name=name or func.__name__,
            description=(description or summary).strip(),
            fn=func,
            params=params,
            mutating=mutating,
            tags=tags or [],
        )

    return wrap(fn) if fn is not None else wrap


def _resolve_hints(func: Callable[..., Any]) -> dict[str, Any]:
    try:
        return typing.get_type_hints(func, globalns=getattr(func, "__globals__", None), include_extras=True)
    except Exception:  # noqa: BLE001 - a forward ref should not kill tool discovery
        return {k: v for k, v in getattr(func, "__annotations__", {}).items() if k != "return"}


@dataclass(slots=True)
class ToolResult:
    name: str
    ok: bool
    content: str
    error: dict[str, Any] | None = None
    validation_problems: list[str] = field(default_factory=list)
    latency_ms: float = 0.0

    def as_message(self, call_id: str) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": call_id, "name": self.name, "content": self.content}


class Toolkit:
    """Registry + dispatcher. Unknown tools bounce back with the real menu."""

    def __init__(self, tools: list[Tool] | None = None, *, strict: bool = True) -> None:
        self.strict = strict
        self._tools: dict[str, Tool] = {}
        for item in tools or []:
            self.register(item)
        self.rejections = 0

    def register(self, tool_: Tool) -> None:
        self._tools[tool_.name] = tool_

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        selected = [self._tools[n] for n in names if n in self._tools] if names else list(self._tools.values())
        return [t.schema() for t in selected]

    def execute(self, name: str, args: dict[str, Any], *, call_id: str = "call_0") -> ToolResult:
        import time

        started = time.perf_counter()
        tool_ = self._tools.get(name)
        if tool_ is None:
            self.rejections += 1
            payload = ToolError("unknown_tool", f"no tool named '{name}'", hint=f"available: {', '.join(self.names)}").as_dict()
            return ToolResult(name=name, ok=False, content=json.dumps(payload, ensure_ascii=False), error=payload)

        clean, problems = tool_.validate(args or {})
        if problems:
            self.rejections += 1
            payload = ToolError(
                "invalid_arguments",
                f"{name} was called with unusable arguments",
                hint="; ".join(problems[:4]),
            ).as_dict()
            payload["problems"] = problems
            return ToolResult(
                name=name,
                ok=False,
                content=json.dumps(payload, ensure_ascii=False),
                error=payload,
                validation_problems=problems,
            )

        try:
            raw = tool_.call(clean)
        except Interrupt:
            # Control flow, not a failure. Swallowing this into an error result turns a
            # run that should park into one that keeps spending — the durable-execution
            # bug this runtime exists to avoid.
            raise
        except ToolError as exc:
            payload = exc.as_dict()
            return ToolResult(name=name, ok=False, content=json.dumps(payload, ensure_ascii=False), error=payload)
        except Exception as exc:  # noqa: BLE001 - tool bugs must not kill the run
            payload = ToolError(
                "tool_crashed",
                f"{name} raised {type(exc).__name__}: {exc}",
                hint="try a narrower call or escalate",
                retryable=True,
            ).as_dict()
            return ToolResult(name=name, ok=False, content=json.dumps(payload, ensure_ascii=False), error=payload)

        content = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, default=str)
        return ToolResult(name=name, ok=True, content=content, latency_ms=round((time.perf_counter() - started) * 1000, 2))

    def prompt_section(self) -> str:
        """Compact tool menu for system prompts (cheaper than full JSON-Schema)."""
        return "\n".join(f"- {t.name}: {t.description}" for t in self._tools.values())
