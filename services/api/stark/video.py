"""Video studio: trim, merge, speed, audio, platform sizes, captions, transcription and thumbnails, on this computer.

FFmpeg comes with the desktop app (imageio-ffmpeg); elsewhere the ``STARK_FFMPEG`` setting or an ``ffmpeg`` on the
PATH is used. Speech-to-text uses whisper.cpp (pywhispercpp, MIT) with a model the owner downloads once.
Only files in the workspace's ``media/video`` folder are read and results are written next to them.
Commands are passed as argument lists (never through a shell) and file names are checked against the folder listing.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

VIDEO_DIR = "media/video"
VIDEO_TYPES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
MAX_UPLOAD = 2 * 1024 * 1024 * 1024  # streamed to disk, never held in memory
MAX_SECONDS = 15 * 60  # longest input the studio processes
MAX_MERGE = 10

# Platform presets: frame size, longest clip the platform takes.
PRESETS: dict[str, dict[str, Any]] = {
    "vertical": {"label": "Vertical 9:16 (Reels, TikTok, Shorts, Stories)", "size": (1080, 1920), "max_s": 90},
    "square": {"label": "Square 1:1 (feeds)", "size": (1080, 1080), "max_s": 140},
    "portrait": {"label": "Portrait 4:5 (Instagram, Threads, LinkedIn)", "size": (1080, 1350), "max_s": 140},
    "landscape": {"label": "Landscape 16:9 (YouTube, X, LinkedIn)", "size": (1920, 1080), "max_s": 600},
    "original": {"label": "Original size", "size": None, "max_s": MAX_SECONDS},
}
FORMATS = ("mp4", "webm", "gif")
COLOURS = {"white": "&H00FFFFFF", "yellow": "&H0000FFFF", "cyan": "&H00FFFF00"}
ALIGN = {"bottom": 2, "middle": 5, "top": 8}  # ASS numpad positions
ANIMATIONS = ("none", "fade", "pop", "karaoke")
TRANSITIONS = ("fade", "dissolve", "wipeleft", "wiperight", "slideleft", "slideup", "circleopen", "fadeblack", "zoomin")

# whisper.cpp models (ggml), downloaded on request into the data folder.
WHISPER_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"
WHISPER_MODELS = {"tiny": {"label": "Tiny · fastest · 75 MB", "mb": 75},
                  "base": {"label": "Base · good balance · 142 MB", "mb": 142},
                  "small": {"label": "Small · most accurate · 466 MB", "mb": 466}}


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


WHISPER_ERROR: dict[str, str] = {}


def whisper_available() -> bool:
    try:
        import pywhispercpp.model  # noqa: F401

        return True
    except Exception as exc:  # noqa: BLE001 - optional: not installed or no build for this computer
        WHISPER_ERROR["error"] = f"{exc.__class__.__name__}: {exc}"[:300]
        return False


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
    return {"available": True, "version": version[:120], "burn_captions": " subtitles " in out,
            "transitions": " xfade " in out, "transcribe": whisper_available()}


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


def _transcript_path(src: Path) -> Path:
    return src.with_name(src.name + ".transcript.json")


def list_files(settings) -> list[dict[str, Any]]:
    d = folder(settings)
    out = []
    for p in sorted(d.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if p.is_file() and ".part" not in p.name and (p.suffix.lower() in VIDEO_TYPES | {".gif", ".srt", ".jpg"}):
            out.append({"name": p.name, "bytes": p.stat().st_size, "kind": _kind(p), "modified": p.stat().st_mtime,
                        "transcript": _transcript_path(p).is_file()})
    return out[:300]


def _kind(p: Path) -> str:
    s = p.suffix.lower()
    return "captions" if s == ".srt" else "image" if s in (".jpg", ".gif") else "video"


def _looks_like_video(head: bytes) -> bool:
    return head[4:8] == b"ftyp" or head.startswith(b"\x1a\x45\xdf\xa3")  # MP4/MOV family or Matroska/WebM


async def save_stream(settings, chunks, name: str, max_bytes: int = MAX_UPLOAD) -> dict[str, Any]:
    """Write an upload straight to disk in chunks (never the whole file in memory); checked as it arrives."""
    stem, ext = os.path.splitext(os.path.basename(name or "video.mp4"))
    ext = ext.lower()
    if ext not in VIDEO_TYPES:
        raise VideoError("Upload an MP4, MOV, M4V, WebM or MKV video")
    safe = re.sub(r"[^\w.-]+", "-", stem)[:60].strip("-.") or "video"
    final = folder(settings) / f"{safe}-{uuid.uuid4().hex[:6]}{ext}"
    part = final.with_name(final.name + ".part")
    size, head = 0, b""
    try:
        with open(part, "wb") as fh:
            async for chunk in chunks:
                if not chunk:
                    continue
                if len(head) < 16:
                    head += chunk[:16]
                    if len(head) >= 16 and not _looks_like_video(head):
                        raise VideoError("That file is not a valid video")
                size += len(chunk)
                if size > max_bytes:
                    raise VideoError(f"The video is larger than {max_bytes // 1_048_576} MB")
                fh.write(chunk)
        if size == 0 or not _looks_like_video(head):
            raise VideoError("That file is not a valid video")
        os.replace(part, final)
    finally:
        part.unlink(missing_ok=True)
    return {"name": final.name, "bytes": size}


def save_upload(settings, data: bytes, name: str) -> dict[str, Any]:
    """Small uploads already in memory (kept for callers that have bytes)."""
    async def one():
        yield data

    return asyncio.run(save_stream(settings, one(), name))


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
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _srt_from_segments(segments: list[dict[str, Any]]) -> str:
    return "\n".join(f"{i}\n{_ts(s['start'])} --> {_ts(s['end'])}\n{s['text'].strip()}\n"
                     for i, s in enumerate(segments, 1)) + "\n"


def captions_from_script(script: str, duration: float, max_chars: int = 42) -> str:
    """SRT captions from a script: split into short lines and timed by their length over the clip.
    For captions timed to the speech, transcribe the video instead."""
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
    t, segs = 0.0, []
    for line in lines:
        span = duration * len(line) / total
        segs.append({"start": t, "end": min(duration, t + span) - 0.05, "text": line})
        t += span
    return _srt_from_segments(segs)


def check_srt(text: str) -> str:
    text = text.replace("\r\n", "\n").strip()
    if not re.search(r"\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}", text):
        raise VideoError("Captions must be in SRT format (00:00:01,000 --> 00:00:03,000)")
    if len(text) > 200_000:
        raise VideoError("Captions file too long")
    return text + "\n"


def split_lines(segments: list[dict[str, Any]], max_chars: int = 42) -> list[dict[str, Any]]:
    """Long transcript segments become short caption lines, timed in proportion to their length."""
    out = []
    for s in segments:
        words, lines, cur = s["text"].split(), [], ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > max_chars:
                lines.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            lines.append(cur)
        total, t = sum(len(x) for x in lines) or 1, s["start"]
        for line in lines:
            span = (s["end"] - s["start"]) * len(line) / total
            out.append({"start": t, "end": t + span, "text": line})
            t += span
    return out


def clip_segments(segments: list[dict[str, Any]], start: float, end: float | None) -> list[dict[str, Any]]:
    """Transcript lines inside [start, end], shifted so the clip starts at 0 (the trimmed output's time)."""
    out = []
    for s in segments:
        if s["end"] <= start or (end is not None and s["start"] >= end):
            continue
        a = max(s["start"], start) - start
        b = (min(s["end"], end) if end is not None else s["end"]) - start
        if b - a > 0.05:
            out.append({"start": a, "end": b, "text": s["text"]})
    return out


def plan_clips(segments: list[dict[str, Any]], max_s: float = 60, min_s: float = 8) -> list[dict[str, Any]]:
    """Split a talk into short clips at sentence boundaries (for Shorts, Reels, TikTok)."""
    clips: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []
    for s in segments:
        if cur and s["end"] - cur[0]["start"] > max_s:
            clips.append(cur)
            cur = []
        cur.append(s)
        if s["end"] - cur[0]["start"] >= min_s and s["text"].rstrip().endswith((".", "!", "?")):
            clips.append(cur)
            cur = []
    if cur:
        if clips and cur[-1]["end"] - cur[0]["start"] < min_s and cur[-1]["end"] - clips[-1][0]["start"] <= max_s:
            clips[-1] += cur
        else:
            clips.append(cur)
    return [{"start": round(c[0]["start"], 2), "end": round(c[-1]["end"], 2),
             "text": " ".join(x["text"].strip() for x in c)[:300]} for c in clips]


def style_string(style: dict[str, Any] | None) -> str:
    st = style or {}
    size = min(40, max(8, int(st.get("size") or 14)))
    colour = COLOURS.get(str(st.get("color") or "white"), COLOURS["white"])
    align = ALIGN.get(str(st.get("position") or "bottom"), 2)
    parts = [f"FontSize={size}", f"PrimaryColour={colour}", f"Alignment={align}", "MarginV=40", "Bold=1"]
    parts += ["BorderStyle=3", "Outline=1", "Shadow=0", "BackColour=&H80000000"] if st.get("box") \
        else ["BorderStyle=1", "Outline=2", "Shadow=0"]
    return ",".join(parts)


def parse_srt(text: str) -> list[dict[str, Any]]:
    out = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        m = re.search(r"(\d\d):(\d\d):(\d\d),(\d{3}) --> (\d\d):(\d\d):(\d\d),(\d{3})\n(.+)", block, re.S)
        if m:
            g = [int(x) for x in m.groups()[:8]]
            out.append({"start": g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000,
                        "end": g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000, "text": m.group(9).strip()})
    return out


def _ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def ass_from_segments(segments: list[dict[str, Any]], style: dict[str, Any] | None, animation: str,
                      size: tuple[int, int]) -> str:
    """Animated captions as an ASS file (libass renders it): fade, pop or word-by-word karaoke highlight."""
    st = style or {}
    w, h = size
    font = round(min(40, max(8, int(st.get("size") or 14))) * h / 288)  # same look as the SRT FontSize scale
    colour = COLOURS.get(str(st.get("color") or "white"), COLOURS["white"])
    align = ALIGN.get(str(st.get("position") or "bottom"), 2)
    box = bool(st.get("box"))
    primary, secondary = (colour, "&H00FFFFFF") if animation == "karaoke" else (colour, colour)
    if animation == "karaoke" and colour == COLOURS["white"]:
        primary = COLOURS["yellow"]  # the spoken word stands out
    head = ("[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
            f"PlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
            "MarginR, MarginV, Encoding\n"
            f"Style: Default,Arial,{font},{primary},{secondary},&H00000000,&H80000000,1,0,0,0,100,100,0,0,"
            f"{3 if box else 1},{max(1, font // 14)},0,{align},{w // 20},{w // 20},{h // 14},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lines = []
    for s in segments:
        text = re.sub(r"[{}\\]", "", s["text"]).strip()
        if not text:
            continue
        if animation == "fade":
            body = "{\\fad(150,100)}" + text
        elif animation == "pop":
            body = "{\\fscx70\\fscy70\\t(0,160,\\fscx100\\fscy100)}" + text
        elif animation == "karaoke":
            words = text.split()
            total_cs = max(len(words), int((s["end"] - s["start"]) * 100))
            chars = sum(len(x) for x in words) or 1
            parts, used = [], 0
            for i, word in enumerate(words):
                k = total_cs - used if i == len(words) - 1 else max(1, round(total_cs * len(word) / chars))
                used += k
                parts.append(f"{{\\k{k}}}{word}")
            body = " ".join(parts)
        else:
            body = text
        lines.append(f"Dialogue: 0,{_ass_time(s['start'])},{_ass_time(s['end'])},Default,,0,0,0,,{body}")
    return head + "\n".join(lines) + "\n"


# ------------------------------------------------------------------ commands
def _speed(opts: dict[str, Any]) -> float:
    return min(2.0, max(0.5, float(opts.get("speed") or 1.0)))


def build_command(exe: str, src: Path, out: Path, info: dict[str, Any], opts: dict[str, Any],
                  srt_name: str | None) -> list[str]:
    """The FFmpeg arguments for one export of one video. Pure: tested without running FFmpeg."""
    preset = PRESETS[opts["preset"]]
    speed = _speed(opts)
    start = max(0.0, float(opts.get("start") or 0))
    end = float(opts.get("end") or info["duration"])
    end = min(end, info["duration"], start + preset["max_s"] * speed)
    if end - start < 0.3:
        raise VideoError("The clip must be at least 0.3 seconds long")
    out_len = (end - start) / speed
    fmt = opts["format"]
    audio = info["audio"] and not opts.get("mute") and fmt != "gif"
    vf: list[str] = []
    if preset["size"]:
        w, h = preset["size"]
        if opts.get("fit") == "crop":  # fill the frame, cut the edges
            vf.append(f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}")
        else:  # whole picture, bars where needed
            vf.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black")
    if srt_name and opts.get("captions") == "burn":
        vf.append(f"subtitles={srt_name}" if srt_name.endswith(".ass")
                  else f"subtitles={srt_name}:force_style='{style_string(opts.get('style'))}'")
    if speed != 1.0:
        vf.append(f"setpts=PTS/{speed:g}")
    fade = min(1.0, float(opts.get("fade") or 0), out_len / 3)
    if fade > 0:
        vf.append(f"fade=t=in:st=0:d={fade:.2f},fade=t=out:st={out_len - fade:.2f}:d={fade:.2f}")
    if fmt == "gif":
        vf.append("fps=12,scale='min(720,iw)':-2:flags=lanczos")
    af: list[str] = []
    if audio:
        if speed != 1.0:
            af.append(f"atempo={speed:g}")
        vol = float(opts.get("volume") if opts.get("volume") is not None else 1.0)
        if vol != 1.0:
            af.append(f"volume={min(3.0, max(0.0, vol)):g}")
        if fade > 0:
            af.append(f"afade=t=in:st=0:d={fade:.2f},afade=t=out:st={out_len - fade:.2f}:d={fade:.2f}")
    cmd = [exe, "-hide_banner", "-y", "-nostats", "-progress", "pipe:1",
           "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src.name]
    soft = srt_name and opts.get("captions") == "track" and fmt == "mp4"
    if soft:
        cmd += ["-i", srt_name]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    if af:
        cmd += ["-af", ",".join(af)]
    if fmt == "mp4":
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        cmd += ["-c:a", "aac", "-b:a", "128k"] if audio else ["-an"]
        if soft:
            cmd += ["-map", "0:v:0"] + (["-map", "0:a:0?"] if audio else [])
            cmd += ["-map", "1:0", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng"]
    elif fmt == "webm":
        cmd += ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "33", "-row-mt", "1", "-deadline", "realtime"]
        cmd += ["-c:a", "libopus", "-b:a", "96k"] if audio else ["-an"]
    else:
        cmd += ["-an", "-loop", "0"]
    return cmd + [out.name]


def build_merge_command(exe: str, srcs: list[Path], infos: list[dict[str, Any]], out: Path,
                        opts: dict[str, Any]) -> tuple[list[str], float]:
    """Join several videos into one, each scaled to the same frame, with an optional cross-fade between them."""
    if not 2 <= len(srcs) <= MAX_MERGE:
        raise VideoError(f"Pick 2 to {MAX_MERGE} videos to join")
    preset = PRESETS[opts["preset"]]
    w, h = preset["size"] or (infos[0]["width"] - infos[0]["width"] % 2, infos[0]["height"] - infos[0]["height"] % 2)
    audio = all(i["audio"] for i in infos) and not opts.get("mute") and opts["format"] != "gif"
    fade = min(1.5, max(0.0, float(opts.get("transition") or 0)))
    if fade and any(i["duration"] <= fade * 2 for i in infos):
        raise VideoError("Each video must be longer than twice the transition")
    fit = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}" if opts.get("fit") == "crop"
           else f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black")
    parts = [f"[{i}:v]{fit},setsar=1,fps=30,format=yuv420p[v{i}]" for i in range(len(srcs))]
    if audio:
        parts += [f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]" for i in range(len(srcs))]
    total = sum(i["duration"] for i in infos)
    if fade:
        offset, vprev, aprev = 0.0, "[v0]", "[a0]"
        for i in range(1, len(srcs)):
            offset += infos[i - 1]["duration"] - fade
            kind = opts.get("transition_type") if opts.get("transition_type") in TRANSITIONS else "fade"
            parts.append(f"{vprev}[v{i}]xfade=transition={kind}:duration={fade:.2f}:offset={offset:.3f}[x{i}]")
            vprev = f"[x{i}]"
            if audio:
                parts.append(f"{aprev}[a{i}]acrossfade=d={fade:.2f}[y{i}]")
                aprev = f"[y{i}]"
        total -= fade * (len(srcs) - 1)
        vout, aout = vprev, aprev
    else:
        ins = "".join(f"[v{i}]" + (f"[a{i}]" if audio else "") for i in range(len(srcs)))
        parts.append(f"{ins}concat=n={len(srcs)}:v=1:a={1 if audio else 0}[vc]" + ("[ac]" if audio else ""))
        vout, aout = "[vc]", "[ac]"
    if opts["format"] == "gif":
        parts.append(f"{vout}fps=12,scale='min(720,iw)':-2:flags=lanczos[vg]")
        vout = "[vg]"
    cmd = [exe, "-hide_banner", "-y", "-nostats", "-progress", "pipe:1"]
    for s in srcs:
        cmd += ["-i", s.name]
    cmd += ["-filter_complex", ";".join(parts), "-map", vout] + (["-map", aout] if audio else [])
    if opts["format"] == "mp4":
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        cmd += ["-c:a", "aac", "-b:a", "128k"] if audio else ["-an"]
    elif opts["format"] == "webm":
        cmd += ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "33", "-row-mt", "1", "-deadline", "realtime"]
        cmd += ["-c:a", "libopus", "-b:a", "96k"] if audio else ["-an"]
    else:
        cmd += ["-an", "-loop", "0"]
    return cmd + [out.name], total


# ------------------------------------------------------------------ speech to text
def models_dir(settings) -> Path:
    d = Path(settings.data_dir) / "models" / "whisper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def model_file(settings, name: str) -> Path:
    return models_dir(settings) / f"ggml-{name}.bin"


def models_status(settings) -> list[dict[str, Any]]:
    return [{"name": n, **m, "installed": model_file(settings, n).is_file()} for n, m in WHISPER_MODELS.items()]


def decode_audio(exe: str, src: Path):
    """16 kHz mono float samples for whisper, decoded by FFmpeg."""
    import numpy as np

    r = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
                        "-f", "f32le", "pipe:1"], capture_output=True, timeout=600)
    if r.returncode != 0:
        raise VideoError("Could not read the sound: " + r.stderr.decode("utf-8", "replace")[-200:])
    if not r.stdout:
        raise VideoError("This video has no sound to transcribe")
    return np.frombuffer(r.stdout, dtype=np.float32)


