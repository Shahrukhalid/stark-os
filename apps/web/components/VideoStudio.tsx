"use client";

import { Clapperboard, Download, Image as ImageIcon, LoaderCircle, Mic, Scissors, Trash2, Upload, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import { Section } from "./ui";

type VFile = { name: string; bytes: number; kind: "video" | "image" | "captions"; transcript?: boolean };
type Job = { id: string; kind: string; status: "queued" | "running" | "done" | "failed" | "cancelled"; progress: number; file: string; output: string | null; captions: string | null; error: string | null; preset?: string; format?: string; model?: string };
type Model = { name: string; label: string; installed: boolean };
type FF = { available: boolean; message?: string; version?: string; burn_captions?: boolean; transitions?: boolean; transcribe?: boolean };
type Home = { ffmpeg: FF; files: VFile[]; jobs: Job[]; presets: Record<string, { label: string }>; formats: string[]; models: Model[] };
type Seg = { start: number; end: number; text: string };
type Transcript = { file: string; segments: Seg[]; clips: Seg[]; text: string };

const mb = (n: number) => `${(n / 1048576).toFixed(1)} MB`;
const t = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;
const KIND: Record<string, string> = { export: "Export", merge: "Join", transcribe: "Transcribe", model: "Speech model" };

/** Trim, join, speed, captions from speech, platform sizes, thumbnails: all on this computer. */
export function VideoStudio({ talkTo }: { talkTo: (agentId: string, text?: string) => void }) {
  const { client, notify } = useStark();
  const [home, setHome] = useState<Home | null>(null);
  const [busy, setBusy] = useState("");
  const [join, setJoin] = useState<string[]>([]);
  const [tr, setTr] = useState<Transcript | null>(null);
  const [frames, setFrames] = useState<{ a?: string; b?: string }>({});
  const [model, setModel] = useState("base");
  const [o, setO] = useState({
    file: "", presets: ["vertical"] as string[], format: "mp4", fit: "pad", start: "", end: "", mute: false, speed: 1, volume: 1, fade: 0, transition: 0.5,
    captions: "none", caption_source: "script", script: "", srt: "", style: { size: 14, color: "white", position: "bottom", box: false },
  });
  const set = (k: keyof typeof o, v: any) => setO((x) => ({ ...x, [k]: v }));

  const load = useCallback(() => {
    client.get<Home>("/api/video").then((h) => {
      setHome(h);
      const first = h.files.find((f) => f.kind === "video");
      setO((x) => (x.file || !first ? x : { ...x, file: first.name }));
    }).catch((e) => notify("error", e.message));
  }, [client, notify]);
  useEffect(load, [load]);
  const running = home?.jobs.some((j) => j.status === "queued" || j.status === "running");
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(load, 1000);
    return () => clearInterval(timer);
  }, [running, load]);

  const current = home?.files.find((f) => f.name === o.file);
  useEffect(() => {
    setTr(null);
    if (current?.transcript) client.get<Transcript>(`/api/video/transcript?name=${encodeURIComponent(current.name)}`).then(setTr).catch(() => {});
  }, [client, current?.name, current?.transcript]);

  // timeline: frames at the start and end of the cut
  useEffect(() => {
    if (!o.file) return;
    let live = true;
    const urls: string[] = [];
    const grab = (at: number, key: "a" | "b") =>
      client.blob(`/api/video/preview?name=${encodeURIComponent(o.file)}&at=${at}`).then((b) => {
        const u = URL.createObjectURL(b);
        urls.push(u);
        if (live) setFrames((f) => ({ ...f, [key]: u }));
      }).catch(() => {});
    const timer = setTimeout(() => {
      grab(Number(o.start || 0), "a");
      if (o.end) grab(Math.max(0, Number(o.end) - 0.1), "b");
      else setFrames((f) => ({ ...f, b: undefined }));
    }, 400);
    return () => {
      live = false;
      clearTimeout(timer);
      urls.forEach((u) => setTimeout(() => URL.revokeObjectURL(u), 5000));
    };
  }, [client, o.file, o.start, o.end]);

  async function act(name: string, call: () => Promise<unknown>, ok?: string) {
    setBusy(name);
    try {
      await call();
      if (ok) notify("success", ok);
      load();
    } catch (e: any) {
      notify("error", e.message);
    } finally {
      setBusy("");
    }
  }

  const upload = (f: File) => act("upload", async () => {
    const r = await client.upload<{ name: string }>(`/api/video/upload?name=${encodeURIComponent(f.name)}`, f);
    set("file", r.name);
  }, "Video added");

  const exportVideo = (extra: Record<string, unknown> = {}) => act("export", () => client.post("/api/video/export", {
    ...o, file: o.file, files: join.length >= 2 ? join : null, preset: o.presets[0], presets: o.presets,
    start: o.start ? Number(o.start) : null, end: o.end ? Number(o.end) : null, transition: o.transition,
    script: o.script || null, srt: o.srt || null, caption_source: o.srt ? "srt" : o.caption_source, ...extra,
  }));

  async function exportClips() {
    if (!tr) return;
    for (const c of tr.clips) await exportVideo({ start: c.start, end: c.end, files: null });
    notify("success", `${tr.clips.length} clips queued`);
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
  const ff = home.ffmpeg;
  const videos = home.files.filter((f) => f.kind === "video");
  const installed = home.models.filter((m) => m.installed);
  const label = (txt: string) => <span className="hud-label text-[var(--color-mute)]">{txt}</span>;

  return (
    <Section title="Video studio" right={<Clapperboard size={15} className="text-cyan-300" />}>
      {!ff.available ? (
        <p className="text-sm text-amber-300">{ff.message}</p>
      ) : (
        <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-[1.3fr_1fr]">
          <div className="space-y-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <select aria-label="Video" className="input !w-auto min-w-0 flex-1" value={o.file} onChange={(e) => set("file", e.target.value)}>
                {videos.length === 0 && <option value="">Add a video first</option>}
                {videos.map((f) => <option key={f.name} value={f.name}>{f.name} · {mb(f.bytes)}{f.transcript ? " · transcribed" : ""}</option>)}
              </select>
              <label className="btn cursor-pointer">
                {busy === "upload" ? <LoaderCircle size={13} className="animate-spin" /> : <Upload size={13} />} Add video
                <input type="file" accept="video/mp4,video/quicktime,video/webm,video/x-matroska,.m4v" className="sr-only" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
              </label>
            </div>

            {o.file && (
              <div className="grid grid-cols-2 gap-2" aria-label="Timeline">
                {(["a", "b"] as const).map((k) => (
                  <figure key={k} className="overflow-hidden rounded-lg border border-[var(--color-line)] bg-black/40">
                    {frames[k] ? <img src={frames[k]} alt={k === "a" ? "First frame of the cut" : "Last frame of the cut"} className="h-28 w-full object-contain" /> : <div className="grid h-28 place-items-center text-xs text-[var(--color-mute)]">{k === "a" ? "start" : "end of video"}</div>}
                    <figcaption className="px-2 py-1 text-[11px] text-[var(--color-mute)]">{k === "a" ? `Start ${t(Number(o.start || 0))}` : o.end ? `End ${t(Number(o.end))}` : "End"}</figcaption>
                  </figure>
                ))}
              </div>
            )}

            <div className="grid gap-2 sm:grid-cols-3">
              <label>{label("Start (s)")}<input className="input mt-1 w-full" type="number" min={0} step={0.1} value={o.start} onChange={(e) => set("start", e.target.value)} placeholder="0" /></label>
              <label>{label("End (s)")}<input className="input mt-1 w-full" type="number" min={0} step={0.1} value={o.end} onChange={(e) => set("end", e.target.value)} placeholder="end" /></label>
              <label>{label("Format")}<select className="input mt-1 w-full" value={o.format} onChange={(e) => set("format", e.target.value)}>{home.formats.map((f) => <option key={f} value={f}>{f.toUpperCase()}</option>)}</select></label>
              <label>{label(`Speed ${o.speed}×`)}<input className="mt-2 w-full" type="range" min={0.5} max={2} step={0.25} value={o.speed} onChange={(e) => set("speed", Number(e.target.value))} /></label>
              <label>{label(`Volume ${Math.round(o.volume * 100)}%`)}<input className="mt-2 w-full" type="range" min={0} max={2} step={0.1} value={o.volume} onChange={(e) => set("volume", Number(e.target.value))} disabled={o.mute} /></label>
              <label>{label(`Fade in/out ${o.fade}s`)}<input className="mt-2 w-full" type="range" min={0} max={1} step={0.25} value={o.fade} onChange={(e) => set("fade", Number(e.target.value))} /></label>
            </div>

            <fieldset className="space-y-1">
              <legend className="hud-label text-[var(--color-mute)]">Sizes (one export each)</legend>
              <div className="flex flex-wrap gap-2 text-xs">
                {Object.entries(home.presets).map(([id, p]) => (
                  <label key={id} className={`chip cursor-pointer ${o.presets.includes(id) ? "!border-cyan-400 !text-cyan-200" : ""}`}>
                    <input type="checkbox" className="sr-only" checked={o.presets.includes(id)} onChange={(e) => set("presets", e.target.checked ? [...o.presets, id] : o.presets.filter((x) => x !== id).length ? o.presets.filter((x) => x !== id) : o.presets)} />
                    {p.label}
                  </label>
                ))}
              </div>
              <div className="flex flex-wrap gap-3 pt-1 text-xs">
                <label className="flex items-center gap-1"><input type="radio" checked={o.fit === "pad"} onChange={() => set("fit", "pad")} /> Whole picture (bars)</label>
                <label className="flex items-center gap-1"><input type="radio" checked={o.fit === "crop"} onChange={() => set("fit", "crop")} /> Fill the frame (crop)</label>
                <label className="flex items-center gap-1"><input type="checkbox" checked={o.mute} onChange={(e) => set("mute", e.target.checked)} /> Remove sound</label>
              </div>
            </fieldset>

            <details className="rounded-lg border border-[var(--color-line)] p-2" open={o.captions !== "none"}>
              <summary className="cursor-pointer text-xs font-medium">Captions</summary>
              <div className="mt-2 space-y-2">
                <div className="grid gap-2 sm:grid-cols-2">
                  <label>{label("Captions")}
                    <select className="input mt-1 w-full" value={o.captions} onChange={(e) => set("captions", e.target.value)}>
                      <option value="none">None</option>
                      {ff.burn_captions && <option value="burn">Burned into the picture</option>}
                      <option value="track">Caption track (MP4)</option>
                      <option value="file">Separate .srt file</option>
                    </select>
                  </label>
                  <label>{label("Text from")}
                    <select className="input mt-1 w-full" value={o.caption_source} onChange={(e) => set("caption_source", e.target.value)}>
                      <option value="transcript" disabled={!current?.transcript}>The speech (transcribe first)</option>
                      <option value="script">A script (evenly timed)</option>
                    </select>
                  </label>
                </div>
                {o.caption_source === "script" && o.captions !== "none" && (
                  <>
                    <textarea className="input w-full" rows={2} value={o.script} onChange={(e) => set("script", e.target.value)} placeholder="Script" />
                    <textarea className="input w-full font-mono text-xs" rows={2} value={o.srt} onChange={(e) => set("srt", e.target.value)} placeholder="…or paste exact SRT captions" />
                  </>
                )}
                {o.captions === "burn" && (
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <label className="flex items-center gap-1">Size <input className="input !w-16 !py-1" type="number" min={8} max={40} value={o.style.size} onChange={(e) => set("style", { ...o.style, size: Number(e.target.value) })} /></label>
                    <select className="input !w-auto !py-1" aria-label="Caption colour" value={o.style.color} onChange={(e) => set("style", { ...o.style, color: e.target.value })}><option value="white">White</option><option value="yellow">Yellow</option><option value="cyan">Cyan</option></select>
                    <select className="input !w-auto !py-1" aria-label="Caption position" value={o.style.position} onChange={(e) => set("style", { ...o.style, position: e.target.value })}><option value="bottom">Bottom</option><option value="middle">Middle</option><option value="top">Top</option></select>
                    <label className="flex items-center gap-1"><input type="checkbox" checked={o.style.box} onChange={(e) => set("style", { ...o.style, box: e.target.checked })} /> Dark box</label>
                  </div>
                )}
              </div>
            </details>

            {videos.length >= 2 && (
              <details className="rounded-lg border border-[var(--color-line)] p-2" open={join.length > 0}>
                <summary className="cursor-pointer text-xs font-medium">Join videos {join.length >= 2 && `(${join.length} in order)`}</summary>
                <div className="mt-2 space-y-1 text-xs">
                  {videos.map((f) => (
                    <label key={f.name} className="flex items-center gap-2">
                      <input type="checkbox" checked={join.includes(f.name)} onChange={(e) => setJoin((j) => (e.target.checked ? [...j, f.name] : j.filter((x) => x !== f.name)))} />
                      {join.includes(f.name) && <b>{join.indexOf(f.name) + 1}.</b>} <span className="truncate">{f.name}</span>
                    </label>
                  ))}
                  {ff.transitions && <label className="flex items-center gap-2 pt-1">Cross-fade {o.transition}s <input type="range" min={0} max={1.5} step={0.25} value={o.transition} onChange={(e) => set("transition", Number(e.target.value))} /></label>}
                </div>
              </details>
            )}

            <div className="flex flex-wrap gap-2">
              <button className="btn btn-primary" disabled={(!o.file && join.length < 2) || busy === "export"} onClick={() => exportVideo()}>
                {busy === "export" ? <LoaderCircle size={13} className="animate-spin" /> : <Clapperboard size={13} />} {join.length >= 2 ? `Join ${join.length} videos` : o.presets.length > 1 ? `Export ${o.presets.length} sizes` : "Export"}
              </button>
              <button className="btn" disabled={!o.file || busy === "thumb"} onClick={() => act("thumb", () => client.post("/api/video/thumbnail", { file: o.file, at: Number(o.start || 1) }), "Thumbnail saved to your media library")}>
                <ImageIcon size={13} /> Thumbnail at start
              </button>
            </div>
          </div>

          <div className="space-y-3 text-xs">
            <div className="rounded-lg border border-[var(--color-line)] p-2">
              <div className="mb-1 flex items-center gap-2 font-medium"><Mic size={13} className="text-cyan-300" /> Speech to text</div>
              {!ff.transcribe ? (
                <p className="text-[var(--color-mute)]">Not available in this install. The desktop app includes it.</p>
              ) : (
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <select className="input !w-auto !py-1" aria-label="Speech model" value={model} onChange={(e) => setModel(e.target.value)}>
                      {home.models.map((m) => <option key={m.name} value={m.name}>{m.label}{m.installed ? " ✓" : ""}</option>)}
                    </select>
                    {home.models.find((m) => m.name === model)?.installed ? (
                      <button className="btn !py-1" disabled={!o.file || busy === "tr"} onClick={() => act("tr", () => client.post("/api/video/transcribe", { file: o.file, model }))}>Transcribe</button>
                    ) : (
                      <button className="btn !py-1" onClick={() => act("dl", () => client.post(`/api/video/models/${model}`), "Downloading the model")}><Download size={11} /> Download model</button>
                    )}
                  </div>
                  {installed.length === 0 && <p className="text-[var(--color-mute)]">The model is downloaded once from the public whisper.cpp model page and then works offline on this computer.</p>}
                  {tr && (
                    <>
                      <div className="max-h-40 space-y-0.5 overflow-auto rounded border border-[var(--color-line)] p-1">
                        {tr.segments.map((s, i) => (
                          <button key={i} className="block w-full rounded px-1 text-left hover:bg-white/5" title="Use as the cut" onClick={() => setO((x) => ({ ...x, start: String(s.start), end: String(s.end) }))}>
                            <span className="font-mono text-cyan-300">{t(s.start)}</span> {s.text}
                          </button>
                        ))}
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[var(--color-mute)]">{tr.clips.length} short clips found at sentence ends</span>
                        <button className="btn !py-0.5" onClick={exportClips}><Scissors size={11} /> Export all clips</button>
                        <button className="btn !py-0.5" onClick={() => talkTo("u", `U, pick the 3 best moments for Shorts from this transcript and give start/end seconds and a hook for each:\n${tr.segments.map((s) => `[${s.start}-${s.end}] ${s.text}`).join("\n").slice(0, 6000)}`)}>Ask U for the best moments</button>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>

            <div className="hud-label text-[var(--color-mute)]">Jobs</div>
            {home.jobs.length === 0 && <p className="text-[var(--color-mute)]">Nothing yet.</p>}
            {home.jobs.map((j) => (
              <div key={j.id} className="rounded-lg border border-[var(--color-line)] p-2">
                <div className="flex items-center gap-2">
                  <span className={j.status === "done" ? "text-emerald-300" : j.status === "failed" ? "text-red-300" : j.status === "cancelled" ? "text-[var(--color-mute)]" : "text-cyan-300"}>{KIND[j.kind] || j.kind} · {j.status}</span>
                  <span className="min-w-0 flex-1 truncate">{j.output || j.file}</span>
                  {(j.status === "running" || j.status === "queued") && <button className="btn !py-0.5" onClick={() => act("", () => client.del(`/api/video/jobs/${j.id}`))} aria-label="Cancel"><X size={11} /></button>}
                  {j.status === "done" && j.output && j.kind !== "model" && <button className="btn !py-0.5" onClick={() => download(j.output!)} aria-label={`Download ${j.output}`}><Download size={11} /></button>}
                </div>
                {(j.status === "running" || j.status === "queued") && (
                  <div className="mt-1 h-1.5 overflow-hidden rounded bg-white/10" role="progressbar" aria-valuenow={Math.round(j.progress * 100)} aria-valuemin={0} aria-valuemax={100}>
                    <div className="h-full bg-cyan-400 transition-all" style={{ width: `${Math.round(j.progress * 100)}%` }} />
                  </div>
                )}
                {j.captions && <button className="mt-1 text-cyan-300 underline" onClick={() => download(j.captions!)}>{j.captions}</button>}
                {j.error && <p className="mt-1 break-anywhere text-red-300">{j.error}</p>}
              </div>
            ))}

            {videos.length > 0 && (
              <>
                <div className="hud-label pt-1 text-[var(--color-mute)]">Files</div>
                {home.files.map((f) => (
                  <div key={f.name} className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate">{f.name}</span>
                    <span className="text-[var(--color-mute)]">{mb(f.bytes)}</span>
                    <button className="btn !py-0.5" onClick={() => download(f.name)} aria-label={`Download ${f.name}`}><Download size={11} /></button>
                    <button className="btn !py-0.5" onClick={() => act("", () => client.del(`/api/video/file?name=${encodeURIComponent(f.name)}`))} aria-label={`Delete ${f.name}`}><Trash2 size={11} /></button>
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
