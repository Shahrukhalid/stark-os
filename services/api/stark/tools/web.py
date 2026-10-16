"""Web research tools: search (Tavily / Brave), fetch, rendered browse, document ingestion.

No tool here pretends research happened: search without an API key returns a
clear setup error, and every retrieved URL is recorded as a task source so
Jocasta's citation check can flag anything that was never fetched.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.request import getproxies
from urllib.robotparser import RobotFileParser

import httpx
from pydantic import BaseModel, Field

from ..core.tool_registry import ApprovalText, Availability, Risk, Tool, ToolResult
from .filesystem import is_sensitive, rel, resolve_in_roots

USER_AGENT = "StarkOS-Research/0.1 (+personal research assistant; respects robots.txt)"
MAX_BYTES = 3_000_000


class FetchBlocked(PermissionError):
    pass


def _blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    # only globally routable addresses: blocks loopback, RFC1918, link-local, CGNAT (100.64/10, e.g. Tailscale),
    # multicast, reserved, documentation and unspecified (0.0.0.0) ranges
    return not ip.is_global or ip.is_multicast


async def check_url(url: str, allow_private: bool) -> str | None:
    """Validate a URL for outbound fetching. Returns the vetted IP to connect to (None if private allowed)."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise FetchBlocked("only http(s) URLs are allowed")
    if parts.username or parts.password:
        raise FetchBlocked("credentials in URLs are not allowed")
    host = parts.hostname or ""
    if not host:
        raise FetchBlocked("missing host")
    if allow_private:
        return None
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise FetchBlocked("local/private hosts are blocked (SSRF protection)")
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except socket.gaierror as exc:
        raise FetchBlocked(f"cannot resolve {host}") from exc
    ips = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    if not ips:
        raise FetchBlocked(f"cannot resolve {host}")
    for ip in ips:
        if _blocked_ip(ip):
            raise FetchBlocked(f"{host} resolves to a non-public address (SSRF protection)")
    return str(ips[0])


async def pinned_get(client: httpx.AsyncClient, url: str, ip: str | None, *, limit: int = MAX_BYTES,
                     timeout: float | None = None) -> httpx.Response:
    """GET ``url`` but connect to the already-vetted ``ip`` (defeats DNS rebinding between check and connect).
    TLS still verifies the certificate against the original host name via SNI. The body is streamed and
    cut at ``limit`` bytes, so a hostile server cannot exhaust memory."""
    parts = urlsplit(url)
    headers: dict[str, str] = {"Accept-Encoding": "gzip, deflate"}  # only encodings we can decode bounded
    extensions: dict[str, Any] = {}
    target = url
    if ip is not None and not getproxies().get(parts.scheme):
        # (Behind an HTTP proxy the proxy resolves names, so pinning is impossible and unnecessary.)
        host = parts.hostname or ""
        ip_host = f"[{ip}]" if ":" in ip else ip
        target = parts._replace(netloc=ip_host + (f":{parts.port}" if parts.port else "")).geturl()
        headers["Host"] = host + (f":{parts.port}" if parts.port else "")
        if parts.scheme == "https":
            extensions["sni_hostname"] = host
    if timeout is not None:
        extensions["timeout"] = httpx.Timeout(timeout).as_dict()
    request = client.build_request("GET", target, headers=headers, extensions=extensions)
    resp = await client.send(request, stream=True)
    try:
        chunks, size = [], 0
        try:
            async for chunk in resp.aiter_raw():
                chunks.append(chunk)
                size += len(chunk)
                if size >= limit:
                    break
            raw = b"".join(chunks)[:limit]
        except httpx.StreamConsumed:  # transports that hand back an already-read body (tests)
            raw = resp.content[:limit]
    finally:
        await resp.aclose()
    # rebuild a complete, decoded response object from the bounded body
    out = httpx.Response(resp.status_code, headers=resp.headers, content=_decode(raw, resp.headers), request=request)
    out.headers.pop("content-encoding", None)
    return out


def _decode(raw: bytes, headers: httpx.Headers) -> bytes:
    enc = headers.get("content-encoding", "").lower()
    try:
        if enc == "gzip":
            import zlib

            return zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw, MAX_BYTES)
        if enc == "deflate":
            import zlib

            return zlib.decompressobj().decompress(raw, MAX_BYTES)
    except Exception:
        return b""
    return raw


