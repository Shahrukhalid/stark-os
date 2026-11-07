"""Docker entry point: creates one persistent API token when STARK_API_TOKEN is unset."""

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the Docker entry point uses fcntl (Linux only)")


def _load(monkeypatch, tmp_path):
    monkeypatch.setenv("STARK_DATA_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("stark_start", Path(__file__).parents[1] / "start.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_token_created_once_and_kept(monkeypatch, tmp_path):
    monkeypatch.delenv("STARK_API_TOKEN", raising=False)
    mod = _load(monkeypatch, tmp_path)
    first = mod.get_api_token()
    assert len(first) >= 24 and mod.get_api_token() == first
    assert (tmp_path / "api-token").stat().st_mode & 0o777 == 0o600


def test_configured_token_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("STARK_API_TOKEN", "x" * 30)
    assert _load(monkeypatch, tmp_path).get_api_token() == "x" * 30
    assert not (tmp_path / "api-token").exists()
