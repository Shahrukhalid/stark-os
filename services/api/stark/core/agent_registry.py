"""Agent registry: loads and validates each agent's configuration.

Each agent lives in ``agents/<id>/`` with ``agent.toml`` (identity, model,
tools, memory rules, voice, limits) and ``system_prompt.md`` (instructions).
Each agent has its own "brain": its own first-choice free models, prompt,
temperature, tools, permissions, private memory and workflow. They are
separate software agents, not conscious minds.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Workflow = Literal["orchestrate", "community", "engagement", "adversarial", "research", "publishing", "visual"]


class ModelConfig(BaseModel):
    tier: Literal["deep", "balanced", "fast"] = "balanced"
    provider: str | None = None  # pin a provider; otherwise router picks
    model: str | None = None  # pin a model id; otherwise tier mapping
    # The agent's own "brain": free models it tries first, in order, before the shared tier list.
    preferred: list[str] = Field(default_factory=list)
    temperature: float = 0.5
    max_output_tokens: int = 2048


class LimitsConfig(BaseModel):
    max_steps: int = 8
    timeout_s: int = 180
    max_retries: int = 2
    max_tokens_per_task: int = 60_000


class MemoryRules(BaseModel):
    read_namespaces: list[str] = Field(default_factory=list)
    write_namespaces: list[str] = Field(default_factory=list)


class DelegationRules(BaseModel):
    can_delegate_to: list[str] = Field(default_factory=list)
    review_focus: str = ""


class VoiceProfile(BaseModel):
    lang: str = "en-US"
    pitch: float = 1.0
    rate: float = 1.0
    preferred_voices: list[str] = Field(default_factory=list)
    muted: bool = False  # never spoken aloud (U. is mute)
    description: str = ""


class AgentConfig(BaseModel):
    id: str
    name: str
    order: int = 100
    full_name: str = ""
    role: str
    color: str = "#22d3ee"
    icon: str = "circle"
    personality: list[str] = Field(default_factory=list)
    communication_style: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    boundaries: list[str] = Field(default_factory=list)
    workflow: Workflow
    permission_level: Literal["observe", "assist", "execute_approved"] = "assist"
    tools: list[str] = Field(default_factory=list)
    model: ModelConfig = Field(default_factory=ModelConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    memory: MemoryRules = Field(default_factory=MemoryRules)
    delegation: DelegationRules = Field(default_factory=DelegationRules)
    voice: VoiceProfile = Field(default_factory=VoiceProfile)
    canon_notes: list[str] = Field(default_factory=list)
    system_prompt: str = ""

    @field_validator("id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not v.replace("_", "").isalnum() or not v.islower():
            raise ValueError("agent id must be lowercase alphanumeric/underscore")
        return v

    @property
    def private_namespace(self) -> str:
        return f"agent:{self.id}"


class RegistryError(ValueError):
    pass


class AgentRegistry:
    def __init__(self, agents: dict[str, AgentConfig]) -> None:
        self._agents = agents

    @classmethod
    def load(cls, directory: Path, known_tools: set[str] | None = None) -> "AgentRegistry":
        agents: dict[str, AgentConfig] = {}
        if not directory.is_dir():
            raise RegistryError(f"agents directory not found: {directory}")
        for agent_dir in sorted(p for p in directory.iterdir() if p.is_dir()):
            cfg_path = agent_dir / "agent.toml"
            if not cfg_path.is_file():
                continue
            with cfg_path.open("rb") as fh:
                data = tomllib.load(fh)
            prompt_path = agent_dir / "system_prompt.md"
            data["system_prompt"] = prompt_path.read_text() if prompt_path.is_file() else ""
            try:
                cfg = AgentConfig.model_validate(data)
            except Exception as exc:  # pydantic ValidationError
                raise RegistryError(f"{cfg_path}: {exc}") from exc
            if not cfg.system_prompt.strip():
                raise RegistryError(f"{agent_dir.name}: system_prompt.md is missing or empty")
            if cfg.id in agents:
                raise RegistryError(f"duplicate agent id {cfg.id}")
            if known_tools is not None:
                unknown = set(cfg.tools) - known_tools
                if unknown:
                    raise RegistryError(f"{cfg.id}: unknown tools {sorted(unknown)}")
            agents[cfg.id] = cfg
        for cfg in agents.values():
            bad = set(cfg.delegation.can_delegate_to) - agents.keys()
            if bad:
                raise RegistryError(f"{cfg.id}: can_delegate_to unknown agents {sorted(bad)}")
            if cfg.private_namespace not in cfg.memory.read_namespaces:
                cfg.memory.read_namespaces.append(cfg.private_namespace)
            if cfg.private_namespace not in cfg.memory.write_namespaces:
                cfg.memory.write_namespaces.append(cfg.private_namespace)
        if not agents:
            raise RegistryError(f"no agents found in {directory}")
        return cls(dict(sorted(agents.items(), key=lambda kv: (kv[1].order, kv[0]))))

    def get(self, agent_id: str) -> AgentConfig:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(f"unknown agent '{agent_id}'") from exc

    def all(self) -> list[AgentConfig]:
        return list(self._agents.values())

    def ids(self) -> list[str]:
        return list(self._agents)

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._agents
