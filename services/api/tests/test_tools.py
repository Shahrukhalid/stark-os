"""Every tool marked 'implemented' is exercised here against real files, processes or HTTP shapes."""

from __future__ import annotations

import http.server
import json
import os
import threading

import httpx
import pytest

from stark.core.runtime import ToolContext
from stark.core.tool_registry import Availability
from stark.tools.filesystem import FsList, FsMove, FsRead, FsWrite, PathError
from stark.tools.security import SecurityAudit
from stark.tools.system import SystemMetrics
from stark.tools.web import BrowserRender, WebFetch, WebSearch, html_to_text, pdf_to_text

from .conftest import make_kernel


@pytest.fixture
def kctx(settings):
    k, _ = make_kernel(settings)

    def ctx(agent_id: str | None = "jarvis") -> ToolContext:
        agent = k.registry.get(agent_id) if agent_id else None
        t = k._create_task(agent_id=agent_id or "user", instruction="test")
        return ToolContext(kernel=k, agent=agent, task_id=t["id"], root_id=t["id"], settings=settings)

    return k, ctx


# ----------------------------------------------------------------- filesystem
async def test_fs_sandbox_blocks_escape(kctx, workspace, tmp_path):
    k, ctx = kctx
    (tmp_path / "outside.txt").write_text("secret")
    for bad in ["../outside.txt", str(tmp_path / "outside.txt"), "/etc/passwd"]:
        with pytest.raises(PathError):
            await FsRead().run(FsRead.Input(path=bad), ctx())
    # symlink pointing outside the workspace is also refused
    os.symlink(tmp_path / "outside.txt", workspace / "link.txt")
    with pytest.raises(PathError):
        await FsRead().run(FsRead.Input(path="link.txt"), ctx())


async def test_directory_walks_ignore_symlinked_dirs_outside(kctx, workspace, tmp_path):
    from stark.tools.filesystem import FsSearch

    k, ctx = kctx
    outside = tmp_path / "outside_dir"
    outside.mkdir()
    (outside / "private.txt").write_text("needle outside")
    os.symlink(outside, workspace / "escape")
    (workspace / "inside.txt").write_text("needle inside")
    found = await FsSearch().run(FsSearch.Input(query="needle"), ctx())
    assert [m["path"] for m in found.data["matches"]] == ["inside.txt"]
    listing = await FsList().run(FsList.Input(path=".", recursive=True), ctx())
    assert not any("private" in e["path"] for e in listing.data["entries"])


async def test_fs_read_sensitive_needs_approval(kctx, workspace):
    k, ctx = kctx
    (workspace / ".env").write_text("X=1")
    (workspace / "readme.md").write_text("hi")
    tool = FsRead()
    assert tool.needs_approval(FsRead.Input(path=".env"), ctx()) is True
    assert tool.needs_approval(FsRead.Input(path="readme.md"), ctx()) is False


async def test_fs_move_never_overwrites(kctx, workspace):
    k, ctx = kctx
    (workspace / "a.txt").write_text("A")
    (workspace / "b.txt").write_text("B")
    res = await FsMove().run(FsMove.Input(moves=[{"src": "a.txt", "dst": "b.txt"}]), ctx())
    assert res.data["failed"] and (workspace / "b.txt").read_text() == "B"


async def test_fs_write_and_list(kctx, workspace):
    k, ctx = kctx
    res = await FsWrite().run(FsWrite.Input(path="notes/plan.md", content="# Plan"), ctx())
    assert res.ok and (workspace / "notes" / "plan.md").read_text() == "# Plan"
    again = await FsWrite().run(FsWrite.Input(path="notes/plan.md", content="x"), ctx())
    assert not again.ok and again.error == "exists"
    listing = await FsList().run(FsList.Input(path=".", recursive=True), ctx())
    assert any(e["path"].endswith("plan.md") for e in listing.data["entries"])


# ----------------------------------------------------------------- system
async def test_demo2_system_metrics_are_real(kctx):
    k, ctx = kctx
    res = await SystemMetrics().run(SystemMetrics.Input(top_n=5, sample_seconds=0.3), ctx(None))
    assert res.ok
    d = res.data
    assert d["memory"]["total_gb"] > 0 and d["process_count"] > 1
    assert any(p["pid"] == os.getpid() for p in d["top_memory"] + d["top_cpu"]) or d["process_count"] > 5
    assert d["host"]["os"] in {"Linux", "Darwin", "Windows"}


# ----------------------------------------------------------------- security
async def test_demo5_security_audit_finds_real_issues(kctx, workspace):
    k, ctx = kctx
    proj = workspace / "proj"
    proj.mkdir()
    fake_key = "AKIA" + "QWERTYUIOPASDFGH"  # assembled at runtime so the repo itself has no key-shaped string
    (proj / "settings.py").write_text(f'AWS_KEY = "{fake_key}"\nDEBUG = True\n')
    (proj / ".env").write_text("DB_PASSWORD=" + "hunter2hunter2xyz\n")
    (proj / ".gitignore").write_text("node_modules\n")
    (proj / "docker-compose.yml").write_text("services:\n  app:\n    privileged: true\n")
    (proj / "Dockerfile").write_text("FROM python:latest\nCMD python app.py\n")
    res = await SecurityAudit().run(SecurityAudit.Input(path="proj"), ctx("edith"))
    types = {f["type"] for f in res.data["findings"]}
    assert {"secret", "debug_enabled", "sensitive_not_ignored", "docker_privileged", "docker_root",
            "docker_latest_tag", "gitignore_env"} <= types
    secret = [f for f in res.data["findings"] if f["type"] == "secret"][0]
    assert fake_key not in json.dumps(res.data) and secret["line"] == 1  # masked


