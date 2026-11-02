"use client";

import { Clapperboard, Download, Image as ImageIcon, LoaderCircle, Trash2, Upload } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import { Section } from "./ui";

type VFile = { name: string; bytes: number; kind: "video" | "image" | "captions" };
type Job = { id: string; status: "queued" | "running" | "done" | "failed"; file: string; output: string; captions: string | null; error: string | null; preset: string; format: string };
type Home = { ffmpeg: { available: boolean; message?: string; version?: string; burn_captions?: boolean }; files: VFile[]; jobs: Job[]; presets: Record<string, { label: string }>; formats: string[] };

const mb = (n: number) => `${(n / 1048576).toFixed(1)} MB`;

/** Trim, resize for each platform, convert, add captions and grab thumbnails, all on this computer. */
export function VideoStudio({ talkTo }: { talkTo: (agentId: string, text?: string) => void }) {
  const { client, notify } = useStark();
  const [home, setHome] = useState<Home | null>(null);
  const [busy, setBusy] = useState("");
  const [o, setO] = useState({ file: "", preset: "vertical", format: "mp4", fit: "pad", start: "", end: "", mute: false, captions: "none", script: "", srt: "" });
  const set = (k: keyof typeof o, v: any) => setO((x) => ({ ...x, [k]: v }));

  const load = useCallback(() => {
    client.get<Home>("/api/video").then((h) => {
      setHome(h);
      setO((x) => (x.file || !h.files.find((f) => f.kind === "video") ? x : { ...x, file: h.files.find((f) => f.kind === "video")!.name }));
    }).catch((e) => notify("error", e.message));
  }, [client, notify]);
  useEffect(load, [load]);
  const running = home?.jobs.some((j) => j.status === "queued" || j.status === "running");
  useEffect(() => {
    if (!running) return;
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [running, load]);

  async function upload(f: File) {
    setBusy("upload");
    try {
      const r = await client.upload<{ name: string }>(`/api/video/upload?name=${encodeURIComponent(f.name)}`, f);
      set("file", r.name);
      notify("success", "Video added");
      load();
    } catch (e: any) {
      notify("error", e.message);
    } finally {
      setBusy("");
    }
  }

  async function exportVideo() {
    setBusy("export");
    try {
      await client.post("/api/video/export", { ...o, start: o.start ? Number(o.start) : null, end: o.end ? Number(o.end) : null, script: o.script || null, srt: o.srt || null });
      load();
    } catch (e: any) {
      notify("error", e.message);
    } finally {
      setBusy("");
    }
  }

  async function thumbnail() {
    setBusy("thumb");
    try {
      const r = await client.post<{ file: string }>("/api/video/thumbnail", { file: o.file, at: Number(o.start || 1) });
      notify("success", `Thumbnail saved to your media library (${r.file})`);
    } catch (e: any) {
      notify("error", e.message);
    } finally {
      setBusy("");
    }
  }

  async function download(name: string) {
    try {
      const url = URL.createObjectURL(await client.blob(`/api/video/file?name=${encodeURIComponent(name)}`));
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (e: any) {
      notify("error", e.message);
    }
  }

  if (!home) return null;
  const videos = home.files.filter((f) => f.kind === "video");
  return (
    <Section title="Video studio" right={<Clapperboard size={15} className="text-cyan-300" />}>
      {!home.ffmpeg.available ? (
        <p className="text-sm text-amber-300">{home.ffmpeg.message}</p>
      ) : (
        <div className="grid gap-4 [&>*]:min-w-0 lg:grid-cols-[1.2fr_1fr]">
          <div className="space-y-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <select aria-label="Video" className="input !w-auto min-w-0 flex-1" value={o.file} onChange={(e) => set("file", e.target.value)}>
                {videos.length === 0 && <option value="">Add a video first</option>}
                {videos.map((f) => <option key={f.name} value={f.name}>{f.name} · {mb(f.bytes)}</option>)}
              </select>
              <label className="btn cursor-pointer">
                {busy === "upload" ? <LoaderCircle size={13} className="animate-spin" /> : <Upload size={13} />} Add video
                <input type="file" accept="video/mp4,video/quicktime,video/webm,video/x-matroska,.m4v" className="sr-only" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
              </label>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <label><span className="hud-label text-[var(--color-mute)]">Size</span>
                <select className="input mt-1 w-full" value={o.preset} onChange={(e) => set("preset", e.target.value)}>
                  {Object.entries(home.presets).map(([id, p]) => <option key={id} value={id}>{p.label}</option>)}
                </select>
              </label>
              <label><span className="hud-label text-[var(--color-mute)]">Format</span>
                <select className="input mt-1 w-full" value={o.format} onChange={(e) => set("format", e.target.value)}>
                  {home.formats.map((f) => <option key={f} value={f}>{f.toUpperCase()}</option>)}
                </select>
              </label>
              <label><span className="hud-label text-[var(--color-mute)]">Start (seconds)</span>
                <input className="input mt-1 w-full" type="number" min={0} step={0.1} value={o.start} onChange={(e) => set("start", e.target.value)} placeholder="0" />
              </label>
              <label><span className="hud-label text-[var(--color-mute)]">End (seconds)</span>
                <input className="input mt-1 w-full" type="number" min={0} step={0.1} value={o.end} onChange={(e) => set("end", e.target.value)} placeholder="end of video" />
              </label>
              <label><span className="hud-label text-[var(--color-mute)]">Fit</span>
                <select className="input mt-1 w-full" value={o.fit} onChange={(e) => set("fit", e.target.value)}>
                  <option value="pad">Whole picture (bars)</option>
                  <option value="crop">Fill the frame (crop edges)</option>
                </select>
              </label>
              <label><span className="hud-label text-[var(--color-mute)]">Captions</span>
                <select className="input mt-1 w-full" value={o.captions} onChange={(e) => set("captions", e.target.value)}>
                  <option value="none">None</option>
                  {home.ffmpeg.burn_captions && <option value="burn">Burned into the picture</option>}
                  <option value="track">Caption track (MP4, viewers can switch it off)</option>
                  <option value="file">Separate .srt file only</option>
                </select>
              </label>
            </div>
            {o.captions !== "none" && (
              <div className="space-y-2">
                <textarea className="input w-full" rows={3} value={o.script} onChange={(e) => set("script", e.target.value)} placeholder="Script (captions are timed evenly over the clip)" />
                <textarea className="input w-full font-mono text-xs" rows={2} value={o.srt} onChange={(e) => set("srt", e.target.value)} placeholder="…or paste exact SRT captions (used instead of the script)" />
                <button className="btn text-xs" type="button" onClick={() => talkTo("u", "U, write a short spoken script with captions for this video: ")}>Ask U for a script</button>
              </div>
            )}
            <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={o.mute} onChange={(e) => set("mute", e.target.checked)} /> Remove sound</label>
            <div className="flex flex-wrap gap-2">
              <button className="btn btn-primary" disabled={!o.file || busy === "export"} onClick={exportVideo}>
                {busy === "export" ? <LoaderCircle size={13} className="animate-spin" /> : <Clapperboard size={13} />} Export
              </button>
              <button className="btn" disabled={!o.file || busy === "thumb"} onClick={thumbnail} title="Saves the frame at the start time to your media library">
                <ImageIcon size={13} /> Thumbnail at start time
              </button>
            </div>
            <p className="text-xs text-[var(--color-mute)]">Runs on this computer with FFmpeg. Clips are capped at each platform&apos;s length (vertical 90 s).</p>
          </div>
          <div className="space-y-2 text-xs">
            <div className="hud-label text-[var(--color-mute)]">Exports</div>
            {home.jobs.length === 0 && <p className="text-[var(--color-mute)]">Nothing exported yet.</p>}
            {home.jobs.map((j) => (
              <div key={j.id} className="rounded-lg border border-[var(--color-line)] p-2">
                <div className="flex items-center gap-2">
                  <span className={j.status === "done" ? "text-emerald-300" : j.status === "failed" ? "text-red-300" : "text-cyan-300"}>{j.status}</span>
                  <span className="truncate">{j.output}</span>
                  {j.status === "done" && <button className="btn ml-auto !py-0.5" onClick={() => download(j.output)} aria-label={`Download ${j.output}`}><Download size={11} /></button>}
                </div>
                {j.captions && <button className="mt-1 text-cyan-300 underline" onClick={() => download(j.captions!)}>{j.captions}</button>}
                {j.error && <p className="mt-1 break-anywhere text-red-300">{j.error}</p>}
              </div>
            ))}
            {videos.length > 0 && (
              <>
                <div className="hud-label pt-2 text-[var(--color-mute)]">Files</div>
                {home.files.map((f) => (
                  <div key={f.name} className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate">{f.name}</span>
                    <span className="text-[var(--color-mute)]">{mb(f.bytes)}</span>
                    <button className="btn !py-0.5" onClick={() => download(f.name)} aria-label={`Download ${f.name}`}><Download size={11} /></button>
                    <button className="btn !py-0.5" onClick={() => client.del(`/api/video/file?name=${encodeURIComponent(f.name)}`).then(load)} aria-label={`Delete ${f.name}`}><Trash2 size={11} /></button>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      )}
    </Section>
  );
}
