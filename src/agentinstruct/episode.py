"""Task-owned accepted history, private evidence and durable recording."""

import asyncio
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, is_dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import uuid4

from pydantic import JsonValue, TypeAdapter

if TYPE_CHECKING:
    from agentinstruct.judge import Evaluator

_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


class PersistenceError(OSError):
    """Recording failed before an operation could become durable."""


def json_data(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: json_data(item) for key, item in vars(value).items()}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        return {key: json_data(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_data(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON numbers must be finite")
    return _JSON_VALUE.validate_python(value, strict=True)


def canonical_json(value: object) -> str:
    return json.dumps(
        json_data(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def parse_json(text: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON object key")
            result[key] = value
        return result

    def number(token: str) -> float:
        return cast(float, json_data(float(token)))

    return json.loads(
        text, object_pairs_hook=pairs, parse_constant=number, parse_float=number
    )


def freeze(value: object) -> Any:
    def immutable(data: Any) -> Any:
        if isinstance(data, dict):
            return MappingProxyType(
                {key: immutable(item) for key, item in data.items()}
            )
        if isinstance(data, list):
            return tuple(immutable(item) for item in data)
        return data

    return immutable(json_data(value))


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def output_path(value: str | Path) -> Path:
    path = Path(os.path.abspath(value))
    current = Path(path.anchor)
    aliases = {Path("/tmp"): Path("/private/tmp"), Path("/var"): Path("/private/var")}
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            if current not in aliases or current.resolve() != aliases[current]:
                raise ValueError("Output paths cannot contain symbolic links")
            current = current.resolve()
    if current.is_file() and current.stat().st_nlink > 1:
        raise ValueError("Output cannot overwrite hard-linked evidence")
    return current


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_json(path: Path, value: object) -> None:
    path = output_path(path)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(canonical_json(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        _sync_directory(path.parent)
    except OSError as exc:
        raise PersistenceError("JSON publication failed") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _append_json(path: Path, value: object) -> None:
    try:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(canonical_json(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise PersistenceError("Ledger append failed") from exc


@dataclass(frozen=True)
class FunctionCall:
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Tool function requires a name")
        if not isinstance(self.arguments, Mapping):
            raise ValueError("Tool arguments must be an object")
        canonical_json(self.arguments)
        object.__setattr__(self, "arguments", freeze(self.arguments))


@dataclass(frozen=True)
class ToolCall:
    id: str
    function: FunctionCall
    type: Literal["function"] = "function"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, str)
            or not self.id.strip()
            or self.type != "function"
        ):
            raise ValueError("Tool calls require a stable ID and function type")
        if not isinstance(self.function, FunctionCall):
            raise ValueError("Tool calls require a FunctionCall")


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    name: str | None = None
    id: str = ""
    actor_id: str | None = None
    control: Literal["complete"] | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    visibility: Literal["shared", "private"] = "shared"
    segment: str | None = None
    turn_id: str | None = None
    timestamp: str = ""
    reasoning: tuple[Mapping[str, Any], ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("Unknown message role")
        if not isinstance(self.content, str) or self.control not in {None, "complete"}:
            raise ValueError("Messages require text and a supported completion signal")
        if self.visibility not in {"shared", "private"}:
            raise ValueError("Messages require shared or private visibility")
        if any(not isinstance(call, ToolCall) for call in self.tool_calls):
            raise ValueError("Invalid Tool call")
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        object.__setattr__(
            self, "reasoning", tuple(freeze(item) for item in self.reasoning)
        )
        object.__setattr__(self, "evidence", freeze(self.evidence))


@dataclass
class Episode:
    """An inert identity until open(); accepted generation seals exactly once."""

    _id: str = field(default_factory=lambda: uuid4().hex, init=False)
    _path: Path | None = field(default=None, init=False)
    _verification_path: Path | None = field(default=None, init=False)
    _messages: list[Message] = field(default_factory=list, init=False)
    _events: list[Mapping[str, Any]] = field(default_factory=list, init=False)
    _verification: list[Mapping[str, Any]] = field(default_factory=list, init=False)
    _metadata: Mapping[str, Any] = field(default_factory=dict, init=False)
    _generation: Mapping[str, Any] = field(default_factory=dict, init=False)
    _secrets: set[str] = field(default_factory=set, init=False, repr=False)
    _sealed: bool = field(default=False, init=False)
    _running: bool = field(default=False, init=False)
    _segment: str | None = field(default=None, init=False)
    _storage_error: bool = field(default=False, init=False)

    @property
    def id(self) -> str:
        return self._id

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def messages(self) -> tuple[Message, ...]:
        return tuple(self._messages)

    @property
    def events(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._events)

    @property
    def verification(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._verification)

    @property
    def generation(self) -> Mapping[str, Any]:
        return self._generation

    @property
    def metadata(self) -> Mapping[str, Any]:
        return self._metadata

    @property
    def sealed(self) -> bool:
        return self._sealed

    @property
    def status(self) -> str:
        if (
            self._generation.get("state") in {"failed", "invalid"}
            or self._storage_error
        ):
            return "invalid" if self._generation.get("state") == "invalid" else "failed"
        valid = [item for item in self._verification if item["status"] != "unverified"]
        return str(valid[-1]["status"]) if valid else "unverified"

    def open(self, path: str | Path) -> None:
        if (
            self._path is not None
            or self._sealed
            or self._storage_error
            or self._running
        ):
            raise RuntimeError("Episode cannot be reopened or rebound")
        try:
            destination = output_path(path)
            _new_recording(destination)
        except (OSError, ValueError) as exc:
            self._opening_failure(exc)
            if isinstance(exc, (FileExistsError, ValueError)):
                raise
            raise PersistenceError("Episode opening failed") from exc
        self._path = destination

    def _opening_failure(self, error: BaseException) -> None:
        self._storage_error = True
        self._generation = freeze({"state": "failed", "reason": "persistence"})
        self._events.append(
            freeze(
                {
                    "id": uuid4().hex,
                    "kind": "opening_error",
                    "timestamp": timestamp(),
                    "actor_id": None,
                    "turn_id": None,
                    "step_id": None,
                    "data": {"failure": self.failure(error, "open")},
                }
            )
        )

    def begin(self, metadata: Mapping[str, Any]) -> None:
        self.require_open()
        if self._running:
            raise RuntimeError("Episode is already executing")
        self._running = True
        self._metadata = freeze(self.sanitize(metadata))
        assert self._path is not None
        write_json(self._path / "run-plan.json", self._metadata)
        self.record("generation_started")

    def require_open(self) -> None:
        if self._sealed or self._storage_error or self._path is None:
            raise RuntimeError(
                "Episode requires healthy open recording and unsealed generation"
            )

    def add_secrets(self, *clients: Any) -> None:
        for client in clients:
            secret = getattr(client, "api_key", None)
            if isinstance(secret, str) and secret:
                self._secrets.add(secret)

    def sanitize(self, value: object, *, diagnostic: bool = False) -> Any:
        if is_dataclass(value) and not isinstance(value, type):
            value = json_data(value)
        if isinstance(value, str):
            for secret in sorted(self._secrets, key=len, reverse=True):
                value = value.replace(secret, "[REDACTED]")
            return _diagnostic_text(value) if diagnostic else value
        if isinstance(value, Mapping):
            return {
                self.sanitize(key): "[REDACTED]"
                if _secret_key(key)
                else self.sanitize(item, diagnostic=diagnostic)
                for key, item in value.items()
            }
        if isinstance(value, (tuple, list)):
            return [self.sanitize(item, diagnostic=diagnostic) for item in value]
        return json_data(value)

    def append(self, message: Message) -> Message:
        self.require_open()
        message = _decode_message(self.sanitize(message))
        message = replace(
            message,
            id=message.id or uuid4().hex,
            segment=self._segment,
            timestamp=message.timestamp or timestamp(),
        )
        _validate_append(self.messages, message)
        self._persist("conversation.jsonl", _commit(message))
        self._messages.append(message)
        return message

    def record(
        self,
        kind: str,
        *,
        actor_id: str | None = None,
        turn_id: str | None = None,
        **data: Any,
    ) -> None:
        self.require_open()
        context = {"actor_id": actor_id, "turn_id": turn_id, "step_id": self._segment}
        event = {
            "id": uuid4().hex,
            "kind": kind,
            "timestamp": timestamp(),
            **context,
            "data": self.sanitize(data, diagnostic=True),
        }
        self._events.append(freeze(event))
        self._persist("events.jsonl", event)

    def _persist(self, filename: str, value: object) -> None:
        assert self._path is not None
        try:
            _append_json(output_path(self._path / filename), value)
        except (OSError, ValueError) as exc:
            self._storage_error = True
            raise PersistenceError("Episode ledger persistence failed") from exc

    def activate(self, name: str | None, instructions: Mapping[str, str]) -> None:
        self.require_open()
        self._segment = name
        self.record("segment_activated", name=name, instructions=instructions)

    def history(self, role: str | None = None) -> tuple[Message, ...]:
        return tuple(
            replace(message, reasoning=())
            if role is not None and message.actor_id != role
            else message
            for message in self._messages
            if role is None
            or message.visibility == "shared"
            or message.actor_id == role
        )

    def seal(self, state: str = "terminated", reason: str = "completed") -> None:
        if self._sealed or self._path is None:
            raise RuntimeError("Episode cannot seal unopened or sealed generation")
        if state not in {"terminated", "truncated", "failed", "invalid"}:
            raise ValueError("Unknown generation outcome")
        self._generation = freeze(
            {
                "state": "failed" if self._storage_error else state,
                "reason": "persistence" if self._storage_error else reason,
            }
        )
        self._running = False
        try:
            write_json(self._path / "trace.json", self.to_dict())
        except (OSError, ValueError) as exc:
            self._storage_error = True
            raise PersistenceError("Episode publication failed") from exc
        self._sealed = True

    async def verify(self, judge: "Evaluator") -> Mapping[str, Any]:
        from agentinstruct.judge import Judge, Judgment

        if not self._sealed:
            raise RuntimeError("Verification requires sealed generation")
        if isinstance(judge, Judge):
            self.add_secrets(judge.client)
        try:
            result = await judge.evaluate(self.messages)
            if not isinstance(result, Judgment):
                raise ValueError("Evaluator must return a Judgment")
        except BaseException as exc:
            self._verification_failure(exc)
            raise
        return self._append_verification(_verification_data(result))

    def _verification_failure(self, error: BaseException) -> None:
        data = {
            "status": "unverified",
            "error": self.failure(error, "verifier"),
            "events": getattr(error, "evidence", {}),
        }
        try:
            self._append_verification(data)
        except OSError as storage:
            if isinstance(error, asyncio.CancelledError):
                raise error from storage
            raise

    def _append_verification(self, data: Mapping[str, Any]) -> Mapping[str, Any]:
        assert self._path is not None
        directory = output_path(self._verification_path or self._path / "verification")
        directory.mkdir(exist_ok=True)
        attempt = freeze(
            self.sanitize(
                {
                    "id": uuid4().hex,
                    "trace_id": self.id,
                    "sequence": len(self._verification) + 1,
                    **data,
                },
                diagnostic=True,
            )
        )
        write_json(directory / f"{attempt['id']}.json", attempt)
        _sync_directory(directory.parent)
        self._verification.append(attempt)
        return cast(Mapping[str, Any], attempt)

    def failure(self, error: BaseException, stage: str) -> Mapping[str, Any]:
        return cast(
            Mapping[str, Any],
            freeze(
                self.sanitize(
                    {
                        "stage": stage,
                        "exception": type(error).__name__,
                        "kind": getattr(error, "kind", None),
                        "message": str(error)
                        if type(error).__module__ == "builtins"
                        else f"{type(error).__name__} failed",
                    },
                    diagnostic=True,
                )
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "trace_id": self.id,
            "run_id": self._metadata.get("run_id", self.id),
            "seed_id": self._metadata.get("seed", {}).get("id", self.id),
            "status": self.status,
            "generation": json_data(self._generation),
            "run_plan": json_data(self._metadata),
            "conversation": [_commit(m) for m in self.messages],
            "events": json_data(self.events),
            "verification": json_data(self.verification),
        }

    @classmethod
    def load(cls, path: str | Path) -> "Episode":
        source = Path(path)
        source = source / "trace.json" if source.is_dir() else source
        source = source.resolve(strict=True)
        data = _snapshot_data(source)
        episode = cls()
        episode._id = data["trace_id"]
        episode._path = source.parent
        episode._sealed = True
        episode._metadata, episode._generation = (
            freeze(data["run_plan"]),
            freeze(data["generation"]),
        )
        episode._messages = [_decode_commit(item) for item in data["conversation"]]
        episode._events = [freeze(item) for item in data["events"]]
        episode._verification_path = _verification_directory(source)
        episode._verification = _load_verification(source, data)
        return episode

    def export(self, path: str | Path, *, format: str = "openai") -> None:
        destination = output_path(path)
        if self.path is not None and destination.is_relative_to(self.path):
            raise ValueError("Export cannot overwrite Episode evidence")
        value = (
            self.to_dict()
            if format == "native"
            else {"messages": self.training_messages()}
        )
        if format not in {"native", "openai"}:
            raise ValueError("Unknown export format")
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(canonical_json(value) + "\n")

    def training_messages(self) -> list[dict[str, Any]]:
        agents = self.metadata.get("agents", {})
        target = next(
            (role for role, settings in agents.items() if settings.get("target")),
            "assistant",
        )
        return [
            {
                "role": "assistant" if message.actor_id == target else "user",
                "content": message.content,
            }
            for message in self.messages
            if message.visibility == "shared"
            and message.role != "tool"
            and not message.tool_calls
        ]


def _secret_key(key: str) -> bool:
    return key.lower().replace("-", "_") in {
        "authorization",
        "proxy_authorization",
        "x_api_key",
        "api_key",
        "access_token",
        "password",
        "client_secret",
    }


def _diagnostic_text(text: str) -> str:
    return re.sub(
        r"""(?i)(authorization|api[_-]key|password|access[_-]token)["']?\s*[:=]\s*(?:"[^"\n]*"|'[^'\n]*'|(?:bearer\s+)?[^\s,;}]+)""",
        r'\1: "[REDACTED]"',
        text,
    )


def _decode_message(data: dict[str, Any]) -> Message:
    data = dict(data)
    data["tool_calls"] = tuple(
        ToolCall(call["id"], FunctionCall(**call["function"]))
        for call in data.get("tool_calls", ())
    )
    return Message(
        **{
            key: item
            for key, item in data.items()
            if key in Message.__dataclass_fields__
        }
    )


def _commit(message: Message) -> dict[str, Any]:
    return {
        "message": json_data(message),
        "visibility": message.visibility,
        "step_id": message.segment,
        "turn_id": message.turn_id,
        "timestamp": message.timestamp,
    }


def _decode_commit(commit: Mapping[str, Any]) -> Message:
    return replace(
        _decode_message(commit["message"]),
        visibility=commit.get("visibility", "shared"),
        segment=commit.get("step_id"),
        turn_id=commit.get("turn_id"),
        timestamp=commit.get("timestamp", ""),
    )


def _load_verification(source: Path, data: dict[str, Any]) -> list[Mapping[str, Any]]:
    directory = _verification_directory(source)
    by_id = _verification_index(data)
    for path in directory.glob("*.json"):
        item = parse_json(path.read_text(encoding="utf-8"))
        _check_verification(item, data["trace_id"])
        if item["id"] in by_id and by_id[item["id"]] != item:
            raise ValueError("Conflicting immutable Verification")
        by_id[item["id"]] = item
    result = sorted(by_id.values(), key=lambda item: item["sequence"])
    if len({item["sequence"] for item in result}) != len(result):
        raise ValueError("Duplicate Verification sequence")
    return [freeze(item) for item in result]


def _validate_append(messages: Sequence[Message], message: Message) -> None:
    _participant_message(message)
    if any(item.id == message.id for item in messages):
        raise ValueError("Accepted message ID must be unique")
    calls = {(m.actor_id, call.id) for m in messages for call in m.tool_calls}
    results = {(m.actor_id, m.tool_call_id) for m in messages if m.role == "tool"}
    identity = (message.actor_id, message.tool_call_id)
    if message.role == "tool":
        if identity in results or identity not in calls:
            raise ValueError("Tool result must match an outstanding private call")
    elif calls - results:
        raise ValueError("Finish outstanding Tool exchanges before another message")
    ids = [(message.actor_id, call.id) for call in message.tool_calls]
    if len(ids) != len(set(ids)) or calls.intersection(ids):
        raise ValueError("Tool calls require unique per-Agent identifiers")


def _verification_data(result: Any) -> dict[str, Any]:
    return {
        "status": "accepted" if result.passed else "rejected",
        "criteria": result.criteria,
        "score": result.score,
        "feedback": result.feedback,
        "events": result.evidence,
    }


def _participant_message(message: Message) -> None:
    if message.actor_id not in {"assistant", "user"}:
        raise ValueError("Accepted messages require a participant identity")
    if message.role != "tool" and message.role != message.actor_id:
        raise ValueError("Accepted participant role must match its identity")
    if message.control and (message.actor_id != "assistant" or message.role == "tool"):
        raise ValueError("Only assistant may signal completion")
    if (
        message.role == "tool" or message.tool_calls
    ) and message.visibility != "private":
        raise ValueError("Tool exchanges must remain private")
    if message.tool_calls and message.control:
        raise ValueError("Tool intent cannot also signal completion")


def _verification_directory(source: Path) -> Path:
    return (
        source.parent / "verification"
        if source.name == "trace.json"
        else source.with_name(source.name + ".verification")
    )


def _snapshot_data(source: Path) -> dict[str, Any]:
    from jsonschema import validate
    from jsonschema.exceptions import ValidationError

    data = parse_json(source.read_text(encoding="utf-8"))
    try:
        validate(data, _SAVED_EPISODE_SCHEMA)
    except ValidationError as exc:
        raise ValueError("Invalid saved Episode") from exc
    return cast(dict[str, Any], data)


def _verification_index(data: Mapping[str, Any]) -> dict[str, Any]:
    result = {}
    for item in data.get("verification", []):
        _check_verification(item, data["trace_id"])
        if item["id"] in result:
            raise ValueError("Duplicate immutable Verification ID")
        result[item["id"]] = item
    return result


def _check_verification(item: Mapping[str, Any], identity: str) -> None:
    if not isinstance(item, Mapping):
        raise ValueError("Verification must be an object")
    if item.get("trace_id") != identity or item.get("status") not in {
        "accepted",
        "rejected",
        "unverified",
    }:
        raise ValueError("Verification has foreign identity or invalid status")
    if not isinstance(item.get("id"), str) or not item["id"]:
        raise ValueError("Verification requires an ID")
    if type(item.get("sequence")) is not int or item["sequence"] < 1:
        raise ValueError("Verification requires a positive sequence")
    if not isinstance(item.get("criteria", {}), Mapping) or any(
        type(v) is not bool for v in item.get("criteria", {}).values()
    ):
        raise ValueError("Verification criteria require Boolean verdicts")


_SAVED_EPISODE_SCHEMA = {
    "type": "object",
    "required": [
        "schema_version",
        "trace_id",
        "run_plan",
        "generation",
        "conversation",
        "events",
    ],
    "properties": {
        "schema_version": {"const": "1"},
        "trace_id": {"type": "string", "minLength": 1},
        "run_plan": {"type": "object"},
        "generation": {
            "type": "object",
            "required": ["state", "reason"],
            "properties": {
                "state": {"enum": ["terminated", "truncated", "failed", "invalid"]},
                "reason": {"type": "string"},
            },
        },
        "conversation": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["message"],
                "properties": {
                    "message": {"type": "object", "required": ["role", "content"]}
                },
            },
        },
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["kind"],
                "properties": {"kind": {"type": "string"}, "data": {"type": "object"}},
            },
        },
        "verification": {"type": "array", "items": {"type": "object"}},
    },
}


def _new_recording(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for name in ("conversation.jsonl", "events.jsonl"):
        with (destination / name).open("x", encoding="utf-8") as stream:
            stream.flush()
            os.fsync(stream.fileno())
    _sync_directory(destination)
    _sync_directory(destination.parent)
