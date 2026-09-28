"""Source records retain their data and origin before per-Seed compilation."""

import csv
import json
import math
import os
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from agentinstruct.paths import normalized_name, portable_name, seed_glob, unique_names
from agentinstruct.plans import (
    FrozenJsonValue,
    JsonValue,
    Seed,
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
    seed_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", freeze(json_value(self.data)))
        object.__setattr__(
            self,
            "digest",
            content_digest(self.data if self.error is None else self.raw),
        )


type SeedInput = Seed | Mapping[str, JsonValue | FrozenJsonValue]


def _python_data(value: object) -> JsonValue:
    """Copy only JSON values; never invoke arbitrary repr or serialization hooks."""
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("non-string mapping key")
            result[key] = _python_data(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_python_data(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite number")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise ValueError("unsupported value")


def read_python_records(seeds: Iterable[SeedInput]) -> Iterator[SeedRecord]:
    """Assign a stable position before validating a caller-provided record."""
    try:
        iterator = iter(seeds)
    except Exception as exc:
        raise SeedSourceError(
            f"python:seeds: source iteration failed ({type(exc).__name__})"
        ) from exc
    position = 0
    while True:
        try:
            item = next(iterator)
        except StopIteration:
            return
        except Exception as exc:
            raise SeedSourceError(
                f"python:seeds: source iteration failed ({type(exc).__name__})"
            ) from exc
        position += 1
        origin = SeedOrigin("python:seeds", position, "python")
        seed_id = None
        try:
            if isinstance(item, Seed):
                if (
                    not isinstance(item.origin, SeedOrigin)
                    or not isinstance(item.origin.path, str)
                    or not item.origin.path.strip()
                    or type(item.origin.record) is not int
                    or item.origin.record < 1
                    or item.origin.format not in {"json", "csv", "python"}
                ):
                    raise ValueError("invalid Seed origin")
                origin = item.origin
                if not isinstance(item.id, str) or not item.id.strip():
                    raise ValueError("invalid Seed ID")
                seed_id = item.id
                data = _python_data(item.data)
            else:
                data = _python_data(item)
            yield SeedRecord(origin, freeze(data), seed_id=seed_id)
        except Exception as exc:
            yield SeedRecord(
                origin,
                None,
                f"{origin.path}: record {origin.record}: expected JSON-compatible "
                f"Seed data with a valid identity and origin ({type(exc).__name__})",
                "<invalid Python Seed>",
                seed_id=seed_id,
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


def parse_json(raw: str, label: str) -> JsonValue:
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
        data = parse_json(raw, f"{origin.path}: record {origin.record}")
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
        if path.suffix.lower() == ".csv":
            yield from _csv_records(path, origin)
        elif path.suffix.lower() == ".jsonl":
            with path.open("r", encoding="utf-8") as stream:
                for position, raw in enumerate(stream, 1):
                    if raw.strip():
                        yield _record(raw, SeedOrigin(origin, position))
        else:
            yield from _json_records(path.read_text(encoding="utf-8"), origin)
    except (OSError, UnicodeError) as exc:
        raise SeedSourceError(f"{origin}: cannot read UTF-8 source: {exc}") from exc


def seed_files(path: Path, origin: str, glob: str | None) -> list[tuple[Path, str]]:
    """Preflight every selected path before returning any work for generation."""
    try:
        if not path.is_dir():
            if not path.is_file():
                raise ValueError("expected a regular Seed source file or directory")
            return [(path, origin)]
        if glob is None:
            raise ValueError("directory source requires seed.glob")
        seed_glob(glob)
        found: list[tuple[Path, str]] = []

        def fail(error: OSError) -> None:
            raise error

        for directory, directories, files in os.walk(
            path, onerror=fail, followlinks=False
        ):
            parent = Path(directory)
            unique_names(directories + files, str(parent))
            for name in directories:
                portable_name(name)
                if (parent / name).is_symlink():
                    raise ValueError(
                        f"{name}: symbolic links are not allowed in Seed directories"
                    )
            for name in files:
                item = parent / name
                relative = item.relative_to(path)
                if not relative.full_match(glob, case_sensitive=True):
                    continue
                portable_name(name)
                if item.is_symlink():
                    raise ValueError(
                        f"{name}: symbolic links are not allowed in Seed directories"
                    )
                if not item.is_file():
                    raise ValueError(f"{name}: expected a regular Seed file")
                if item.suffix.lower() not in {".json", ".jsonl", ".csv"}:
                    raise ValueError(f"{name}: unsupported Seed file format")
                found.append(
                    (item, normalized_name((Path(origin) / relative).as_posix()))
                )
        return sorted(found, key=lambda entry: entry[1])
    except (OSError, ValueError, RuntimeError) as exc:
        raise SeedSourceError(f"{origin}: cannot enumerate Seed source: {exc}") from exc


def _csv_records(path: Path, origin: str) -> Iterator[SeedRecord]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        try:
            headers = next(reader, None)
            if headers is None:
                return
            if not headers or any(not header for header in headers):
                raise SeedSourceError(f"{origin}: CSV requires nonempty headers")
            if len(set(headers)) != len(headers):
                raise SeedSourceError(f"{origin}: duplicate CSV header")
            while True:
                # Physical start line remains precise for quoted multiline rows.
                position = reader.line_num + 1
                row = next(reader, None)
                if row is None:
                    return
                if not row:
                    continue
                source = SeedOrigin(origin, position, "csv")
                if len(row) != len(headers):
                    yield SeedRecord(
                        source,
                        None,
                        f"{origin}: record {position}: CSV row has {len(row)} "
                        f"values; expected {len(headers)}",
                        json.dumps(row),
                    )
                else:
                    yield SeedRecord(
                        source, freeze(dict(zip(headers, row, strict=True)))
                    )
        except csv.Error as exc:
            raise SeedSourceError(
                f"{origin}: cannot enumerate CSV at line {reader.line_num}: {exc}"
            ) from exc
