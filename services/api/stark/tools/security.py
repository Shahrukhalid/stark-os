"""Defensive configuration audit for a project inside the workspace (E.D.I.T.H.).

Read-only static checks. Detected secrets are masked in the output; this tool
never extracts or transmits credentials.
"""

from __future__ import annotations

import asyncio
import fnmatch
import re
import stat
from pathlib import Path

from pydantic import BaseModel, Field

from ..core.tool_registry import ApprovalText, Risk, Tool, ToolResult
from .filesystem import SKIP_DIRS, inside_roots, is_sensitive, rel, resolve_in_roots

SECRET_RULES = [
    ("OpenRouter API key", re.compile(r"sk-or-v1-[0-9a-fA-F]{32,}"), "critical"),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}"), "critical"),
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "critical"),
    ("OpenAI-style API key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9]{20,}"), "critical"),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), "critical"),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "critical"),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "critical"),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), "critical"),
    ("Hardcoded credential", re.compile(
        # also matches compound names such as OPENROUTER_API_KEY=... or STARK_API_TOKEN=...
        r"(?i)(?<![A-Za-z0-9])[A-Z0-9_]*(api[_-]?key|secret|token|passwd|password)[\"']?\s*[:=]\s*['\"]?"
        r"([A-Za-z0-9_\-/+=.]{12,})"), "high"),
]
WEAK_PASSWORD = re.compile(r"(?i)\b(password|passwd|pwd)\b\s*[:=]\s*['\"]?(admin|password|changeme|123456|root|test)\b")
DEBUG_ON = re.compile(r"(?i)^\s*(debug|DEBUG|FLASK_DEBUG|APP_DEBUG)\s*[:=]\s*['\"]?(true|1|yes|on)\b")
CORS_ANY = re.compile(r"(?i)(allow_origins\s*=\s*\[\s*['\"]\*['\"]|Access-Control-Allow-Origin['\"]?\s*[:,]\s*['\"]\*)")
BIND_ALL = re.compile(r"(?i)(host\s*[:=]\s*['\"]?0\.0\.0\.0|--host\s+0\.0\.0\.0)")
TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf",
            ".env", ".sh", ".md", ".txt", ".properties", ".xml", ".tf", ".go", ".rb", ".php", ""}
PLACEHOLDER = re.compile(r"(?i)(your[_-]|example|changeme|xxx|<|\$\{|placeholder|dummy|test[_-]?key)")


def _mask(s: str) -> str:
    return s[:4] + "…" + s[-2:] if len(s) > 8 else "…"


class AuditInput(BaseModel):
    path: str = Field(".", description="Project directory inside the workspace")
    max_files: int = Field(3000, le=20000)