def transcribe_audio(model_path: Path, samples, language: str = "auto",
                     on_segment: Callable[[float], None] | None = None,
                     should_stop: Callable[[], bool] | None = None) -> list[dict[str, Any]]:
    """Speech to text with timestamps (whisper.cpp). Times are seconds."""
    from pywhispercpp.model import Model

    params: dict[str, Any] = {"print_progress": False, "print_realtime": False}
    if language and language != "auto":
        params["language"] = language
    else:
        params["language"] = "auto"
    model = Model(str(model_path), **params)

    def cb(seg) -> None:
        if on_segment:
            on_segment(seg.t1 / 100)
    import inspect

    kwargs: dict[str, Any] = {"new_segment_callback": cb}
    if should_stop and "abort_callback" in inspect.signature(model.transcribe).parameters:
        kwargs["abort_callback"] = should_stop  # newer whisper.cpp builds stop mid-run
    segs = model.transcribe(samples, **kwargs)
    if should_stop and should_stop():
        raise VideoError("cancelled")
    return [{"start": round(s.t0 / 100, 2), "end": round(s.t1 / 100, 2), "text": s.text.strip()}
            for s in segs if s.text.strip() and not re.fullmatch(r"\[.*\]|\(.*\)", s.text.strip())]


# ------------------------------------------------------------------ jobs
class Studio:
    """Runs exports one at a time in the background with progress, cancellation and recovery after a restart."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.jobs: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._procs: dict[str, asyncio.subprocess.Process] = {}
        self._cleanup()

    def _cleanup(self) -> None:
        """Half-written files from an export or upload that was interrupted (crash, quit) are removed."""
        try:
            for p in folder(self.settings).iterdir():
                if p.name.endswith(".part") or ".part." in p.name:
                    p.unlink(missing_ok=True)
        except (OSError, VideoError):
            pass

    def list_jobs(self) -> list[dict[str, Any]]:
        jobs = sorted(self.jobs.values(), key=lambda j: j["created"], reverse=True)[:40]
        return [{k: v for k, v in j.items() if k != "abort"} for j in jobs]

    def _new_job(self, kind: str, **kw: Any) -> dict[str, Any]:
        job = {"id": uuid.uuid4().hex[:10], "kind": kind, "status": "queued", "progress": 0.0, "created": time.time(),
               "error": None, "output": None, "captions": None, **kw}
        self.jobs[job["id"]] = job
        return job

    def _exe(self) -> str:
        exe = ffmpeg_path()
        if not exe:
            raise VideoError(status()["message"])
        return exe

    def _captions(self, src: Path, opts: dict[str, Any], start: float, end: float) -> Path | None:
        mode = opts.get("captions")
        if mode not in ("burn", "track", "file"):
            return None
        if (opts.get("srt") or "").strip():
            text = check_srt(opts["srt"])
        elif opts.get("caption_source") == "transcript":
            tp = _transcript_path(src)
            if not tp.is_file():
                raise VideoError("Transcribe this video first, or write a script")
            segs = clip_segments(split_lines(json.loads(tp.read_text(encoding="utf-8"))["segments"]), start, end)
            if not segs:
                raise VideoError("Nothing is said in this part of the video")
            text = _srt_from_segments(segs)
        else:
            text = captions_from_script(str(opts.get("script") or ""), end - start)
        srt = src.with_name(f"{src.stem}-captions-{uuid.uuid4().hex[:4]}.srt")
        srt.write_text(text, encoding="utf-8")
        animation = opts.get("animation") if opts.get("animation") in ANIMATIONS else "none"
        if mode == "burn" and animation != "none":
            size = PRESETS[opts["preset"]]["size"] or self._size(src)
            ass = srt.with_suffix(".ass")
            ass.write_text(ass_from_segments(parse_srt(text), opts.get("style"), animation, size), encoding="utf-8")
            return ass  # the .srt stays next to it for platforms that take a captions file
        return srt

    def _size(self, src: Path) -> tuple[int, int]:
        info = probe(self._exe(), src)
        return info["width"], info["height"]

    def start(self, opts: dict[str, Any]) -> dict[str, Any]:
        """One export, or one per preset in ``opts['presets']`` (batch)."""
        presets = opts.get("presets") or [opts.get("preset")]
        if not presets or any(p not in PRESETS for p in presets) or opts.get("format") not in FORMATS:
            raise VideoError("Unknown size or format")
        if len(presets) > 5:
            raise VideoError("Up to 5 sizes at once")
        jobs = [self._start_one({**opts, "preset": p}) for p in dict.fromkeys(presets)]
        return jobs[0] if len(jobs) == 1 else {"jobs": jobs}

    def _start_one(self, opts: dict[str, Any]) -> dict[str, Any]:
        exe = self._exe()
        files = opts.get("files") or []
        if len(files) >= 2:
            srcs = [_find(self.settings, str(f)) for f in files]
            infos = [probe(exe, s) for s in srcs]
            if sum(i["duration"] for i in infos) > MAX_SECONDS:
                raise VideoError("Joined videos can be up to 15 minutes")
            out = srcs[0].with_name(f"{srcs[0].stem}-joined-{opts['preset']}-{uuid.uuid4().hex[:4]}.{opts['format']}")
            cmd, total = build_merge_command(exe, srcs, infos, out, opts)
            job = self._new_job("merge", file=", ".join(s.name for s in srcs), output=out.name,
                                preset=opts["preset"], format=opts["format"], duration=total)
        else:
            src = _find(self.settings, str(opts.get("file") or (files[0] if files else "")))
            if src.suffix.lower() not in VIDEO_TYPES:
                raise VideoError("Pick a video file")
            info = probe(exe, src)
            if info["duration"] > MAX_SECONDS:
                raise VideoError("Videos up to 15 minutes can be edited here")
            start = max(0.0, float(opts.get("start") or 0))
            end = min(float(opts.get("end") or info["duration"]), info["duration"])
            srt = self._captions(src, opts, start, end)
            out = src.with_name(f"{src.stem}-{opts['preset']}-{uuid.uuid4().hex[:4]}.{opts['format']}")
            cmd = build_command(exe, src, out, info, opts, srt.name if srt and opts["captions"] != "file" else None)
            total = (min(end, start + PRESETS[opts["preset"]]["max_s"] * _speed(opts)) - start) / _speed(opts)
            job = self._new_job("export", file=src.name, output=out.name, captions=srt.name if srt else None,
                                preset=opts["preset"], format=opts["format"], duration=total)
        asyncio.get_running_loop().create_task(self._run(job, cmd, out))
        return job

    async def _run(self, job: dict[str, Any], cmd: list[str], out: Path) -> None:
        async with self._lock:
            if job["status"] == "cancelled":
                return
            job["status"] = "running"
            tmp = out.with_name(out.name + ".part" + out.suffix)  # FFmpeg needs the real extension at the end
            cmd = cmd[:-1] + [tmp.name]
            proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(out.parent), stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.PIPE)
            self._procs[job["id"]] = proc
            err_tail: list[str] = []

            async def read_err() -> None:
                assert proc.stderr is not None
                async for line in proc.stderr:
                    err_tail.append(line.decode("utf-8", "replace").strip())
                    del err_tail[:-6]

            async def read_progress() -> None:
                assert proc.stdout is not None
                async for line in proc.stdout:
                    m = re.match(rb"out_time_(?:us|ms)=(\d+)", line)
                    if m and job.get("duration"):
                        job["progress"] = min(0.99, int(m.group(1)) / 1_000_000 / job["duration"])
            try:
                await asyncio.wait_for(asyncio.gather(read_err(), read_progress(), proc.wait()), timeout=60 * 60)
            except asyncio.TimeoutError:
                proc.kill()
                job.update(status="failed", error="Took longer than an hour")
            finally:
                self._procs.pop(job["id"], None)
            if job["status"] == "cancelled":
                tmp.unlink(missing_ok=True)
            elif job["status"] != "failed" and proc.returncode == 0 and tmp.is_file():
                os.replace(tmp, out)
                job.update(status="done", progress=1.0, bytes=out.stat().st_size)
            else:
                tmp.unlink(missing_ok=True)
                if job["status"] != "failed":
                    msg = " ".join(x for x in err_tail if x and not x.startswith("frame="))[-400:]
                    job.update(status="failed", error=msg or "FFmpeg failed")

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if job is None or job["status"] not in ("queued", "running"):
            return False
        job["status"] = "cancelled"
        proc = self._procs.get(job_id)
        if proc is not None and proc.returncode is None:
            proc.kill()
        if job.get("abort") is not None:
            job["abort"].set()
        return True

    # -- transcription
    def transcribe(self, name: str, model: str, language: str = "auto") -> dict[str, Any]:
        if model not in WHISPER_MODELS:
            raise VideoError("Unknown speech model")
        if not whisper_available():
            raise VideoError("Speech-to-text is not available on this computer")
        mpath = model_file(self.settings, model)
        if not mpath.is_file():
            raise VideoError("Download the speech model first")
        exe = self._exe()
        src = _find(self.settings, name)
        info = probe(exe, src)
        if not info["audio"]:
            raise VideoError("This video has no sound to transcribe")
        job = self._new_job("transcribe", file=src.name, duration=info["duration"], model=model)
        job["abort"] = threading.Event()
        asyncio.get_running_loop().create_task(self._run_transcribe(job, exe, src, mpath, language))
        return job

    async def _run_transcribe(self, job, exe, src: Path, mpath: Path, language: str) -> None:
        async with self._lock:
            if job["status"] == "cancelled":
                return
            job["status"] = "running"

            def progress(t: float) -> None:
                job["progress"] = min(0.99, t / (job["duration"] or 1))
            try:
                samples = await asyncio.to_thread(decode_audio, exe, src)
                segs = await asyncio.to_thread(transcribe_audio, mpath, samples, language, progress,
                                               job["abort"].is_set)
                del samples  # free the audio right away
            except Exception as exc:  # noqa: BLE001 - reported on the job
                if job["status"] != "cancelled":
                    job.update(status="failed", error=str(exc)[:300])
                return
            if job["status"] == "cancelled":  # whisper.cpp can't be stopped mid-run; the result is dropped
                return
            _transcript_path(src).write_text(json.dumps({"model": job["model"], "segments": segs}), encoding="utf-8")
            srt = src.with_name(f"{src.stem}-transcript.srt")
            srt.write_text(_srt_from_segments(split_lines(segs)), encoding="utf-8")
            job.update(status="done", progress=1.0, captions=srt.name, segments=len(segs))

    def transcript(self, name: str) -> dict[str, Any]:
        src = _find(self.settings, name)
        tp = _transcript_path(src)
        if not tp.is_file():
            raise VideoError("This video has not been transcribed yet")
        data = json.loads(tp.read_text(encoding="utf-8"))
        return {"file": src.name, "segments": data["segments"], "clips": plan_clips(data["segments"]),
                "text": " ".join(s["text"] for s in data["segments"])}

    # -- models
    def download_model(self, name: str, transport=None) -> dict[str, Any]:
        if name not in WHISPER_MODELS:
            raise VideoError("Unknown speech model")
        if any(j["kind"] == "model" and j["status"] in ("queued", "running") for j in self.jobs.values()):
            raise VideoError("A model is already downloading")
        job = self._new_job("model", file=f"ggml-{name}.bin", model=name, output=None)
        job["abort"] = threading.Event()
        asyncio.get_running_loop().create_task(self._download(job, name, transport))
        return {k: v for k, v in job.items() if k != "abort"}

    async def _download(self, job, name: str, transport) -> None:
        import httpx

        dest = model_file(self.settings, name)
        part = dest.with_name(dest.name + ".part")
        job["status"] = "running"
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True, transport=transport) as c:
                async with c.stream("GET", WHISPER_URL.format(name=name)) as r:
                    if r.status_code != 200:
                        raise VideoError(f"Download failed (HTTP {r.status_code})")
                    total = int(r.headers.get("content-length") or WHISPER_MODELS[name]["mb"] * 1_048_576)
                    got = 0
                    with open(part, "wb") as fh:
                        async for chunk in r.aiter_bytes(1 << 20):
                            if job["abort"].is_set():
                                raise VideoError("cancelled")
                            fh.write(chunk)
                            got += len(chunk)
                            job["progress"] = min(0.99, got / total)
            with open(part, "rb") as fh:
                magic = fh.read(4)
            if magic not in (b"lmgg", b"ggml", b"GGUF") or part.stat().st_size < 10_000_000:
                raise VideoError("The downloaded file is not a speech model")
            os.replace(part, dest)
            job.update(status="done", progress=1.0, output=dest.name)
        except Exception as exc:  # noqa: BLE001
            part.unlink(missing_ok=True)
            if job["status"] != "cancelled":
                job.update(status="failed", error=str(exc)[:300])

    # -- frames and files
    async def thumbnail(self, name: str, at: float) -> dict[str, Any]:
        """A JPEG frame from the video, saved to the media library so it can be attached to posts."""
        exe = self._exe()
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

    async def preview(self, name: str, at: float) -> bytes:
        """A small JPEG frame for the timeline (not saved)."""
        exe = self._exe()
        src = _find(self.settings, name)
        proc = await asyncio.create_subprocess_exec(
            exe, "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, at):.3f}", "-i", str(src), "-frames:v", "1",
            "-vf", "scale=320:-2", "-q:v", "6", "-f", "image2", "-c:v", "mjpeg", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        data, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0 or not data:
            raise VideoError("Could not read a frame here")
        return data

    def info(self, name: str) -> dict[str, Any]:
        return probe(self._exe(), _find(self.settings, name))

    def path(self, name: str) -> Path:
        return _find(self.settings, name)

    def delete(self, name: str) -> None:
        p = _find(self.settings, name)
        p.unlink()
        _transcript_path(p).unlink(missing_ok=True)
        p.with_name(p.name + ".packages.json").unlink(missing_ok=True)


def self_check(exe: str, workdir: Path) -> dict[str, Any]:
    """Used by the desktop self-test: make a clip, burn a caption into it, read it back."""
    out = workdir / "check.mp4"
    r = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10",
                        "-t", "1", "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
                        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return {"ok": False, "error": "FFmpeg failed: " + r.stderr[-300:]}
    info = probe(exe, out)
    if (info["width"], info["height"]) != (1080, 1920):
        return {"ok": False, "error": f"unexpected size {info}"}
    (workdir / "c.srt").write_text("1\n00:00:00,000 --> 00:00:00,900\nHello\n", encoding="utf-8")
    burn = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-i", "check.mp4", "-vf",
                           f"subtitles=c.srt:force_style='{style_string(None)}'", "-c:v", "libx264", "burn.mp4"],
                          cwd=str(workdir), capture_output=True, text=True, timeout=120)
    return {"ok": True, "burn_captions": burn.returncode == 0 and (workdir / "burn.mp4").is_file(),
            "burn_error": burn.stderr[-200:] if burn.returncode else "", "transcribe": whisper_available(),
            "transcribe_error": WHISPER_ERROR.get("error", "")}
