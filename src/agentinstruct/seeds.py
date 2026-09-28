"""Source records retain their data and origin before per-Seed compilation."""

import json
import math
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from agentinstruct.plans import (
    FrozenJsonValue,
    JsonValue,
    SeedOrigin,
    content_digest,
    freeze,
    json_value,
)


class SeedSourceError(ValueError):
    """The source cannot reliably enumerate further records."""


@dataclass(frozen=True)
class SeedRecord:
    origin: SeedOrigin
    data: FrozenJsonValue
    error: str | None = None
    raw: str | None = None
    digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", freeze(json_value(self.data)))
        object.__setattr__(
            self,
            "digest",
            content_digest(self.data if self.error is None else self.raw),
        )


def _json_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _json_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite numbers are not valid JSON Seed data")
    return result


def _parse(raw: str, label: str) -> JsonValue:
    try:
        return cast(
            JsonValue,
            json.loads(
                raw,
                object_pairs_hook=_json_object,
                parse_float=_json_float,
                parse_constant=_json_float,
            ),
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{label}: malformed JSON at line {exc.lineno}, column {exc.colno}"
        ) from exc
    except ValueError as exc:
        raise ValueError(f"{label}: {exc}") from exc


def _record(raw: str, origin: SeedOrigin) -> SeedRecord:
    try:
        data = _parse(raw, f"{origin.path}: record {origin.record}")
        return SeedRecord(origin, freeze(data))
    except ValueError as exc:
        return SeedRecord(origin, None, str(exc), raw)
    except RecursionError:
        return SeedRecord(
            origin,
            None,
            f"{origin.path}: record {origin.record}: "
            "JSON nesting exceeds the parser limit",
            raw,
        )


def _json_records(raw: str, origin: str) -> Iterator[SeedRecord]:
    # The decoder establishes array-element boundaries, then strict per-record
    # parsing rejects duplicate keys and non-finite values at their stable origin.
    decoder = json.JSONDecoder()
    position = len(raw) - len(raw.lstrip(" \t\r\n"))
    array = raw[position : position + 1] == "["
    if array:
        position += 1
    record = 1
    try:
        while True:
            while position < len(raw) and raw[position] in " \t\r\n":
                position += 1
            if array and record == 1 and raw[position : position + 1] == "]":
                position += 1
                break
            _, end = decoder.raw_decode(raw, position)
            item = raw[position:end]
            position = end
            while position < len(raw) and raw[position] in " \t\r\n":
                position += 1
            if not array:
                if raw[position:].strip(" \t\r\n"):
                    raise json.JSONDecodeError("Extra data", raw, position)
                yield _record(item, SeedOrigin(origin, record))
                return
            delimiter = raw[position : position + 1]
            if delimiter not in {",", "]"}:
                raise json.JSONDecodeError("Expected ',' or ']'", raw, position)
            yield _record(item, SeedOrigin(origin, record))
            position += 1
            record += 1
            if delimiter == "]":
                break
        if raw[position:].strip(" \t\r\n"):
            raise json.JSONDecodeError("Extra data", raw, position)
    except json.JSONDecodeError as exc:
        raise SeedSourceError(
            f"{origin}: malformed JSON at line {exc.lineno}, "
            f"column {exc.colno}: {exc.msg}"
        ) from exc
    except (ValueError, RecursionError) as exc:
        raise SeedSourceError(f"{origin}: cannot enumerate JSON source: {exc}") from exc


def read_seed_records(path: Path, origin: str) -> Iterator[SeedRecord]:
    """Yield records in source order; enumeration failures have no invented Seed."""
    try:
        if path.suffix.lower() == ".jsonl":
            with path.open("r", encoding="utf-8") as stream:
                for position, raw in enumerate(stream, 1):
                    if raw.strip():
                        yield _record(raw, SeedOrigin(origin, position))
        else:
            yield from _json_records(path.read_text(encoding="utf-8"), origin)
    except (OSError, UnicodeError) as exc:
        raise SeedSourceError(f"{origin}: cannot read UTF-8 source: {exc}") from exc
