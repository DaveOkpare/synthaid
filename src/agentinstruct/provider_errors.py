"""Safe classified inference and structured-output failures."""

from typing import Literal

from agentinstruct.traces import immutable_data

type ProviderErrorKind = Literal[
    "authentication",
    "authorization",
    "rate_limit",
    "timeout",
    "network",
    "invalid_request",
    "unsupported_feature",
    "model_unavailable",
    "server",
    "malformed_response",
    "unknown",
    "refusal",
    "incomplete",
    "invalid_json",
    "schema_mismatch",
    "unsupported_schema",
]


class ProviderError(Exception):
    """A classified failure containing only framework-approved diagnostic data."""

    def __init__(
        self,
        kind: ProviderErrorKind,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
        code: str | None = None,
    ) -> None:
        self.kind = kind
        self.metadata = immutable_data(
            {
                "status_code": status_code,
                "request_id": request_id,
                "code": code,
            }
        )
        super().__init__(f"Provider failure: {kind}")


class StructuredOutputValidationError(ProviderError):
    """A structured contract could not be compiled or satisfied locally."""
