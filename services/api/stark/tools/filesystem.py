"""File tools, confined to the configured workspace roots (STARK_WORKSPACE_ROOTS)."""

from __future__ import annotations

import asyncio
import fnmatch
import shutil
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

from ..core.tool_registry import ApprovalText, Risk, Tool, ToolResult

SENSITIVE_PATTERNS = [".env", ".env.*", "*.pem", "*.key", "id_rsa*", "id_ed25519*", "*.p12", "*.pfx",
                      "credentials*", "*secret*", "*.kdbx", ".netrc", ".npmrc", ".pypirc"]
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".next"}
# Version-control metadata can make tools like git execute commands (hooks, fsmonitor):
# agents may never create, change or move anything inside these directories.
PROTECTED_DIRS = {".git", ".hg", ".svn"}
MAX_READ_BYTES = 200_000

CATEGORIES = {
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".pages"},
    "Spreadsheets": {".xls", ".xlsx", ".csv", ".numbers", ".ods"},
    "Images": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".heic", ".bmp"},
    "Audio": {".mp3", ".wav", ".m4a", ".flac", ".ogg"},
    "Video": {".mp4", ".mov", ".mkv", ".avi", ".webm"},
    "Archives": {".zip", ".tar", ".gz", ".rar", ".7z", ".tgz"},
    "Code": {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".cpp", ".h", ".sh", ".rb"},
    "Data": {".json", ".yaml", ".yml", ".toml", ".xml", ".sql", ".db"},
    "Presentations": {".ppt", ".pptx", ".key"},
}


class PathError(PermissionError):
    pass


def resolve_in_roots(raw: str, roots: list[Path]) -> Path:
    """Resolve ``raw`` (absolute, or relative to the first root) and require it to stay inside a root."""
    if not roots:
        raise PathError("no workspace roots configured")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = roots[0] / candidate
    resolved = candidate.resolve()
    for root in roots:
        if resolved == root or root in resolved.parents:
            return resolved
    raise PathError(f"{raw} is outside the authorised workspace ({', '.join(map(str, roots))})")


def inside_roots(path: Path, roots: list[Path]) -> bool:
    """True if the fully resolved path (following symlinks) stays inside a workspace root."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return any(resolved == r or r in resolved.parents for r in roots)


def is_sensitive(path: Path) -> bool:
    """Credential-looking file, judged on both the given name and the symlink target's name."""
    names = {path.name.lower()}
    try:
        names.add(path.resolve().name.lower())
    except OSError:
        pass
    return any(fnmatch.fnmatch(n, p) for n in names for p in SENSITIVE_PATTERNS)


def is_protected(path: Path) -> bool:
    return any(part in PROTECTED_DIRS for part in path.parts)


def scope_key(raw: str, roots: list[Path]) -> str:
    """Normalised workspace-relative path used to match standing grants ('' if outside)."""
    try:
        return rel(resolve_in_roots(raw, roots), roots)
    except PathError:
        return "\x00outside"


def in_scope(key: str, scope: str) -> bool:
    if key.startswith("\x00"):
        return False
    scope = scope.strip().strip("/")
    if scope in ("", "."):
        return True
    return key == scope or key.startswith(scope + "/")


def rel(path: Path, roots: list[Path]) -> str:
    for root in roots:
        if path == root or root in path.parents:
            return str(path.relative_to(root)) or "."
    return str(path)


def category_for(path: Path) -> str:
    ext = path.suffix.lower()
    for name, exts in CATEGORIES.items():
        if ext in exts:
            return name
    return "Other"


class ListInput(BaseModel):
    path: str = Field(".", description="Directory inside the workspace (relative to the first root, or absolute)")
    recursive: bool = False
    max_entries: int = Field(500, le=2000)


class FsList(Tool):
    id = "fs.list"
    category = "file"
    description = "List files and folders inside the authorised workspace."
    Input = ListInput
    risk = Risk.READ

    async def run(self, args: ListInput, ctx) -> ToolResult:
        return await asyncio.to_thread(self._run, args, ctx.settings.workspace_roots)

    def _run(self, args: ListInput, roots: list[Path]) -> ToolResult:
        base = resolve_in_roots(args.path, roots)
        if not base.is_dir():
            return ToolResult(False, f"{args.path} is not a directory", error="not_a_directory")
        entries = []
        iterator = base.rglob("*") if args.recursive else base.iterdir()
        for p in sorted(iterator):
            if any(part in SKIP_DIRS for part in p.relative_to(base).parts) or not inside_roots(p, roots):
                continue
            st = p.lstat()
            entries.append({"path": rel(p, roots), "type": "dir" if p.is_dir() else "file",
                            "size": st.st_size if p.is_file() else None,
                            "sensitive": is_sensitive(p)})
            if len(entries) >= args.max_entries:
                break
        return ToolResult(True, f"{len(entries)} entries in {rel(base, roots)}", {"entries": entries})

    def describe(self, args, ctx):
        return ApprovalText(f"List {args.path}", args.path, "None (read-only)", "None")