def outbound_needs_approval(url: str, ctx) -> bool:
    """Exfiltration guard. Fetching is read-only, but the URL itself can carry data out: an injected
    instruction can make an agent put anything it has seen (files, memories, earlier chat turns) into a URL.
    A URL runs without approval only if a web search in this task tree returned it, or the user typed it
    in this request. Everything else, and any URL with a long query, needs approval."""
    parts = urlsplit(url)
    if len(parts.query) > 200 or len(url) > 1000:
        return True
    kernel = getattr(ctx, "kernel", None)
    if kernel is None:
        return True
    normalized = url.rstrip("/")
    if normalized in kernel.tree_flags(ctx.root_id)["search_urls"]:
        return False
    root = kernel.get_task(ctx.root_id) or {}
    if root.get("requested_by", "user") == "user" and normalized in (root.get("instruction") or ""):
        return False
    return True


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "pre"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = [" ".join(ln.split()) for ln in raw.splitlines()]
        return "\n".join(ln for ln in lines if ln)


def html_to_text(html: str) -> tuple[str, str, list[str]]:
    p = _TextExtractor()
    p.feed(html)
    return p.title.strip(), p.text(), p.links


def pdf_to_text(data: bytes, max_pages: int = 50) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PDF support needs the 'pypdf' package") from exc
    reader = PdfReader(BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages[:max_pages])


async def robots_allows(client: httpx.AsyncClient, url: str, ip: str | None = None) -> bool:
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        resp = await pinned_get(client, robots_url, ip, timeout=8, limit=500_000)
    except httpx.HTTPError:
        return True  # unreachable robots.txt: treat as no restrictions (RFC 9309 §2.3.1.4 for 4xx)
    if resp.status_code >= 500:
        return False  # RFC 9309: server error => assume complete disallow
    if resp.status_code >= 400:
        return True
    rp = RobotFileParser()
    rp.parse(resp.text.splitlines())
    return rp.can_fetch(USER_AGENT, url)


class FetchInput(BaseModel):
    url: str
    max_chars: int = Field(20_000, ge=500, le=100_000)


class WebFetch(Tool):
    id = "web.fetch"
    category = "web"
    description = ("Retrieve a public web page or PDF and return its readable text. Respects robots.txt, blocks "
                   "private network addresses, records the URL as a source.")
    Input = FetchInput
    risk = Risk.READ
    timeout_s = 45

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def needs_approval(self, args, ctx) -> bool:
        return outbound_needs_approval(args.url, ctx)

    def describe(self, args, ctx):
        return ApprovalText(f"Fetch {args.url}", args.url, "Downloads a public page.",
                            "This URL did not come from a web search and you didn't type it: an injected "
                            "instruction could be smuggling data out inside the URL. Check the full URL first.")

    async def run(self, args: FetchInput, ctx) -> ToolResult:
        allow_private = ctx.settings.allow_private_fetch
        url = args.url
        async with httpx.AsyncClient(headers={"user-agent": USER_AGENT}, timeout=20, follow_redirects=False,
                                     transport=self._transport) as client:
            for _ in range(5):
                try:
                    ip = await check_url(url, allow_private)
                except FetchBlocked as exc:
                    return ToolResult(False, f"Blocked: {exc}", error="blocked")
                if not await robots_allows(client, url, ip):
                    return ToolResult(False, f"robots.txt disallows fetching {url}", error="robots_disallow")
                try:
                    resp = await pinned_get(client, url, ip)
                except httpx.HTTPError as exc:
                    return ToolResult(False, f"Fetch failed: {exc.__class__.__name__}", error="network")
                if resp.is_redirect and resp.headers.get("location"):
                    url = urljoin(url, resp.headers["location"])
                    continue
                break
            else:
                return ToolResult(False, "Too many redirects", error="redirects")
        if resp.status_code >= 400:
            return ToolResult(False, f"HTTP {resp.status_code} for {url}", error=f"http_{resp.status_code}")
        body = resp.content
        ctype = resp.headers.get("content-type", "")
        title, links = "", []
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            text = await asyncio.to_thread(pdf_to_text, body)
            kind = "pdf"
        elif "html" in ctype or body.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
            title, text, links = html_to_text(body.decode(resp.encoding or "utf-8", errors="replace"))
            kind = "html"
        else:
            text = body.decode(resp.encoding or "utf-8", errors="replace")
            kind = "text"
        retrieved = datetime.now(timezone.utc).isoformat()
        source = {"url": url, "title": title or url, "retrieved_at": retrieved,
                  "last_modified": resp.headers.get("last-modified")}
        return ToolResult(True, f"Retrieved {kind} '{title or url}' ({len(text)} chars)",
                          {"url": url, "title": title, "kind": kind, "retrieved_at": retrieved,
                           "last_modified": resp.headers.get("last-modified"),
                           "text": text[: args.max_chars], "truncated": len(text) > args.max_chars,
                           "links": [urljoin(url, h) for h in links[:40]]},
                          sources=[source])


