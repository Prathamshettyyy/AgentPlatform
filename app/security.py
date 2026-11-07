from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass
from typing import Any


SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "authorization",
    "credential",
    "private_key",
)
_KEY_VALUE_PATTERN = re.compile(
    r"(?i)(\b(?:password|secret|token|api[_-]?key|authorization|credential)\b\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[^\s,;]+")


def is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def redact_text(value: str) -> str:
    value = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
    return _KEY_VALUE_PATTERN.sub(r"\1[REDACTED]", value)


def redact_sensitive(value: Any) -> Any:
    """Return a JSON-compatible copy with credential-like data removed."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if is_sensitive_key(key) else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


@dataclass(frozen=True)
class Principal:
    user_id: str
    permissions: frozenset[str]
    development: bool = False

    def can(self, permission: str) -> bool:
        return self.development or permission in self.permissions or "*" in self.permissions


@dataclass(frozen=True)
class _TokenRecord:
    token: str
    permissions: frozenset[str]


class AuthenticationError(ValueError):
    pass


class AuthorizationError(PermissionError):
    pass


class AuthConfig:
    """Small bearer-token boundary for the local API.

    Development bypass is accepted only when the caller explicitly selects
    ``development`` and sets ``AGENT_PLATFORM_DEV_MODE=1``. The production
    default is fail-closed token authentication.
    """

    def __init__(self, mode: str, tokens: dict[str, _TokenRecord]):
        if mode not in {"required", "development"}:
            raise ValueError("AGENT_PLATFORM_AUTH_MODE must be 'required' or 'development'")
        if mode == "development" and os.getenv("AGENT_PLATFORM_DEV_MODE") != "1":
            raise ValueError("development authentication requires AGENT_PLATFORM_DEV_MODE=1")
        if mode == "required" and not tokens:
            raise ValueError("token authentication is required; configure AGENT_PLATFORM_API_TOKEN or AGENT_PLATFORM_AUTH_TOKENS")
        self.mode = mode
        self.tokens = tokens

    @classmethod
    def from_values(
        cls,
        mode: str | None = None,
        tokens: dict[str, str | dict[str, Any]] | None = None,
    ) -> "AuthConfig":
        selected_mode = mode or os.getenv("AGENT_PLATFORM_AUTH_MODE", "required")
        raw_tokens: dict[str, str | dict[str, Any]] = dict(tokens or {})
        if not raw_tokens:
            configured = os.getenv("AGENT_PLATFORM_AUTH_TOKENS")
            if configured:
                try:
                    parsed = json.loads(configured)
                except json.JSONDecodeError as exc:
                    raise ValueError("AGENT_PLATFORM_AUTH_TOKENS must be valid JSON") from exc
                if not isinstance(parsed, dict):
                    raise ValueError("AGENT_PLATFORM_AUTH_TOKENS must be a JSON object")
                raw_tokens = parsed
            elif os.getenv("AGENT_PLATFORM_API_TOKEN"):
                raw_tokens = {"default": os.environ["AGENT_PLATFORM_API_TOKEN"]}
        records: dict[str, _TokenRecord] = {}
        for user_id, value in raw_tokens.items():
            if isinstance(value, str):
                token, permissions = value, frozenset({"*"})
            elif isinstance(value, dict) and isinstance(value.get("token"), str):
                token = value["token"]
                permissions = frozenset(str(item) for item in value.get("permissions", []))
            else:
                raise ValueError(f"invalid token record for user: {user_id}")
            if not token:
                raise ValueError(f"empty token for user: {user_id}")
            records[str(user_id)] = _TokenRecord(token, permissions)
        return cls(selected_mode, records)

    def authenticate(self, authorization: str | None) -> Principal:
        if self.mode == "development":
            return Principal("development", frozenset({"*"}), development=True)
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthenticationError("authentication required")
        supplied = authorization[7:].strip()
        for user_id, record in self.tokens.items():
            if secrets.compare_digest(supplied, record.token):
                return Principal(user_id, record.permissions)
        raise AuthenticationError("invalid credentials")

    @staticmethod
    def require(principal: Principal, permission: str) -> None:
        if not principal.can(permission):
            raise AuthorizationError("insufficient permissions")