class ReadInput(BaseModel):
    path: str
    max_bytes: int = Field(50_000, le=MAX_READ_BYTES)


class FsRead(Tool):
    id = "fs.read"
    category = "file"
    description = "Read a text file inside the workspace. Sensitive files (.env, keys) require approval."
    Input = ReadInput
    risk = Risk.READ

    def needs_approval(self, args: ReadInput, ctx) -> bool:
        try:
            return is_sensitive(resolve_in_roots(args.path, ctx.settings.workspace_roots))
        except PathError:
            return False

    def describe(self, args, ctx):
        return ApprovalText(f"Read file {args.path}", args.path,
                            "File contents will be shown to the agent and sent to its model provider.",
                            "File looks sensitive (credentials/keys). Contents could be exposed to the model.")

    async def run(self, args: ReadInput, ctx) -> ToolResult:
        return await asyncio.to_thread(self._run, args, ctx)

    def _run(self, args: ReadInput, ctx) -> ToolResult:
        path = resolve_in_roots(args.path, ctx.settings.workspace_roots)
        if not path.is_file():
            return ToolResult(False, f"{args.path} is not a file", error="not_found")
        with path.open("rb") as fh:
            raw = fh.read(args.max_bytes)
        if b"\x00" in raw[:4096]:
            return ToolResult(False, f"{args.path} looks binary; not read", error="binary")
        text = raw.decode("utf-8", errors="replace")
        truncated = path.stat().st_size > args.max_bytes
        return ToolResult(True, f"Read {len(text)} chars from {rel(path, ctx.settings.workspace_roots)}"
                          + (" (truncated)" if truncated else ""),
                          {"path": rel(path, ctx.settings.workspace_roots), "content": text,
                           "truncated": truncated})


class SearchInput(BaseModel):
    query: str = Field(..., min_length=1, description="Text to find in file names and contents")
    path: str = "."
    max_results: int = Field(50, le=500)


