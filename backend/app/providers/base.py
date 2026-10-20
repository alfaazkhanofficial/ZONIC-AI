"""Provider-independent contracts. Wire formats stay inside each adapter."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol


class ProviderErrorCode(str, Enum):
    NOT_CONFIGURED = "not_configured"
    INVALID_CREDENTIALS = "invalid_credentials"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    NETWORK = "network"
    UNSUPPORTED_MODEL = "unsupported_model"
    PROVIDER_OUTAGE = "provider_outage"
    BAD_REQUEST = "bad_request"
    INVALID_RESPONSE = "invalid_response"
    CANCELLED = "cancelled"


class ProviderError(Exception):
    def __init__(self, code: ProviderErrorCode, message: str, *, retryable: bool = False, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.code, self.message, self.retryable, self.status, self.retry_after = code, message, retryable, status, retry_after


HINTS = {
    ProviderErrorCode.NOT_CONFIGURED: "Add your NVIDIA API key in Settings → Model.",
    ProviderErrorCode.INVALID_CREDENTIALS: "The key was rejected. Re-create it at build.nvidia.com and save it again.",
    ProviderErrorCode.RATE_LIMITED: "Rate limit reached. Wait a moment and retry.",
    ProviderErrorCode.TIMEOUT: "The provider did not answer in time. Retry, or raise the timeout in Settings.",
    ProviderErrorCode.NETWORK: "Could not reach the provider. Check your internet connection or proxy.",
    ProviderErrorCode.UNSUPPORTED_MODEL: "The model ID was not found at this endpoint. Check Settings → Model.",
    ProviderErrorCode.PROVIDER_OUTAGE: "The provider is having trouble. Retry shortly.",
    ProviderErrorCode.BAD_REQUEST: "The provider rejected the request. See the message for details.",
    ProviderErrorCode.INVALID_RESPONSE: "The provider returned an unexpected response.",
    ProviderErrorCode.CANCELLED: "Cancelled.",
}


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON text exactly as produced by the model


@dataclass
class ChatMessage:
    role: str  # system | user | assistant | tool
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass
class ChatResult:
    content: str
    tool_calls: list[ToolCall]
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


@dataclass
class ConnectionTest:
    ok: bool
    code: str
    message: str
    latency_ms: int | None = None
    model: str | None = None
    hint: str | None = None


DeltaCallback = Callable[[str], None]


class ModelProvider(Protocol):
    def configured(self) -> bool: ...
    def describe(self) -> dict[str, Any]: ...
    async def chat(self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None, *, cancel: asyncio.Event | None = None,
                   on_delta: DeltaCallback | None = None, max_tokens: int | None = None) -> ChatResult: ...
    async def test_connection(self) -> ConnectionTest: ...