async def test_security_audit_clean_project(kctx, workspace):
    k, ctx = kctx
    proj = workspace / "clean"
    proj.mkdir()
    (proj / ".gitignore").write_text(".env\n")
    (proj / "app.py").write_text("print('hello')\n")
    res = await SecurityAudit().run(SecurityAudit.Input(path="clean"), ctx("edith"))
    assert res.data["findings"] == []


# ----------------------------------------------------------------- web
def _mock_site(routes: dict[str, tuple[int, str, str]]):
    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path
        status, ctype, body = routes.get(key, (404, "text/plain", "nf"))
        return httpx.Response(status, headers={"content-type": ctype}, content=body.encode()
                              if isinstance(body, str) else body)
    return httpx.MockTransport(handler)


async def test_web_fetch_extracts_text_and_records_source(kctx, settings):
    k, ctx = kctx
    settings.allow_private_fetch = True  # MockTransport host; DNS-based SSRF check tested separately
    site = _mock_site({"/robots.txt": (200, "text/plain", "User-agent: *\nDisallow: /private\n"),
                       "/page": (200, "text/html", "<html><head><title>Ollama Docs</title></head><body>"
                                 "<script>evil()</script><h1>Run models</h1><p>Local LLMs.</p></body></html>")})
    res = await WebFetch(site).run(WebFetch.Input(url="https://docs.example.org/page"), ctx("jocasta"))
    assert res.ok and res.data["title"] == "Ollama Docs"
    assert "Run models" in res.data["text"] and "evil" not in res.data["text"]
    assert res.sources[0]["url"] == "https://docs.example.org/page"
    blocked = await WebFetch(site).run(WebFetch.Input(url="https://docs.example.org/private/x"), ctx("jocasta"))
    assert not blocked.ok and blocked.error == "robots_disallow"


async def test_web_fetch_blocks_ssrf(kctx):
    k, ctx = kctx
    for url in ["http://127.0.0.1:8000/api/settings/mode", "http://169.254.169.254/latest/meta-data",
                "http://localhost/", "file:///etc/passwd", "http://user:pw@example.com/"]:
        res = await WebFetch().run(WebFetch.Input(url=url), ctx("jocasta"))
        assert not res.ok and res.error == "blocked", url


def _tiny_pdf(text: str) -> bytes:
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


async def test_pdf_extraction_and_ingest(kctx, workspace):
    k, ctx = kctx
    assert "Genesis architecture" in pdf_to_text(_tiny_pdf("Genesis architecture"))
    (workspace / "spec.pdf").write_bytes(_tiny_pdf("Genesis architecture"))
    from stark.tools.web import DocumentIngest

    res = await DocumentIngest().run(DocumentIngest.Input(path="spec.pdf"), ctx("jocasta"))
    assert res.ok and res.data["chunks"] == 1
    hits = k.memory.search(actor=k.registry.get("friday"), query="genesis architecture")
    assert hits and hits[0]["namespace"] == "shared:knowledge"


async def test_web_search_requires_credentials_then_works(kctx, settings):
    k, ctx = kctx
    tool = WebSearch(settings)
    assert tool.availability()[0] is Availability.REQUIRES_CREDENTIALS
    settings.tavily_api_key = "tvly-test"
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"results": [
        {"title": "Ollama", "url": "https://ollama.com/", "content": "Get up and running with LLMs"}]}))
    tool = WebSearch(settings, transport)
    assert tool.availability()[0] is Availability.IMPLEMENTED
    res = await tool.run(WebSearch.Input(query="local llm"), ctx("jocasta"))
    assert res.ok and res.data["results"][0]["url"] == "https://ollama.com/"
    assert res.sources[0]["via"] == "search"


def test_html_to_text_strips_scripts():
    title, body, links = html_to_text("<title>T</title><nav>menu</nav><p>Hello <a href='/x'>x</a></p>")
    assert title == "T" and "menu" not in body and "Hello" in body and links == ["/x"]


@pytest.mark.browser
async def test_browser_render_real_chromium(kctx, settings, tmp_path):
    pytest.importorskip("playwright", reason="install the 'browser' extra")
    k, ctx = kctx
    settings.allow_private_fetch = True
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "index.html").write_text(
        "<html><head><title>JS Page</title></head><body><div id=o></div>"
        "<script>document.getElementById('o').innerText='rendered by javascript'</script></body></html>")
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=str(tmp_path / "site"), **kw)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        res = await BrowserRender().run(BrowserRender.Input(url=f"http://127.0.0.1:{server.server_port}/",
                                                           screenshot=True), ctx("jocasta"))
    finally:
        server.shutdown()
    assert res.ok, res.summary
    assert "rendered by javascript" in res.data["text"]
    assert (settings.workspace_roots[0] / res.data["screenshot"]).is_file()