class FsSearch(Tool):
    id = "fs.search"
    category = "file"
    description = "Search file names and text contents inside the workspace (sensitive files are skipped)."
    Input = SearchInput
    risk = Risk.READ
    timeout_s = 60

    async def run(self, args: SearchInput, ctx) -> ToolResult:
        return await asyncio.to_thread(self._run, args, ctx.settings.workspace_roots)

    def _run(self, args: SearchInput, roots: list[Path]) -> ToolResult:
        base = resolve_in_roots(args.path, roots)
        q = args.query.lower()
        hits = []
        for p in base.rglob("*"):
            if (any(part in SKIP_DIRS for part in p.relative_to(base).parts) or p.is_symlink() or not p.is_file()
                    or is_sensitive(p) or not inside_roots(p, roots)):
                continue
            if q in p.name.lower():
                hits.append({"path": rel(p, roots), "match": "name"})
            elif p.stat().st_size < 2_000_000:
                try:
                    text = p.read_text("utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if q in line.lower():
                        hits.append({"path": rel(p, roots), "match": "content", "line": i,
                                     "text": line.strip()[:200]})
                        break
            if len(hits) >= args.max_results:
                break
        return ToolResult(True, f"{len(hits)} matches for '{args.query}'", {"matches": hits})


class ProposeInput(BaseModel):
    path: str = "."


class FsProposeOrganization(Tool):
    id = "fs.propose_organization"
    category = "file"
    description = ("Inspect a folder and propose moving loose files into category subfolders. "
                   "Read-only: returns a list of moves you can pass to fs.move.")
    Input = ProposeInput
    risk = Risk.READ

    async def run(self, args: ProposeInput, ctx) -> ToolResult:
        roots = ctx.settings.workspace_roots
        base = resolve_in_roots(args.path, roots)
        if not base.is_dir():
            return ToolResult(False, f"{args.path} is not a directory", error="not_a_directory")
        moves = []
        for p in sorted(base.iterdir()):
            if p.is_file() and not p.name.startswith("."):
                cat = category_for(p)
                moves.append({"src": rel(p, roots), "dst": rel(base / cat / p.name, roots)})
        counts = Counter(Path(m["dst"]).parent.name for m in moves)
        return ToolResult(True, f"Proposed {len(moves)} moves into {len(counts)} folders",
                          {"moves": moves, "folders": dict(counts)})


class Move(BaseModel):
    src: str
    dst: str


class MoveInput(BaseModel):
    moves: list[Move] = Field(..., min_length=1, max_length=500)


class FsMove(Tool):
    id = "fs.move"
    category = "file"
    description = "Move/rename files inside the workspace. Never overwrites. Requires approval."
    Input = MoveInput
    risk = Risk.WRITE

    def grant_scope_keys(self, args: MoveInput, ctx) -> list[str]:
        roots = ctx.settings.workspace_roots
        return [scope_key(p, roots) for m in args.moves for p in (m.src, m.dst)]

    def needs_approval(self, args: MoveInput, ctx) -> bool:
        """Moving credential files is never covered by a standing grant."""
        roots = ctx.settings.workspace_roots
        for m in args.moves:
            for raw in (m.src, m.dst):
                try:
                    if is_sensitive(resolve_in_roots(raw, roots)):
                        return True
                except PathError:
                    pass
        return False

    def describe(self, args, ctx):
        lines = "\n".join(f"{m.src} -> {m.dst}" for m in args.moves[:50])
        more = f"\n... and {len(args.moves) - 50} more" if len(args.moves) > 50 else ""
        return ApprovalText(f"Move {len(args.moves)} file(s)", "workspace",
                            f"{lines}{more}",
                            "Files change location. Existing files are never overwritten; moves can be reversed "
                            "manually.")

    async def run(self, args: MoveInput, ctx) -> ToolResult:
        return await asyncio.to_thread(self._run, args, ctx.settings.workspace_roots)

    def _run(self, args: MoveInput, roots: list[Path]) -> ToolResult:
        done, failed = [], []
        for m in args.moves:
            try:
                src = resolve_in_roots(m.src, roots)
                dst = resolve_in_roots(m.dst, roots)
                if not src.exists() and not src.is_symlink():
                    raise FileNotFoundError(m.src)
                if src in roots:
                    raise PermissionError("cannot move a workspace root")
                if is_protected(src) or is_protected(dst):
                    raise PermissionError("version-control metadata (.git etc.) is protected")
                if src.is_dir() and (dst == src or src in dst.parents):
                    raise PermissionError("cannot move a folder into itself")
                if dst.exists():
                    raise FileExistsError(f"{m.dst} already exists")
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                done.append({"src": m.src, "dst": m.dst})
            except (OSError, PathError) as exc:
                failed.append({"src": m.src, "dst": m.dst, "error": str(exc)})
        return ToolResult(not failed or bool(done), f"Moved {len(done)} file(s), {len(failed)} failed",
                          {"moved": done, "failed": failed})


class WriteInput(BaseModel):
    path: str
    content: str = Field(..., max_length=500_000)
    overwrite: bool = False


class FsWrite(Tool):
    id = "fs.write"
    category = "file"
    description = "Create (or, with overwrite=true, replace) a text file inside the workspace. Requires approval."
    Input = WriteInput
    risk = Risk.WRITE

    def needs_approval(self, args: WriteInput, ctx) -> bool:
        return args.overwrite  # overwrites are never covered by standing grants

    def grant_scope_keys(self, args: WriteInput, ctx) -> list[str]:
        return [scope_key(args.path, ctx.settings.workspace_roots)]

    def describe(self, args, ctx):
        preview = args.content[:600] + ("..." if len(args.content) > 600 else "")
        return ApprovalText(f"{'Overwrite' if args.overwrite else 'Create'} file {args.path}", args.path,
                            f"Writes {len(args.content)} characters:\n{preview}",
                            "Overwriting replaces the existing file permanently." if args.overwrite
                            else "Creates a new file.")

    async def run(self, args: WriteInput, ctx) -> ToolResult:
        return await asyncio.to_thread(self._run, args, ctx)

    def _run(self, args: WriteInput, ctx) -> ToolResult:
        path = resolve_in_roots(args.path, ctx.settings.workspace_roots)
        if is_protected(path):
            return ToolResult(False, "Refusing to write inside version-control metadata (.git etc.)",
                              error="protected")
        if path.exists() and not args.overwrite:
            return ToolResult(False, f"{args.path} exists; set overwrite=true", error="exists")
        if is_sensitive(path):
            return ToolResult(False, "Refusing to write a sensitive file name", error="sensitive")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args.content, encoding="utf-8")
        return ToolResult(True, f"Wrote {len(args.content)} chars to {rel(path, ctx.settings.workspace_roots)}",
                          {"path": rel(path, ctx.settings.workspace_roots)})


TOOLS = [FsList(), FsRead(), FsSearch(), FsProposeOrganization(), FsMove(), FsWrite()]
