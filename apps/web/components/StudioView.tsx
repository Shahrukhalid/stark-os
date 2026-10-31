"use client";

import { Copy, FlaskConical, ImagePlus, LoaderCircle, Mic, Recycle, Send, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import type { AnalyticsReport } from "@/lib/types";
import { Section } from "./ui";

const PLATFORMS = ["bluesky", "mastodon", "x", "linkedin", "threads", "instagram", "tiktok", "youtube"];
const NAMES: Record<string, string> = { bluesky: "Bluesky", mastodon: "Mastodon", x: "X", linkedin: "LinkedIn", threads: "Threads", instagram: "Instagram", tiktok: "TikTok", youtube: "YouTube" };
const FORMATS = [
  { id: "post", label: "Short post per platform" },
  { id: "thread", label: "Thread (Bluesky / Mastodon / X)" },
  { id: "video", label: "30-second video script (U)" },
  { id: "image", label: "An original image (U)" },
];

/** Creative studio: repurpose content, generate images, run A/B hook tests and teach the team your voice. */
export function StudioView({ talkTo }: { talkTo: (agentId: string, text?: string) => void }) {
  const { client, notify } = useStark();
  const [src, setSrc] = useState("");
  const [targets, setTargets] = useState<string[]>(["bluesky", "mastodon", "linkedin"]);
  const [formats, setFormats] = useState<string[]>(["post", "thread"]);
  const [prompt, setPrompt] = useState("");
  const [img, setImg] = useState<{ file: string; url: string } | null>(null);
  const [imgBusy, setImgBusy] = useState(false);
  const [abTopic, setAbTopic] = useState("");
  const [abPlatform, setAbPlatform] = useState("bluesky");
  const [report, setReport] = useState<AnalyticsReport | null>(null);

  useEffect(() => {
    client.get<AnalyticsReport>("/api/social/analytics").then(setReport).catch(() => {});
  }, [client]);
  useEffect(
    () => () => {
      if (img) URL.revokeObjectURL(img.url);
    },
    [img],
  );

  const isUrl = /^https?:\/\/\S+$/i.test(src.trim());
  const toggle = (list: string[], set: (v: string[]) => void, v: string) => set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  function repurpose() {
    const wants = FORMATS.filter((f) => formats.includes(f.id)).map((f) => f.label.toLowerCase());
    const source = isUrl ? `Read this page first (web.fetch): ${src.trim()}` : `Source text:\n"""\n${src.trim().slice(0, 6000)}\n"""`;
    talkTo(
      "jarvis",
      `JARVIS, repurpose this content for ${targets.join(", ")}. Deliver: ${wants.join("; ")}. ${source}\n\nDelegate: E.D.I.T.H. writes each platform's version in our brand voice (respecting each platform's length), JOCASTA checks any facts against the source, U makes the video script and an original image if asked. Save every piece as a draft for me to review. Keep the source's meaning; credit it with a link when one was given.`,
    );
  }

  async function makeImage() {
    setImgBusy(true);
    try {
      const out = await client.post<{ file: string }>("/api/media/generate", { prompt });
      const blob = await client.blob(`/api/media/file?name=${encodeURIComponent(out.file.split("/").pop() || "")}`);
      setImg({ file: out.file, url: URL.createObjectURL(blob) });
    } catch (e: any) {
      notify("error", e.message);
    } finally {
      setImgBusy(false);
    }
  }

  function abTest() {
    talkTo(
      "edith",
      `EDITH, set up an A/B hook test on ${abPlatform} about: ${abTopic}. Write two drafts with the same message but clearly different opening hooks (A: question, B: bold statement). Save both with campaign "ab:${abTopic.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40)}" and say which is A and which is B. I will schedule them on different days at the same time; the Analytics page compares them.`,
    );
  }

  function learnVoice() {
    const top = [...(report?.posts ?? [])].filter((p) => p.score != null).sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).slice(0, 10);
    if (!top.length) return notify("warn", "Needs published posts with real engagement first.");
    talkTo(
      "jarvis",
      `JARVIS, these are our ${top.length} best-performing posts (by real engagement):\n\n${top.map((p, i) => `${i + 1}. (${p.platform}, ♥${p.engagement?.likes ?? 0} ⟲${p.engagement?.reposts ?? 0} 💬${p.engagement?.replies ?? 0}) ${p.text}`).join("\n")}\n\nWork out our brand voice from them: tone, sentence length, hooks that worked, emoji and hashtag habits, topics people respond to. Save it to shared memory as "brand voice" so every agent writes like this from now on, then summarise it for me.`,
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <section className="panel p-4">
        <div className="hud-label text-cyan-300">Creative studio</div>
        <h1 className="holo-text text-xl font-semibold">Studio</h1>
        <p className="text-xs text-[var(--color-mute)]">Turn one piece of content into many, make images, test hooks and teach the team your voice. Everything becomes drafts you approve.</p>
      </section>

      <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-2">
        <Section title="Repurpose" right={<Recycle size={15} className="text-cyan-300" />}>
          <textarea className="input min-h-[120px]" aria-label="Link or text to repurpose" placeholder="Paste a blog or YouTube link, or the text of an article, newsletter or talk…" value={src} onChange={(e) => setSrc(e.target.value)} />
          <div className="mt-2 text-xs text-[var(--color-mute)]">{isUrl ? "Link: the team will read the page first." : src.trim() ? `${src.trim().length} characters of text` : ""}</div>
          <div className="mt-3 hud-label text-[var(--color-mute)]">Platforms</div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {PLATFORMS.map((p) => (
              <button key={p} aria-pressed={targets.includes(p)} onClick={() => toggle(targets, setTargets, p)} className={`chip ${targets.includes(p) ? "!border-cyan-400/60 !text-cyan-200" : ""}`}>
                {NAMES[p]}
              </button>
            ))}
          </div>
          <div className="mt-3 hud-label text-[var(--color-mute)]">Formats</div>
          <div className="mt-1 grid gap-1 sm:grid-cols-2">
            {FORMATS.map((f) => (
              <label key={f.id} className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={formats.includes(f.id)} onChange={() => toggle(formats, setFormats, f.id)} /> {f.label}
              </label>
            ))}
          </div>
          <button className="btn btn-primary mt-3" disabled={src.trim().length < 20 && !isUrl || !targets.length || !formats.length} onClick={repurpose}>
            <Send size={14} /> Repurpose with the team
          </button>
        </Section>

        <Section title="AI image" right={<ImagePlus size={15} className="text-fuchsia-300" />}>
          <div className="flex gap-2">
            <input className="input" aria-label="Image description" placeholder="A minimalist robot arm painting a sunrise, flat illustration" value={prompt} onChange={(e) => setPrompt(e.target.value)} onKeyDown={(e) => e.key === "Enter" && prompt.length > 2 && makeImage()} />
            <button className="btn shrink-0" disabled={prompt.trim().length < 3 || imgBusy} onClick={makeImage}>
              {imgBusy ? <LoaderCircle size={14} className="anim-spin-fast" /> : <Sparkles size={14} />} Create
            </button>
          </div>
          <p className="mt-1 text-[11px] text-[var(--color-mute)]">Free (Pollinations, no key). The prompt is sent to that service. No real people, logos or characters.</p>
          <div className="mt-3 flex aspect-square max-h-[340px] w-full items-center justify-center overflow-hidden rounded-lg border border-[var(--color-line)] bg-black/10">
            {imgBusy ? (
              <div className="shimmer h-full w-full" aria-label="Creating image" />
            ) : img ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={img.url} alt={prompt} className="h-full w-full object-contain" style={{ animation: "stark-view-in .5s both" }} />
            ) : (
              <ImagePlus size={32} className="text-[var(--color-mute)]" />
            )}
          </div>
          {img && (
            <div className="mt-2 flex flex-wrap gap-2">
              <button className="btn !py-1 text-xs" onClick={() => navigator.clipboard?.writeText(img.file).then(() => notify("success", "Path copied"), () => {})}>
                <Copy size={12} /> {img.file}
              </button>
              <button className="btn !py-1 text-xs" onClick={() => talkTo("edith", `EDITH, write a Bluesky post to go with the image ${img.file} (it shows: ${prompt}). Attach it with media file ${img.file} and good alt text.`)}>
                <Send size={12} /> Write a post for it
              </button>
            </div>
          )}
        </Section>

        <Section title="A/B hook test" right={<FlaskConical size={15} className="text-violet-300" />}>
          <p className="mb-2 text-xs text-[var(--color-mute)]">Two versions of one post with different opening hooks. Publish them on different days at the same time; Analytics shows the winner under Experiments.</p>
          <div className="flex flex-wrap gap-2">
            <input className="input min-w-0 flex-1" aria-label="A/B test topic" placeholder="our new CSV export" value={abTopic} onChange={(e) => setAbTopic(e.target.value)} />
            <select className="input !w-auto" aria-label="A/B test platform" value={abPlatform} onChange={(e) => setAbPlatform(e.target.value)}>
              <option value="bluesky">Bluesky</option>
              <option value="mastodon">Mastodon</option>
            </select>
            <button className="btn" disabled={abTopic.trim().length < 3} onClick={abTest}>
              <FlaskConical size={14} /> Start test
            </button>
          </div>
        </Section>

        <Section title="Brand voice" right={<Mic size={15} className="text-emerald-300" />}>
          <p className="mb-2 text-xs text-[var(--color-mute)]">
            J.A.R.V.I.S. studies your best posts (real engagement) and saves your voice to shared memory, so every agent writes like you.
            {report ? ` ${report.posts.filter((p) => p.score != null).length} measured post(s) available.` : ""}
          </p>
          <button className="btn" onClick={learnVoice}>
            <Mic size={14} /> Learn my voice
          </button>
        </Section>
      </div>
    </div>
  );
}
