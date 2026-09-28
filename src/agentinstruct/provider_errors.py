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


# Only documented codes may enter native diagnostics. Error messages and unknown
# codes remain untrusted even when the provider returned a successful HTTP status.
_KNOWN_ERROR_CODES: dict[str, ProviderErrorKind] = {
    "server_error": "server",
    "rate_limit_exceeded": "rate_limit",
    "invalid_prompt": "invalid_request",
    "data_residency_mismatch": "invalid_request",
    "bio_policy": "refusal",
    "misalignment_policy_violation": "refusal",
    "vector_store_timeout": "timeout",
    "invalid_image": "invalid_request",
    "invalid_image_format": "invalid_request",
    "invalid_base64_image": "invalid_request",
    "invalid_image_url": "invalid_request",
    "image_too_large": "invalid_request",
    "image_too_small": "invalid_request",
    "image_parse_error": "invalid_request",
    "image_content_policy_violation": "refusal",
    "invalid_image_mode": "invalid_request",
    "image_file_too_large": "invalid_request",
    "unsupported_image_media_type": "invalid_request",
    "empty_image_file": "invalid_request",
    "failed_to_download_image": "invalid_request",
    "image_file_not_found": "invalid_request",
    "model_not_found": "model_unavailable",
    "unsupported_parameter": "unsupported_feature",
    "unsupported_value": "unsupported_feature",
    "unsupported_feature": "unsupported_feature",
}


def classify_provider_error(
    code: object,
    *,
    status_code: int | None = None,
    request_id: str | None = None,
    default_kind: ProviderErrorKind = "unknown",
) -> ProviderError:
    """Normalize safe error codes from HTTP failures or Responses error objects."""
    safe_code = code if isinstance(code, str) and code in _KNOWN_ERROR_CODES else None
    kind: ProviderErrorKind
    if status_code == 401:
        kind = "authentication"
    elif status_code == 403:
        kind = "authorization"
    elif status_code == 429:
        kind = "rate_limit"
    elif status_code in {408, 504}:
        kind = "timeout"
    elif safe_code is not None:
        kind = _KNOWN_ERROR_CODES[safe_code]
    elif status_code is not None and 400 <= status_code < 500:
        kind = "invalid_request"
    elif status_code is not None and status_code >= 500:
        kind = "server"
    else:
        kind = default_kind
    return ProviderError(
        kind, status_code=status_code, request_id=request_id, code=safe_code
    )
