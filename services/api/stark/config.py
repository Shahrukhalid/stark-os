"""Environment-based configuration. No secrets are ever hardcoded.

Every setting is read from environment variables (optionally loaded from a
``.env`` file by ``stark.main``). Secrets are held as plain strings in memory
only and are never logged, returned by the API, or written to the database.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


# STARK OS runs exclusively on free OpenRouter models. Model choice is automatic
# (see providers/openrouter.py); OPENROUTER_MODEL / OPENROUTER_MODEL_<TIER> pin one.


@dataclass
class Settings:
    api_token: str = ""
    host: str = "127.0.0.1"
    port: int = 8000
    web_origin: str = "http://localhost:3000"
    database_url: str = ""
    agents_dir: Path = REPO_ROOT / "agents"
    workspace_roots: list[Path] = field(default_factory=list)
    data_dir: Path = REPO_ROOT / "data"

    # model provider: OpenRouter free models only
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_models: dict[str, str] = field(default_factory=dict)
    openrouter_allow_paid: bool = False  # safety net: never call a model that costs money

    # budgets & limits
    task_token_budget: int = 200_000
    max_delegation_depth: int = 2
    max_children_per_task: int = 8
    approval_timeout_s: int = 480  # below every agent's task timeout (600 s+), so approvals never die silently
    default_mode: str = "assist"

    # memory
    memory_enabled: bool = True
    episodic_memory: bool = True
    episodic_ttl_days: int = 30

    # integrations
    tavily_api_key: str = ""
    brave_api_key: str = ""
    # social platforms (free APIs). Anything not configured runs as a labelled SIMULATION.
    bluesky_handle: str = ""
    bluesky_app_password: str = ""  # an app password (Settings -> App passwords), never the main password
    bluesky_service: str = "https://bsky.social"
    mastodon_base_url: str = ""
    mastodon_access_token: str = ""
    brand_blocked_terms: list[str] = field(default_factory=list)
    allow_private_fetch: bool = False  # tests only; never enable in production

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(_env("STARK_DATA_DIR", str(REPO_ROOT / "data"))).expanduser()
        roots = _env_list("STARK_WORKSPACE_ROOTS", [str(REPO_ROOT / "sandbox")])
        return cls(
            api_token=_env("STARK_API_TOKEN"),
            host=_env("STARK_HOST", "127.0.0.1"),
            port=_env_int("STARK_PORT", 8000),
            web_origin=_env("STARK_WEB_ORIGIN", "http://localhost:3000"),
            database_url=_env("DATABASE_URL", f"sqlite:///{data_dir / 'stark.db'}"),
            agents_dir=Path(_env("STARK_AGENTS_DIR", str(REPO_ROOT / "agents"))),
            workspace_roots=[Path(r).expanduser().resolve() for r in roots],
            data_dir=data_dir,
            openrouter_api_key=_env("OPENROUTER_API_KEY"),
            openrouter_base_url=_env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            openrouter_models={
                tier: _env(f"OPENROUTER_MODEL_{tier.upper()}", _env("OPENROUTER_MODEL"))
                for tier in ("deep", "balanced", "fast")
            },
            openrouter_allow_paid=_env_bool("OPENROUTER_ALLOW_PAID", False),
            task_token_budget=_env_int("STARK_TASK_TOKEN_BUDGET", 200_000),
            max_delegation_depth=_env_int("STARK_MAX_DELEGATION_DEPTH", 2),
            approval_timeout_s=_env_int("STARK_APPROVAL_TIMEOUT_S", 480),
            default_mode=_env("STARK_DEFAULT_MODE", "assist"),
            memory_enabled=_env_bool("STARK_MEMORY_ENABLED", True),
            episodic_memory=_env_bool("STARK_EPISODIC_MEMORY", True),
            episodic_ttl_days=_env_int("STARK_EPISODIC_TTL_DAYS", 30),
            tavily_api_key=_env("TAVILY_API_KEY"),
            brave_api_key=_env("BRAVE_API_KEY"),
            bluesky_handle=_env("BLUESKY_HANDLE"),
            bluesky_app_password=_env("BLUESKY_APP_PASSWORD"),
            bluesky_service=_env("BLUESKY_SERVICE", "https://bsky.social"),
            mastodon_base_url=_env("MASTODON_BASE_URL"),
            mastodon_access_token=_env("MASTODON_ACCESS_TOKEN"),
            brand_blocked_terms=_env_list("STARK_BRAND_BLOCKED_TERMS", []),
            allow_private_fetch=_env_bool("STARK_ALLOW_PRIVATE_FETCH", False),
        )


def load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines). Existing env vars win."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)
