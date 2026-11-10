"""Fixed catalogue of read-only AWS tools.

The LLM can only call tools registered here. Each tool is a plain function
``fn(session: boto3.Session, params: dict) -> dict`` returning a trimmed,
JSON-serializable dict (tools registered with ``context=True`` also receive a
``ToolContext``). The ``aws_actions`` list doubles as the source for the IAM policy in
the CloudFormation template, so it must stay accurate.

``run_tool`` validates the parameters against ``input_schema`` (unknown parameters are
rejected too) before any AWS call, and turns every failure into ``{"error": ...}``.
"""

import fnmatch
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from jsonschema import Draft202012Validator

log = logging.getLogger(__name__)

ToolFn = Callable[..., dict]

_ACCESS_DENIED_CODES = {
    "AccessDenied",
    "AccessDeniedException",
    "UnauthorizedOperation",
    "UnauthorizedAccess",
    "AuthorizationError",
}


@dataclass
class ToolContext:
    """What a tool may know about the conversation (only tools registered with context)."""

    # Every user message of the conversation, including the current question.
    user_text: str = ""
    # Hostnames read from configuration (Route 53 records, load balancers, DNS answers).
    known_hostnames: set[str] = field(default_factory=set)


GROUPS = ("compute", "network", "dns", "elb", "metrics", "logs", "cloudtrail")

# Allow-list (AGENTS.md hard constraint #1): an action is read-only only if its verb
# starts with one of these. Anything else (Create*, Run*, Terminate*, ...) is rejected.
READ_ONLY_VERBS = ("Describe", "List", "Get", "LookupEvents", "StartQuery")

# Business data that must never be read even though the verbs look read-only. Used both
# here and as the explicit Deny statement of the CloudFormation template.
DENIED_ACTIONS = [
    "s3:GetObject*",
    "secretsmanager:GetSecretValue",
    "ssm:GetParameter*",
    "kms:Decrypt",
    "dynamodb:GetItem",
    "dynamodb:Query",
    "dynamodb:Scan",
    "rds-data:*",
]

# boto3 service name -> IAM action prefix, where they differ
_IAM_PREFIX = {"elb": "elasticloadbalancing", "elbv2": "elasticloadbalancing"}


def is_read_only_action(action: str) -> bool:
    """True for ``service:Verb`` actions AutoAWS may call (allow-listed verb, not denied)."""
    service, _, verb = action.partition(":")
    if not service or not verb:
        return False
    if any(fnmatch.fnmatchcase(action, pattern) for pattern in DENIED_ACTIONS):
        return False
    return verb.startswith(READ_ONLY_VERBS)


def iam_action(service_name: str, operation_name: str) -> str:
    """IAM action for a botocore operation, e.g. ('elbv2', 'DescribeTargetHealth')."""
    return f"{_IAM_PREFIX.get(service_name, service_name)}:{operation_name}"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    group: str
    label: str
    description: str
    input_schema: dict
    aws_actions: list[str]
    fn: ToolFn
    stub: bool = False
    extra: dict = field(default_factory=dict)
    # fn takes a third argument, the ToolContext of the conversation
    context: bool = False


REGISTRY: dict[str, ToolSpec] = {}


def tool(
    name: str,
    group: str,
    label: str,
    description: str,
    input_schema: dict,
    aws_actions: list[str],
    stub: bool = False,
    context: bool = False,
) -> Callable[[ToolFn], ToolFn]:
    if group not in GROUPS:
        raise ValueError(f"Unknown tool group {group!r}")
    for action in aws_actions:
        if not is_read_only_action(action):
            raise ValueError(f"Tool {name} declares a non read-only action {action}")
    Draft202012Validator.check_schema(input_schema)

    def decorator(fn: ToolFn) -> ToolFn:
        if name in REGISTRY:
            raise ValueError(f"Duplicate tool {name}")
        REGISTRY[name] = ToolSpec(
            name=name,
            group=group,
            label=label,
            description=description,
            input_schema=input_schema,
            aws_actions=aws_actions,
            fn=fn,
            stub=stub,
            context=context,
        )
        return fn

    return decorator


def list_tools() -> list[ToolSpec]:
    """Tools ordered by diagnosis path (group order) then name — stable for UI and prompts."""
    _ensure_loaded()
    return sorted(REGISTRY.values(), key=lambda t: (GROUPS.index(t.group), t.name))