class SearchInput(BaseModel):
    query: str = Field(..., min_length=2)
    max_results: int = Field(6, ge=1, le=15)


class WebSearch(Tool):
    id = "web.search"
    category = "web"
    description = "Search the web via a configured search API (Tavily or Brave). Returns titles, URLs and snippets."
    Input = SearchInput
    risk = Risk.READ
    timeout_s = 30

    def __init__(self, settings=None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport

    def availability(self, ctx=None):
        settings = ctx.settings if ctx else self._settings
        if settings and (settings.tavily_api_key or settings.brave_api_key):
            return Availability.IMPLEMENTED, "tavily" if settings.tavily_api_key else "brave"
        return Availability.REQUIRES_CREDENTIALS, "set TAVILY_API_KEY or BRAVE_API_KEY"

    async def run(self, args: SearchInput, ctx) -> ToolResult:
        s = ctx.settings
        async with httpx.AsyncClient(timeout=20, transport=self._transport) as client:
            try:
                if s.tavily_api_key:
                    resp = await client.post("https://api.tavily.com/search",
                                             json={"query": args.query, "max_results": args.max_results},
                                             headers={"Authorization": f"Bearer {s.tavily_api_key}"})
                    resp.raise_for_status()
                    items = [{"title": r.get("title"), "url": r.get("url"), "snippet": r.get("content", "")[:400]}
                             for r in resp.json().get("results", [])]
                    provider = "tavily"
                else:
                    resp = await client.get("https://api.search.brave.com/res/v1/web/search",
                                            params={"q": args.query, "count": args.max_results},
                                            headers={"X-Subscription-Token": s.brave_api_key,
                                                     "Accept": "application/json"})
                    resp.raise_for_status()
                    items = [{"title": r.get("title"), "url": r.get("url"), "snippet": r.get("description", "")[:400]}
                             for r in resp.json().get("web", {}).get("results", [])]
                    provider = "brave"
            except httpx.HTTPError as exc:
                return ToolResult(False, f"Search failed: {exc}", error="search_failed")
        now = datetime.now(timezone.utc).isoformat()
        return ToolResult(True, f"{len(items)} results from {provider}", {"provider": provider, "results": items},
                          sources=[{"url": i["url"], "title": i["title"], "retrieved_at": now, "via": "search"}
                                   for i in items if i.get("url")])


class RenderInput(BaseModel):
    url: str
    max_chars: int = Field(20_000, ge=500, le=100_000)
    screenshot: bool = False


class BrowserRender(Tool):
    id = "browser.render"
    category = "browser"
    description = ("Open a page in a headless Chromium (Playwright) to read JavaScript-rendered content; "
                   "optionally saves a screenshot into the workspace.")
    Input = RenderInput
    risk = Risk.READ
    timeout_s = 60

    def needs_approval(self, args, ctx) -> bool:
        return args.screenshot or outbound_needs_approval(args.url, ctx)  # screenshots write into the workspace

    def describe(self, args, ctx):
        return ApprovalText(f"Open {args.url} in a headless browser", args.url,
                            "Loads a public page." + (" Saves a screenshot into the workspace." if args.screenshot
                                                      else ""),
                            "Check the full URL: if it didn't come from a web search or from you, an injected "
                            "instruction could be smuggling data out inside it.")

    def availability(self, ctx=None):
        try:
            import playwright  # noqa: F401
        except ImportError:
            return Availability.UNAVAILABLE, "pip install playwright && playwright install chromium"
        return Availability.IMPLEMENTED, ""

    async def run(self, args: RenderInput, ctx) -> ToolResult:
        from playwright.async_api import Error as PWError, async_playwright

        try:
            first_ip = await check_url(args.url, ctx.settings.allow_private_fetch)
        except FetchBlocked as exc:
            return ToolResult(False, f"Blocked: {exc}", error="blocked")
        async with httpx.AsyncClient(headers={"user-agent": USER_AGENT}, timeout=10) as client:
            if not ctx.settings.allow_private_fetch and not await robots_allows(client, args.url, first_ip):
                return ToolResult(False, "robots.txt disallows this URL", error="robots_disallow")
        shot_path = None
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch()
                try:
                    page = await browser.new_page(user_agent=USER_AGENT)

                    async def guard(route):
                        url = route.request.url
                        try:
                            if url.startswith(("data:", "blob:")):
                                await route.continue_()
                                return
                            await check_url(url, ctx.settings.allow_private_fetch)
                            if route.request.is_navigation_request():
                                # Fetch navigations ourselves without following redirects, so every hop
                                # (each new request comes back through this guard) is checked.
                                resp = await route.fetch(max_redirects=0)
                                location = resp.headers.get("location")
                                if 300 <= resp.status < 400 and location:
                                    await check_url(urljoin(url, location), ctx.settings.allow_private_fetch)
                                await route.fulfill(response=resp)
                                return
                            await route.continue_()
                        except FetchBlocked:
                            await route.abort()

                    await page.route("**/*", guard)
                    # page.route does not see WebSockets: refuse them all (SSRF via ws://127.0.0.1)
                    await page.route_web_socket(re.compile(".*"), lambda ws: ws.close())
                    await page.goto(args.url, wait_until="domcontentloaded", timeout=30_000)
                    title = await page.title()
                    text = await page.inner_text("body")
                    if args.screenshot:
                        out = ctx.settings.workspace_roots[0] / "screenshots"
                        out.mkdir(parents=True, exist_ok=True)
                        shot_path = out / f"shot-{datetime.now():%Y%m%d-%H%M%S}.png"
                        await page.screenshot(path=str(shot_path), full_page=False)
                finally:
                    await browser.close()
        except PWError as exc:
            return ToolResult(False, f"Browser error: {str(exc)[:300]}", error="browser")
        now = datetime.now(timezone.utc).isoformat()
        return ToolResult(True, f"Rendered '{title}' ({len(text)} chars)",
                          {"url": args.url, "title": title, "text": text[: args.max_chars],
                           "screenshot": rel(shot_path, ctx.settings.workspace_roots) if shot_path else None},
                          sources=[{"url": args.url, "title": title, "retrieved_at": now, "via": "browser"}])


class IngestInput(BaseModel):
    path: str = Field(..., description="Workspace file (.pdf, .md, .txt, .html) to add to shared knowledge")
    chunk_chars: int = Field(1500, ge=300, le=6000)


class DocumentIngest(Tool):
    id = "docs.ingest"
    category = "document"
    description = "Extract text from a workspace document (PDF/Markdown/text/HTML) and store it as searchable shared knowledge."
    Input = IngestInput
    risk = Risk.MEMORY
    timeout_s = 120
    MAX_BYTES = 20_000_000

    def needs_approval(self, args, ctx) -> bool:
        return True  # writes durable knowledge every agent can read

    def describe(self, args, ctx):
        return ApprovalText(f"Add {args.path} to shared knowledge", "shared:knowledge",
                            "The document's text becomes searchable memory available to all agents.",
                            "Anything in the document (including instructions planted in it) will be visible to "
                            "every agent. Delete it in Memory if needed.")

    async def run(self, args: IngestInput, ctx) -> ToolResult:
        path = resolve_in_roots(args.path, ctx.settings.workspace_roots)
        if not path.is_file():
            return ToolResult(False, f"{args.path} not found", error="not_found")
        if is_sensitive(path):
            return ToolResult(False, "Refusing to ingest a credential/secret file", error="sensitive")
        if path.stat().st_size > self.MAX_BYTES:
            return ToolResult(False, "File too large to ingest (20 MB max)", error="too_large")
        data = await asyncio.to_thread(path.read_bytes)
        if path.suffix.lower() == ".pdf":
            text = await asyncio.to_thread(pdf_to_text, data, 200)
        elif path.suffix.lower() in {".html", ".htm"}:
            text = html_to_text(data.decode("utf-8", errors="replace"))[1]
        else:
            text = data.decode("utf-8", errors="replace")
        chunks, buf = [], ""
        for para in text.split("\n\n"):
            if len(buf) + len(para) > args.chunk_chars and buf:
                chunks.append(buf.strip())
                buf = ""
            buf += para + "\n\n"
        if buf.strip():
            chunks.append(buf.strip())
        saved = 0
        source = rel(path, ctx.settings.workspace_roots)
        for i, chunk in enumerate(chunks):
            ctx.kernel.memory.save(actor=ctx.agent, namespace="shared:knowledge", layer="semantic",
                                   content=chunk, source=f"{source}#chunk{i + 1}", tags=[Path(source).name])
            saved += 1
        return ToolResult(True, f"Ingested {source}: {saved} chunks into shared knowledge",
                          {"chunks": saved, "chars": len(text)})


def build(settings) -> list[Tool]:
    return [WebFetch(), WebSearch(settings), BrowserRender(), DocumentIngest()]
