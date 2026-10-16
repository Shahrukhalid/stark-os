"""Test fixtures.

``ScriptedProvider`` is a TEST-ONLY stand-in for a language model: it returns
pre-scripted responses so orchestration, permissions and tools can be tested
deterministically without network access or API keys. It is not shipped in
the application package and is never used at runtime.
"""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path
from typing import Any, Callable

import pytest

from stark.config import REPO_ROOT, Settings
from stark.core.runtime import Kernel
from stark.main import build_kernel
from stark.providers.base import ModelProvider, ModelRequest, ModelResponse, ProviderError

AGENT_MARKERS = {
    "You are J.A.R.V.I.S.": "jarvis",
    "You are F.R.I.D.A.Y.": "friday",
    "You are E.D.I.T.H.": "edith",
    "You are ULTRON": "ultron",
    "You are JOCASTA": "jocasta",
    "You are D.U.M.-E.": "dum_e",
    "You are U,": "u",
}
_ids = itertools.count(1)


def agent_of(request: ModelRequest) -> str:
    for marker, agent in AGENT_MARKERS.items():
        if request.system.startswith(marker):
            return agent
    return "unknown"


def text(t: str) -> dict[str, Any]:
    return {"type": "text", "text": t}


def tool(name: str, inp: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": name.replace(".", "__"), "input": inp}


def last_tool_results(request: ModelRequest) -> list[dict[str, Any]]:
    last = request.messages[-1]
    if isinstance(last["content"], list):
        return [b for b in last["content"] if b.get("type") == "tool_result"]
    return []


def n_tool_rounds(request: ModelRequest) -> int:
    return sum(1 for m in request.messages if m["role"] == "assistant" and isinstance(m["content"], list))


class ScriptedProvider(ModelProvider):
    """Calls ``brain(agent_id, request)``; brain returns a list of content blocks or raises ProviderError."""

    def __init__(self, brain: Callable[[str, ModelRequest], list[dict[str, Any]]], name: str = "openrouter",
                 delay: float = 0.0) -> None:
        self.name = name
        self.brain = brain
        self.delay = delay
        self.requests: list[tuple[str, ModelRequest]] = []

    def configured(self) -> tuple[bool, str]:
        return True, "scripted (tests)"

    async def complete(self, request: ModelRequest) -> ModelResponse:
        agent = agent_of(request)
        self.requests.append((agent, request))
        if self.delay:
            await asyncio.sleep(self.delay)
        blocks = self.brain(agent, request)
        stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
        return ModelResponse(content=blocks, stop_reason=stop, input_tokens=100, output_tokens=50,
                             model=request.model, provider=self.name)


class Unconfigured(ModelProvider):
    def __init__(self, name: str) -> None:
        self.name = name

    def configured(self):
        return False, "not configured (tests)"

    async def complete(self, request):  # pragma: no cover
        raise ProviderError("not configured")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def settings(tmp_path: Path, workspace: Path) -> Settings:
    s = Settings.from_env()
    s.api_token = "test-token-0123456789abcdefghij"
    s.database_url = f"sqlite:///{tmp_path / 'test.db'}"
    s.data_dir = tmp_path / "data"
    s.workspace_roots = [workspace.resolve()]
    s.agents_dir = REPO_ROOT / "agents"
    s.openrouter_api_key = ""
    s.openrouter_models = {}
    s.tavily_api_key = ""
    s.brave_api_key = ""
    s.bluesky_handle = ""
    s.bluesky_app_password = ""
    s.mastodon_base_url = ""
    s.mastodon_access_token = ""
    s.brand_blocked_terms = []
    s.allow_private_fetch = False
    s.approval_timeout_s = 5
    s.memory_enabled = True
    s.default_mode = "assist"
    return s


def make_kernel(settings: Settings, brain=None, delay: float = 0.0) -> tuple[Kernel, ScriptedProvider | None]:
    provider = ScriptedProvider(brain, delay=delay) if brain else None
    providers: dict[str, ModelProvider] = {"openrouter": provider or Unconfigured("openrouter")}
    return build_kernel(settings, providers), provider


async def wait_for(predicate: Callable[[], Any], timeout: float = 5.0, interval: float = 0.02) -> Any:
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(interval)