class SecurityAudit(Tool):
    id = "security.audit_config"
    category = "security"
    description = ("Defensive static audit of a project folder: leaked secrets (masked), .env exposure, "
                   ".gitignore gaps, debug flags, permissive CORS, 0.0.0.0 binds, Docker risks, weak passwords, "
                   "world-writable files.")
    Input = AuditInput
    risk = Risk.READ
    timeout_s = 90

    def describe(self, args, ctx):
        return ApprovalText(f"Security audit of {args.path}", args.path, "None (read-only)", "None")

    async def run(self, args: AuditInput, ctx) -> ToolResult:
        base = resolve_in_roots(args.path, ctx.settings.workspace_roots)
        if not base.is_dir():
            return ToolResult(False, f"{args.path} is not a directory", error="not_a_directory")
        return await asyncio.to_thread(self._audit, base, args.max_files, ctx.settings.workspace_roots)

    def _audit(self, base: Path, max_files: int, roots: list[Path]) -> ToolResult:
        findings: list[dict] = []

        def add(sev: str, kind: str, path: Path | None, detail: str, fix: str, line: int | None = None):
            findings.append({"severity": sev, "type": kind, "path": rel(path, roots) if path else None,
                             "line": line, "detail": detail, "remediation": fix})

        gitignore = base / ".gitignore"
        ignore_patterns = []
        if gitignore.is_file():
            ignore_patterns = [ln.strip() for ln in gitignore.read_text(errors="replace").splitlines()
                               if ln.strip() and not ln.startswith("#")]
        elif (base / ".git").exists() or any(base.glob("*.py")) or any(base.glob("package.json")):
            add("medium", "missing_gitignore", base, "No .gitignore: secrets and build output may be committed",
                "Add a .gitignore that excludes .env, keys, virtualenvs and build output")

        def ignored(p: Path) -> bool:
            r = str(p.relative_to(base))
            return any(fnmatch.fnmatch(r, pat.strip("/")) or fnmatch.fnmatch(p.name, pat.strip("/"))
                       for pat in ignore_patterns if not pat.startswith("!"))

        scanned = 0
        for p in base.rglob("*"):
            if any(part in SKIP_DIRS for part in p.relative_to(base).parts):
                continue
            if p.is_symlink() or not p.is_file() or not inside_roots(p, roots):
                continue
            scanned += 1
            if scanned > max_files:
                add("info", "scan_limit", base, f"Stopped after {max_files} files", "Narrow the path")
                break
            mode = p.stat().st_mode
            if mode & stat.S_IWOTH:
                add("medium", "world_writable", p, "File is writable by every user", "chmod o-w <file>")
            if is_sensitive(p) and p.name != ".env.example":
                if ignore_patterns and not ignored(p):
                    add("high", "sensitive_not_ignored", p, "Sensitive file is not covered by .gitignore",
                        "Add it to .gitignore and rotate any credentials it contains if it was ever committed")
                elif not ignore_patterns:
                    add("medium", "sensitive_file", p, "Sensitive file present in project",
                        "Keep it out of version control; prefer a secret manager")
                if mode & (stat.S_IRGRP | stat.S_IROTH):
                    add("medium", "sensitive_permissions", p, "Sensitive file readable by group/others",
                        "chmod 600 <file>")
            if p.suffix.lower() not in TEXT_EXT and p.name not in {"Dockerfile", "Makefile"}:
                continue
            if p.stat().st_size > 1_000_000:
                continue
            try:
                text = p.read_text("utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            is_example = p.name.endswith((".example", ".sample", ".template")) or "test" in p.parts[-1].lower()
            for i, ln in enumerate(text.splitlines(), 1):
                for name, rx, sev in SECRET_RULES:
                    m = rx.search(ln)
                    if not m:
                        continue
                    value = m.group(m.lastindex or 0)
                    if PLACEHOLDER.search(ln) or is_example:
                        continue
                    add(sev, "secret", p, f"{name}: {_mask(value)}",
                        "Remove it from the file, load it from the environment, and rotate the credential",
                        i)
                    break
                if WEAK_PASSWORD.search(ln):
                    add("high", "weak_password", p, "Default/weak password", "Use a strong secret from the environment", i)
                if DEBUG_ON.search(ln) and not is_example:
                    add("medium", "debug_enabled", p, "Debug mode enabled", "Disable debug outside development", i)
                if CORS_ANY.search(ln):
                    add("medium", "cors_wildcard", p, "CORS allows any origin",
                        "Restrict allowed origins to known front-ends", i)
                if BIND_ALL.search(ln):
                    add("low", "bind_all_interfaces", p, "Service binds to all interfaces (0.0.0.0)",
                        "Bind to 127.0.0.1 unless remote access is intended and authenticated", i)
            if p.name.startswith("docker-compose") or p.name in {"compose.yml", "compose.yaml"}:
                if re.search(r"(?m)^\s*privileged:\s*true", text):
                    add("high", "docker_privileged", p, "Container runs privileged", "Remove privileged: true")
                if re.search(r"(?m)^\s*network_mode:\s*['\"]?host", text):
                    add("medium", "docker_host_network", p, "Container uses host networking",
                        "Use a bridge network and publish only needed ports")
                if "/var/run/docker.sock" in text:
                    add("high", "docker_socket", p, "Docker socket mounted into a container",
                        "Avoid mounting docker.sock; it grants root on the host")
            if p.name == "Dockerfile":
                if not re.search(r"(?m)^\s*USER\s+", text):
                    add("medium", "docker_root", p, "Image runs as root (no USER instruction)",
                        "Add a non-root USER")
                if re.search(r"(?m)^\s*FROM\s+\S+:latest", text):
                    add("low", "docker_latest_tag", p, "Base image uses :latest", "Pin a specific version")
        if ignore_patterns and not any(x in ignore_patterns for x in (".env", ".env*", "*.env", ".env.*")):
            add("medium", "gitignore_env", gitignore, ".gitignore does not exclude .env files", "Add '.env' to .gitignore")
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        findings.sort(key=lambda f: order[f["severity"]])
        counts = {s: sum(1 for f in findings if f["severity"] == s) for s in order}
        summary = (f"Scanned {min(scanned, max_files)} files: "
                   + ", ".join(f"{v} {k}" for k, v in counts.items() if v) if findings
                   else f"Scanned {scanned} files: no issues found by these checks")
        return ToolResult(True, summary, {"findings": findings[:200], "counts": counts, "files_scanned": scanned})


TOOLS = [SecurityAudit()]
