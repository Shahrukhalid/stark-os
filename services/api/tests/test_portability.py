"""Portability and hardening regressions found in the October 2026 audit."""

from __future__ import annotations

def test_version_control_dirs_are_protected_in_any_case(tmp_path):
    """macOS and Windows file systems ignore case: .GIT/hooks is the real .git/hooks there."""
    from stark.tools.filesystem import is_protected

    for parts in [(".git", "hooks", "pre-commit"), (".GIT", "hooks", "pre-commit"), ("repo", ".Git", "config"),
                  (".SVN", "entries")]:
        assert is_protected(tmp_path.joinpath(*parts)), parts
    assert not is_protected(tmp_path / "gitlab-notes.md")

def test_dotenv_and_prompts_are_read_as_utf8(tmp_path, monkeypatch):
    """Windows defaults to a legacy code page: a .env saved by Notepad (UTF-8 with BOM) or a prompt with
    non-ASCII characters must still load the same everywhere. (CI runs this file on Windows too.)"""
    import os

    from stark.config import load_dotenv
    from stark.core.agent_registry import AgentRegistry

    env = tmp_path / ".env"
    env.write_bytes("﻿STARK_TEST_BOM_KEY=café\n".encode("utf-8"))
    monkeypatch.delenv("STARK_TEST_BOM_KEY", raising=False)
    load_dotenv(env)
    assert os.environ.get("STARK_TEST_BOM_KEY") == "café"

    import shutil
    from pathlib import Path

    agents = tmp_path / "agents"
    shutil.copytree(Path(__file__).resolve().parents[3] / "agents", agents)
    prompt = agents / "edith" / "system_prompt.md"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "\nUse “smart quotes” — and ✨.\n",
                      encoding="utf-8")
    registry = AgentRegistry.load(agents)
    assert "✨" in registry.get("edith").system_prompt
