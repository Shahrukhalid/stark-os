"""Model router: picks which free OpenRouter models an agent call should try.

Each agent has a tier (deep / balanced / fast) in agent.toml. The router asks the
OpenRouter pool for that tier's candidate list (pinned model first, models on
cooldown skipped). The kernel tries them in order until one answers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Settings
from ..providers import ModelProvider
from ..providers.openrouter import OpenRouterProvider
from .agent_registry import AgentConfig


class NoModelAvailable(RuntimeError):
    pass


@dataclass
class Route:
    provider: ModelProvider
    model: str  # first choice
    tier: str
    reason: str
    candidates: list[str] = field(default_factory=list)


class ModelRouter:
    def __init__(self, settings: Settings, providers: dict[str, ModelProvider] | None = None) -> None:
        self.settings = settings
        self.providers = providers if providers is not None else {
            "openrouter": OpenRouterProvider(settings.openrouter_api_key, base_url=settings.openrouter_base_url,
                                             app_url=settings.web_origin,
                                             allow_paid=settings.openrouter_allow_paid)}
        if providers is None and settings.ollama_base_url:
            from ..providers.ollama import OllamaProvider
            self.providers["ollama"] = OllamaProvider(settings.ollama_base_url, settings.ollama_model)
        self.pins = {t: m for t, m in (settings.openrouter_models or {}).items() if m}

    @property
    def openrouter(self) -> OpenRouterProvider | None:
        p = self.providers.get("openrouter")
        return p if isinstance(p, OpenRouterProvider) else None

    async def prepare(self) -> None:
        """Load the free-model catalogue (falls back to the verified snapshot when offline)."""
        if self.openrouter and self.openrouter.configured()[0]:
            await self.openrouter.refresh_catalog()

    def configured_providers(self) -> list[str]:
        return [name for name, p in self.providers.items() if p.configured()[0]]

    def select(self, agent: AgentConfig, *, tier_hint: str | None = None) -> Route:
        available = self.configured_providers()
        if not available:
            raise NoModelAvailable("No model is configured. Add OPENROUTER_API_KEY to .env (free key at "
                                   "https://openrouter.ai/keys) and restart the API.")
        tier = tier_hint or agent.model.tier
        requested = agent.model.provider or (self.settings.default_provider if self.settings.default_provider != "openrouter" else None)
        if requested and requested not in available:
            raise NoModelAvailable("The agent's selected provider is unavailable. Configure it or explicitly "
                                   "change the agent provider; no cross-provider fallback was attempted.")
        name = requested or available[0]
        provider = self.providers[name]
        pinned = agent.model.model or (self.pins.get(tier) if name == "openrouter" else None)
        if isinstance(provider, OpenRouterProvider):
            candidates = provider.candidates(tier, pinned, preferred=agent.model.preferred)
        elif name == "ollama":
            model = pinned or provider.default_model
            if not model:
                raise NoModelAvailable("Choose a local model with STARK_OLLAMA_MODEL or the agent model setting")
            candidates = [model]
        else:  # test doubles / future providers
            candidates = [pinned or f"{provider.name}-{tier}"]
        if not candidates:
            raise NoModelAvailable("No eligible models are available for the selected provider.")
        reason = (f"provider={name}, tier={tier}" + (f", pinned {pinned}" if pinned else "")
                  + (f", own brain {agent.model.preferred[0]}" if agent.model.preferred else "")
                  + f", {len(candidates)} candidates")
        return Route(provider, candidates[0], tier, reason, candidates)
