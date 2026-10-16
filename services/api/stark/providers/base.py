"""Provider-agnostic model interface.

Internally, conversations use content blocks
(``text`` / ``tool_use`` / ``tool_result``). Each adapter converts to and
from its own wire format.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@dataclass
class ModelRequest:
    model: str
    system: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    max_tokens: int = 2048
    temperature: float = 0.5


@dataclass
class ModelResponse:
    content: list[dict[str, Any]]
    stop_reason: str  # end_turn | tool_use | max_tokens
    input_tokens: int
    output_tokens: int
    model: str
    provider: str

    @property
    def text(self) -> str:
        return "\n".join(b["text"] for b in self.content if b.get("type") == "text").strip()

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b.get("type") == "tool_use"]


RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


class ModelProvider(ABC):
    name: str

    @abstractmethod
    def configured(self) -> tuple[bool, str]:
        """Cheap check: are credentials/URLs present? (no network)"""

    async def health(self) -> tuple[bool, str]:
        """Optional live check; defaults to configured()."""
        return self.configured()

    @abstractmethod
    async def complete(self, request: ModelRequest) -> ModelResponse: ...

    async def list_models(self) -> list[str]:
        return []