def get_tool(name: str) -> ToolSpec | None:
    _ensure_loaded()
    return REGISTRY.get(name)


def all_aws_actions() -> list[str]:
    actions = {a for spec in list_tools() for a in spec.aws_actions}
    return sorted(actions)


@dataclass
class ToolRunResult:
    output: dict
    status: str  # ok | error
    error: str | None
    duration_ms: int


def validate_params(spec: ToolSpec, params: dict) -> str | None:
    """Error message if ``params`` do not match the tool's input schema, else None."""
    if not isinstance(params, dict):
        return "INVALID_INPUT: arguments must be a JSON object"
    allowed = set(spec.input_schema.get("properties", {}))
    unknown = sorted(set(params) - allowed)
    if unknown:
        hint = ", ".join(sorted(allowed)) or "none"
        return f"INVALID_INPUT: unknown parameter(s) {', '.join(unknown)}; allowed: {hint}"
    errors = sorted(
        Draft202012Validator(spec.input_schema).iter_errors(params), key=lambda e: list(e.path)
    )
    if errors:
        parts = []
        for e in errors[:3]:
            where = ".".join(str(p) for p in e.absolute_path) or "arguments"
            parts.append(f"{where}: {e.message}")
        return "INVALID_INPUT: " + "; ".join(parts)
    return None


def run_tool(
    session: boto3.Session, name: str, params: dict, ctx: ToolContext | None = None
) -> ToolRunResult:
    """Execute a tool, never raising: AWS/user errors become ``{"error": ...}``."""
    spec = get_tool(name)
    started = time.perf_counter()
    if spec is None:
        return ToolRunResult(
            {"error": f"Unknown tool: {name}"}, "error", f"Unknown tool: {name}", 0
        )
    params = {} if params is None else params
    invalid = validate_params(spec, params)
    if invalid:
        return ToolRunResult({"error": invalid}, "error", invalid, 0)
    try:
        if spec.context:
            output = spec.fn(session, params, ctx or ToolContext())
        else:
            output = spec.fn(session, params)
        status = "error" if "error" in output else "ok"
        return ToolRunResult(output, status, output.get("error"), _ms(started))
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "ClientError")
        msg = e.response.get("Error", {}).get("Message", str(e))
        if code in _ACCESS_DENIED_CODES:
            # Name the missing permission so the agent can say exactly what to grant.
            action = _declared_action(spec, getattr(e, "operation_name", ""))
            output = {"error": "AccessDenied", "action": action, "message": msg}
            log.warning("Tool %s denied: %s", name, action)
            return ToolRunResult(output, "error", f"AccessDenied: {action}", _ms(started))
        err = f"{code}: {msg}"
        log.warning("Tool %s failed: %s", name, err)
        return ToolRunResult({"error": err}, "error", err, _ms(started))
    except BotoCoreError as e:
        err = f"{type(e).__name__}: {e}"
        log.warning("Tool %s failed: %s", name, err)
        return ToolRunResult({"error": err}, "error", err, _ms(started))
    except Exception as e:  # noqa: BLE001 — a tool must never break the agent loop
        err = f"{type(e).__name__}: {e}"
        log.exception("Tool %s crashed", name)
        return ToolRunResult({"error": err}, "error", err, _ms(started))


def _declared_action(spec: ToolSpec, operation_name: str) -> str:
    for action in spec.aws_actions:
        if action.partition(":")[2] == operation_name:
            return action
    return spec.aws_actions[0] if len(spec.aws_actions) == 1 else operation_name or "unknown"


def summarize_output(output: dict, max_len: int = 240) -> str:
    """Short, human-readable one-liner for the UI timeline."""
    if "error" in output:
        action = f" ({output['action']})" if output.get("action") else ""
        return f"Error: {output['error']}{action}"[:max_len]
    parts = []
    for key, value in output.items():
        if key.startswith("_"):
            continue
        if isinstance(value, list):
            parts.append(f"{len(value)} {key.replace('_', ' ')}")
        elif isinstance(value, str | int | float | bool):
            parts.append(f"{key}={value}")
    if parts:
        return "; ".join(parts)[:max_len]
    return json.dumps(output, default=str)[:max_len]


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


_loaded = False


def _ensure_loaded() -> None:
    global _loaded
    if not _loaded:
        _loaded = True
        import app.aws.tools  # noqa: F401  (registers every tool)
