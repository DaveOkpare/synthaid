"""Shared lifecycle cleanup and safe failure evidence."""

import asyncio
import os
import re
from collections.abc import Coroutine, Iterable

from pydantic import ValidationError

from agentinstruct.plans import JsonValue, ProviderPlan, json_value


class SafeDiagnostics:
    """Runtime-only redaction of configured credentials and authentication fields."""

    def __init__(self, providers: Iterable[ProviderPlan] = ()) -> None:
        self._secrets = tuple(
            sorted(
                {
                    value
                    for plan in providers
                    if (
                        name := plan.api_key_env
                        or ("OPENAI_API_KEY" if plan.type == "openai" else None)
                    )
                    and (value := os.environ.get(name))
                },
                key=len,
                reverse=True,
            )
        )

    def text(self, value: str) -> str:
        for secret in self._secrets:
            value = value.replace(secret, "[REDACTED]")
        return value

    def diagnostic_text(self, value: str) -> str:
        value = self.text(value)
        return re.sub(
            r"""(?i)(?<![\w-])(["']?)(authorization|proxy-authorization|x-api-key|api[_-]key|access[_-]token|password)\1\s*[:=]\s*"""
            r"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|(?:(?:bearer|basic)\s+)?[^\s,;}\]]+)""",
            r'\1\2\1: "[REDACTED]"',
            value,
        )

    def data(self, value: object, *, diagnostic: bool = False) -> JsonValue:
        def scrub(item: JsonValue) -> JsonValue:
            if isinstance(item, str):
                return self.diagnostic_text(item) if diagnostic else self.text(item)
            if isinstance(item, list):
                return [scrub(child) for child in item]
            if isinstance(item, dict):
                return {
                    self.text(key): "[REDACTED]"
                    if diagnostic
                    and key.lower().replace("-", "_")
                    in {
                        "authorization",
                        "proxy_authorization",
                        "x_api_key",
                        "api_key",
                        "access_token",
                        "password",
                        "client_secret",
                    }
                    else scrub(child)
                    for key, child in item.items()
                }
            return item

        return scrub(json_value(value))

    def failure(
        self, exc: BaseException, stage: str, **details: object
    ) -> dict[str, JsonValue]:
        def identity(error: BaseException) -> dict[str, JsonValue]:
            try:
                message = (
                    f"Invalid data ({error.error_count()} validation errors)"
                    if isinstance(error, ValidationError)
                    else str(error)
                )
            except Exception:
                message = "Exception message unavailable"
            return {
                "exception": type(error).__name__,
                "message": self.diagnostic_text(message),
            }

        causes: list[JsonValue] = []
        seen = {id(exc)}
        current = exc
        while len(causes) < 8:
            cause = current.__cause__ or (
                None if current.__suppress_context__ else current.__context__
            )
            if cause is None or id(cause) in seen:
                break
            seen.add(id(cause))
            causes.append(identity(cause))
            current = cause
        cause_type = getattr(exc, "cause_type", None)
        if cause_type is not None and not causes:
            causes.append({"exception": str(cause_type)})
        return {
            "stage": stage,
            **identity(exc),
            "causes": causes,
            **{
                key: self.data(value, diagnostic=True) for key, value in details.items()
            },
        }


async def complete_cleanup(operation: Coroutine[object, object, None]) -> bool:
    """Finish bounded cleanup even if its owner receives another cancellation."""
    task = asyncio.create_task(operation)
    interrupted = False
    while True:
        try:
            await asyncio.shield(task)
            return interrupted
        except asyncio.CancelledError:
            interrupted = True
            if task.done():
                if not task.cancelled():
                    task.result()
                return interrupted
