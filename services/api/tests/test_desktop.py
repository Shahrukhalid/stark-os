"""Desktop app support: settings in the credential store and desktop.json, connection tests, auth."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stark import desktop

TOKEN = "t" * 32


class FakeKeyring:
    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, s, n):
        return self.store.get((s, n))

    def set_password(self, s, n, v):
        self.store[(s, n)] = v

    def delete_password(self, s, n):
        self.store.pop((s, n))

    def get_keyring(self):
        return self


@pytest.fixture
def env(tmp_path, monkeypatch):
    kr = FakeKeyring()
    monkeypatch.setenv("STARK_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(desktop, "_keyring", lambda: kr)
    monkeypatch.setattr(desktop, "_restart_soon", lambda delay=0.7: None)
    app = FastAPI()
    app.include_router(desktop.router(TOKEN))
    return TestClient(app), kr, tmp_path


H = {"authorization": f"Bearer {TOKEN}"}


def test_needs_a_token(env):
    client, _, _ = env
    assert client.get("/api/desktop/status").status_code == 401
    assert client.get("/api/desktop/status", headers={"authorization": "Bearer wrong"}).status_code == 401


def test_secrets_go_to_the_credential_store_and_settings_to_disk(env):
    client, kr, tmp = env
    assert client.get("/api/desktop/status", headers=H).json()["needs_setup"] is True
    r = client.put("/api/desktop/settings", headers=H, json={"values": {
        "OPENROUTER_API_KEY": "sk-secret", "BLUESKY_HANDLE": "me.bsky.social", "OPENROUTER_ALLOW_PAID": "true"}})
    assert r.json() == {"ok": True, "restarting": True}
    assert kr.store[("STARK OS", "OPENROUTER_API_KEY")] == "sk-secret"
    saved = json.loads((tmp / "desktop.json").read_text())
    assert saved == {"BLUESKY_HANDLE": "me.bsky.social", "OPENROUTER_ALLOW_PAID": "true"}
    assert "sk-secret" not in (tmp / "desktop.json").read_text()
    st = client.get("/api/desktop/status", headers=H).json()
    assert st["needs_setup"] is False and st["secrets"]["OPENROUTER_API_KEY"] is True
    assert "sk-secret" not in json.dumps(st)  # values are never sent back
    env_vars = desktop.environment()
    assert env_vars["OPENROUTER_API_KEY"] == "sk-secret" and env_vars["BLUESKY_HANDLE"] == "me.bsky.social"


def test_keep_and_clear(env):
    client, kr, _ = env
    client.put("/api/desktop/settings", headers=H, json={"values": {"OPENROUTER_API_KEY": "a"}})
    client.put("/api/desktop/settings", headers=H, json={"values": {"OPENROUTER_API_KEY": "__keep__"}})
    assert kr.store[("STARK OS", "OPENROUTER_API_KEY")] == "a"
    client.put("/api/desktop/settings", headers=H, json={"values": {"OPENROUTER_API_KEY": ""}})
    assert ("STARK OS", "OPENROUTER_API_KEY") not in kr.store


def test_unknown_setting_is_refused(env):
    client, _, _ = env
    r = client.put("/api/desktop/settings", headers=H, json={"values": {"PATH": "/evil"}})
    assert r.status_code == 400


def test_ai_test_lists_models(monkeypatch):
    def fake_get(url, headers=None, timeout=None, **kw):
        req = httpx.Request("GET", url)
        if url.endswith("/key"):
            return httpx.Response(200, json={"data": {}}, request=req)
        return httpx.Response(200, json={"data": [{"id": "a/b:free"}, {"id": "c/d"}]}, request=req)

    monkeypatch.setattr(desktop.httpx, "get", fake_get)
    r = desktop.test_ai("k", "https://openrouter.ai/api/v1")
    assert r["ok"] and r["models"] == 2 and r["free_models"] == 1
    assert desktop.test_ai("k", "http://evil.example/v1")["ok"] is False


def test_ai_test_reports_a_bad_key(monkeypatch):
    monkeypatch.setattr(desktop.httpx, "get", lambda url, **kw: httpx.Response(401, request=httpx.Request("GET", url)))
    assert desktop.test_ai("bad", "https://api.example.com/v1")["ok"] is False


def test_social_tests_never_post(monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(("GET", url))
        return httpx.Response(200, json={"acct": "me", "ok": True, "result": {"username": "bot"}},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(desktop.httpx, "get", fake_get)
    assert desktop.test_social("mastodon", {"MASTODON_BASE_URL": "https://m.social", "MASTODON_ACCESS_TOKEN": "x"})["ok"]
    assert desktop.test_social("telegram", {"TELEGRAM_BOT_TOKEN": "1:x"})["ok"]
    assert desktop.test_social("slack", {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/a"})["ok"]
    assert not desktop.test_social("slack", {"SLACK_WEBHOOK_URL": "https://evil.example/x"})["ok"]
    assert not desktop.test_social("mastodon", {"MASTODON_BASE_URL": "http://insecure"})["ok"]
    assert all(m == "GET" for m, _ in calls)


def test_update_check(monkeypatch):
    monkeypatch.setattr(desktop.httpx, "get", lambda url, **kw: httpx.Response(
        200, json={"tag_name": "v9.0.0", "html_url": "u"}, request=httpx.Request("GET", url)))
    assert desktop.check_update("1.1.0")["update"] is True
    assert desktop.check_update("9.0.0")["update"] is False


def test_diagnostics(env):
    client, _, _ = env
    d = client.get("/api/desktop/diagnostics", headers=H).json()
    assert {c["name"] for c in d["checks"]} >= {"Data folder is writable", "Credential store", "AI key saved"}


def _release(sha: str | None):
    base = desktop.DOWNLOAD_PREFIX + "v9.0.0/"
    return {"tag_name": "v9.0.0", "html_url": "u", "body": "What's new", "assets": [
        {"name": n, "size": 5, "browser_download_url": base + n, "digest": f"sha256:{sha}" if sha else None}
        for n in ("STARK-OS-macOS-AppleSilicon.dmg", "STARK-OS-macOS-Intel.dmg", "STARK-OS-Windows-Setup.exe")]}


def test_update_picks_installer_for_this_computer(monkeypatch):
    monkeypatch.setattr(desktop.httpx, "get", lambda url, **kw: httpx.Response(
        200, json=_release("ab"), request=httpx.Request("GET", url)))
    monkeypatch.setattr(desktop, "asset_name", lambda: "STARK-OS-Windows-Setup.exe")
    info = desktop.check_update("1.0.0")
    assert info["notes"] == "What's new" and info["asset"]["name"] == "STARK-OS-Windows-Setup.exe"
    assert info["asset"]["sha256"] == "ab"
    monkeypatch.setattr(desktop, "asset_name", lambda: None)
    assert desktop.check_update("1.0.0")["asset"] is None


def _fake_stream(payload: bytes):
    from contextlib import contextmanager

    @contextmanager
    def stream(method, url, **kw):
        yield httpx.Response(200, content=payload, headers={"content-length": str(len(payload))},
                             request=httpx.Request(method, url))
    return stream


def test_updater_downloads_and_verifies(monkeypatch, tmp_path):
    import hashlib
    import time

    data = b"12345"
    monkeypatch.setattr(desktop.httpx, "stream", _fake_stream(data))
    asset = _release(hashlib.sha256(data).hexdigest())["assets"][0]
    asset = {"name": asset["name"], "size": 5, "url": asset["browser_download_url"],
             "sha256": hashlib.sha256(data).hexdigest()}
    u = desktop.Updater()
    u.start(asset, tmp_path, open_file=False)
    for _ in range(100):
        if u.state["status"] != "downloading":
            break
        time.sleep(0.02)
    assert u.state["status"] == "ready" and (tmp_path / asset["name"]).read_bytes() == data

    bad = desktop.Updater()
    bad.start({**asset, "sha256": "0" * 64}, tmp_path / "b", open_file=False)
    for _ in range(100):
        if bad.state["status"] != "downloading":
            break
        time.sleep(0.02)
    assert bad.state["status"] == "error" and "checksum" in bad.state["error"]
    assert not list((tmp_path / "b").iterdir())
    import pytest

    with pytest.raises(ValueError):
        desktop.Updater().start({**asset, "url": "https://evil.example/x.dmg"}, tmp_path, open_file=False)
