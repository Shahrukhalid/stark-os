"""Video studio: trim, resize for each platform, convert, captions and thumbnails, all on this computer with FFmpeg.

FFmpeg comes with the desktop app (imageio-ffmpeg); elsewhere the ``STARK_FFMPEG`` setting or an ``ffmpeg`` on the
PATH is used. Only files in the workspace's ``media/video`` folder are read and results are written next to them.
Commands are passed as argument lists (never through a shell) and file names are checked against the folder listing.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

VIDEO_DIR = "media/video"
VIDEO_TYPES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
MAX_UPLOAD = 500 * 1024 * 1024
MAX_SECONDS = 15 * 60  # longest input the studio processes
NAME_RE = re.compile(r"^[\w][\w .()-]{0,120}$")

# Platform presets: frame size, longest clip the platform takes, container.
PRESETS: dict[str, dict[str, Any]] = {
    "vertical": {"label": "Vertical 9:16 (Reels, TikTok, Shorts, Stories)", "size": (1080, 1920), "max_s": 90},
    "square": {"label": "Square 1:1 (feeds)", "size": (1080, 1080), "max_s": 140},
    "portrait": {"label": "Portrait 4:5 (Instagram, Threads, LinkedIn)", "size": (1080, 1350), "max_s": 140},
    "landscape": {"label": "Landscape 16:9 (YouTube, X, LinkedIn)", "size": (1920, 1080), "max_s": 600},
    "original": {"label": "Original size", "size": None, "max_s": MAX_SECONDS},
}
FORMATS = ("mp4", "webm", "gif")


class VideoError(ValueError):
    pass


# ------------------------------------------------------------------ ffmpeg
def ffmpeg_path() -> str | None:
    env = os.environ.get("STARK_FFMPEG")
    if env and Path(env).is_file():
        return env
    try:
        import imageio_ffmpeg  # bundled with the desktop app

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - not installed / no binary for this platform
        return shutil.which("ffmpeg")


def status() -> dict[str, Any]:
    exe = ffmpeg_path()
    if not exe:
        return {"available": False, "message": "FFmpeg was not found. The desktop app includes it; for a source "
                                               "install add ffmpeg to your PATH or set STARK_FFMPEG."}
    try:
        out = subprocess.run([exe, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=20).stdout
        version = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=20).stdout.split("\n")[0]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "message": f"FFmpeg could not run: {exc}"}
    return {"available": True, "version": version[:120], "burn_captions": " subtitles " in out}


def folder(settings) -> Path:
    if not settings.workspace_roots:
        raise VideoError("No workspace folder is set up")
    d = settings.workspace_roots[0] / VIDEO_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find(settings, name: str) -> Path:
    """A file in the video folder, picked from the listing (never a path built from input)."""
    found = next((p for p in folder(settings).iterdir() if p.is_file() and p.name == name), None)
    if found is None:
        raise VideoError(f"{name} is not in the video folder")
    return found


def list_files(settings) -> list[dict[str, Any]]:
    d = folder(settings)
    out = []
    for p in sorted(d.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if p.is_file() and (p.suffix.lower() in VIDEO_TYPES | {".gif", ".srt", ".jpg"}):
            out.append({"name": p.name, "bytes": p.stat().st_size, "kind": _kind(p), "modified": p.stat().st_mtime})
    return out[:300]


def _kind(p: Path) -> str:
    s = p.suffix.lower()
    return "captions" if s == ".srt" else "image" if s in (".jpg", ".gif") else "video"


def save_upload(settings, data: bytes, name: str) -> dict[str, Any]:
    stem, ext = os.path.splitext(os.path.basename(name or "video.mp4"))
    ext = ext.lower()
    if ext not in VIDEO_TYPES:
        raise VideoError("Upload an MP4, MOV, M4V, WebM or MKV video")
    if not data or len(data) > MAX_UPLOAD:
        raise VideoError("The video must be between 1 byte and 500 MB")
    head = data[:16]
    if not (head[4:8] == b"ftyp" or head.startswith(b"\x1a\x45\xdf\xa3")):  # MP4/MOV family or Matroska/WebM
        raise VideoError("That file is not a valid video")
    safe = re.sub(r"[^\w.-]+", "-", stem)[:60].strip("-.") or "video"
    path = folder(settings) / f"{safe}-{uuid.uuid4().hex[:6]}{ext}"
    path.write_bytes(data)
    return {"name": path.name, "bytes": len(data)}


def probe(exe: str, path: Path) -> dict[str, Any]:
    """Duration and frame size from FFmpeg's own report (no extra tools needed)."""
    r = subprocess.run([exe, "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=30)
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    size = re.search(r"Video: .*?(\d{2,5})x(\d{2,5})", r.stderr)
    if not m or not size:
        raise VideoError("FFmpeg could not read this video")
    secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return {"duration": round(secs, 2), "width": int(size.group(1)), "height": int(size.group(2)),
            "audio": "Audio:" in r.stderr}


# ------------------------------------------------------------------ captions
def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def captions_from_script(script: str, duration: float, max_chars: int = 42) -> str:
    """SRT captions from a script: split into short lines and timed by their length over the clip.
    Real timing from speech needs a speech model; this gives evenly paced captions for a known script."""
    words = script.split()
    if not words or duration <= 0:
        raise VideoError("Captions need a script and a clip with a length")
    lines, cur = [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
        if cur.endswith((".", "!", "?")) and len(cur) > max_chars // 2:
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    total = sum(len(x) for x in lines)
    t, out = 0.0, []
    for i, line in enumerate(lines, 1):
        span = duration * len(line) / total
        out.append(f"{i}\n{_ts(t)} --> {_ts(min(duration, t + span) - 0.05)}\n{line}\n")
        t += span
    return "\n".join(out)


def check_srt(text: str) -> str:
    text = text.replace("\r\n", "\n").strip()
    if not re.search(r"\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}", text):
        raise VideoError("Captions must be in SRT format (00:00:01,000 --> 00:00:03,000)")
    if len(text) > 200_000:
        raise VideoError("Captions file too long")
    return text + "\n"


# ------------------------------------------------------------------ jobs
def build_command(exe: str, src: Path, out: Path, info: dict[str, Any], opts: dict[str, Any],
                  srt_name: str | None) -> list[str]:
    """The FFmpeg arguments for one export. Pure: tested without running FFmpeg."""
    preset = PRESETS[opts["preset"]]
    start = max(0.0, float(opts.get("start") or 0))
    end = float(opts.get("end") or info["duration"])
    end = min(end, info["duration"], start + preset["max_s"])
    if end - start < 0.3:
        raise VideoError("The clip must be at least 0.3 seconds long")
    fmt = opts["format"]
    vf: list[str] = []
    if preset["size"]:
        w, h = preset["size"]
        if opts.get("fit") == "crop":  # fill the frame, cut the edges
            vf.append(f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}")
        else:  # whole picture, bars where needed
            vf.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black")
    if srt_name and opts.get("captions") == "burn":
        vf.append(f"subtitles={srt_name}:force_style='FontSize=14,Outline=2,MarginV=40'")
    if fmt == "gif":
        vf.append("fps=12,scale='min(720,iw)':-2:flags=lanczos")
    cmd = [exe, "-hide_banner", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src.name]
    soft = srt_name and opts.get("captions") == "track" and fmt == "mp4"
    if soft:
        cmd += ["-i", srt_name]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    if fmt == "mp4":
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        cmd += ["-an"] if opts.get("mute") or not info["audio"] else ["-c:a", "aac", "-b:a", "128k"]
        if soft:
            cmd += ["-map", "0:v:0"] + ([] if opts.get("mute") or not info["audio"] else ["-map", "0:a:0?"])
            cmd += ["-map", "1:0", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng"]
    elif fmt == "webm":
        cmd += ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "33", "-row-mt", "1", "-deadline", "realtime"]
        cmd += ["-an"] if opts.get("mute") or not info["audio"] else ["-c:a", "libopus", "-b:a", "96k"]
    else:
        cmd += ["-an", "-loop", "0"]
    return cmd + [out.name]


class Studio:
    """Runs exports one at a time in the background and keeps their status for the dashboard."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.jobs: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def list_jobs(self) -> list[dict[str, Any]]:
        return sorted(self.jobs.values(), key=lambda j: j["created"], reverse=True)[:30]

    def start(self, opts: dict[str, Any]) -> dict[str, Any]:
        exe = ffmpeg_path()
        if not exe:
            raise VideoError(status()["message"])
        if opts.get("preset") not in PRESETS or opts.get("format") not in FORMATS:
            raise VideoError("Unknown size or format")
        src = _find(self.settings, str(opts.get("file") or ""))
        if src.suffix.lower() not in VIDEO_TYPES:
            raise VideoError("Pick a video file")
        info = probe(exe, src)
        if info["duration"] > MAX_SECONDS:
            raise VideoError("Videos up to 15 minutes can be edited here")
        srt = None
        if opts.get("captions") in ("burn", "track", "file"):
            text = check_srt(opts["srt"]) if (opts.get("srt") or "").strip() else \
                captions_from_script(str(opts.get("script") or ""), (float(opts.get("end") or info["duration"])
                                                                      - float(opts.get("start") or 0)))
            srt = src.with_name(f"{src.stem}-captions-{uuid.uuid4().hex[:4]}.srt")
            srt.write_text(text, encoding="utf-8")
        out = src.with_name(f"{src.stem}-{opts['preset']}-{uuid.uuid4().hex[:4]}.{opts['format']}")
        cmd = build_command(exe, src, out, info, opts, srt.name if srt and opts["captions"] != "file" else None)
        job = {"id": uuid.uuid4().hex[:10], "status": "queued", "file": src.name, "output": out.name,
               "captions": srt.name if srt else None, "created": time.time(), "error": None,
               "preset": opts["preset"], "format": opts["format"]}
        self.jobs[job["id"]] = job
        asyncio.get_running_loop().create_task(self._run(job, cmd, out))
        return job

    async def _run(self, job: dict[str, Any], cmd: list[str], out: Path) -> None:
        async with self._lock:
            job["status"] = "running"
            proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(out.parent), stdout=asyncio.subprocess.DEVNULL,
                                                        stderr=asyncio.subprocess.PIPE)
            try:
                _, err = await asyncio.wait_for(proc.communicate(), timeout=30 * 60)
            except asyncio.TimeoutError:
                proc.kill()
                job.update(status="failed", error="Took longer than 30 minutes")
                return
            if proc.returncode == 0 and out.is_file():
                job.update(status="done", bytes=out.stat().st_size)
            else:
                tail = (err or b"").decode("utf-8", "replace").strip().splitlines()[-3:]
                job.update(status="failed", error=" ".join(tail)[:400] or "FFmpeg failed")
                out.unlink(missing_ok=True)

    async def thumbnail(self, name: str, at: float) -> dict[str, Any]:
        """A JPEG frame from the video, saved to the media library so it can be attached to posts."""
        exe = ffmpeg_path()
        if not exe:
            raise VideoError(status()["message"])
        src = _find(self.settings, name)
        info = probe(exe, src)
        at = min(max(0.0, at), max(0.0, info["duration"] - 0.1))
        lib = self.settings.workspace_roots[0] / "media" / "generated"
        lib.mkdir(parents=True, exist_ok=True)
        out = lib / f"{src.stem}-thumb-{uuid.uuid4().hex[:4]}.jpg"
        proc = await asyncio.create_subprocess_exec(
            exe, "-hide_banner", "-y", "-ss", f"{at:.3f}", "-i", str(src), "-frames:v", "1",
            "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(out),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0 or not out.is_file():
            raise VideoError("Could not take a frame: " + (err or b"").decode("utf-8", "replace")[-200:])
        return {"file": f"media/generated/{out.name}", "name": out.name, "at": at}

    def path(self, name: str) -> Path:
        return _find(self.settings, name)
