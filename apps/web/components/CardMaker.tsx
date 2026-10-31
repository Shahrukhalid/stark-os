"use client";

import { ChevronLeft, ChevronRight, Images, Save, Send } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { slides } from "@/lib/cards";
import { useStark } from "@/lib/store";
import { Section } from "./ui";

const THEMES = {
  neon: { bg: ["#06080b", "#0f1b2d"], fg: "#e6f6ff", accent: "#22d3ee", accent2: "#a78bfa" },
  light: { bg: ["#ffffff", "#eef4f8"], fg: "#17212b", accent: "#0e7490", accent2: "#6d28d9" },
  sunset: { bg: ["#2b0b3a", "#7a1f4b"], fg: "#fff4ec", accent: "#fbbf24", accent2: "#f472b6" },
  forest: { bg: ["#0b1f17", "#14532d"], fg: "#ecfdf5", accent: "#34d399", accent2: "#a3e635" },
} as const;
const SIZES = { square: [1080, 1080], portrait: [1080, 1350], story: [1080, 1920] } as const;

function wrap(ctx: CanvasRenderingContext2D, text: string, width: number): string[] {
  const lines: string[] = [];
  for (const raw of text.split("\n")) {
    let line = "";
    for (const word of raw.split(/\s+/)) {
      const test = line ? `${line} ${word}` : word;
      if (ctx.measureText(test).width > width && line) {
        lines.push(line);
        line = word;
      } else line = test;
    }
    lines.push(line);
  }
  return lines;
}

function draw(canvas: HTMLCanvasElement, text: string, brand: string, theme: keyof typeof THEMES, size: keyof typeof SIZES, page: number, pages: number) {
  const [W, H] = SIZES[size];
  const t = THEMES[theme];
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d")!;
  const g = ctx.createLinearGradient(0, 0, W, H);
  g.addColorStop(0, t.bg[0]);
  g.addColorStop(1, t.bg[1]);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  // soft glow and corner brackets
  const r = ctx.createRadialGradient(W * 0.8, H * 0.15, 0, W * 0.8, H * 0.15, W * 0.7);
  r.addColorStop(0, `${t.accent}33`);
  r.addColorStop(1, "transparent");
  ctx.fillStyle = r;
  ctx.fillRect(0, 0, W, H);
  ctx.strokeStyle = t.accent;
  ctx.lineWidth = 6;
  for (const [x, y, dx, dy] of [[60, 60, 1, 1], [W - 60, H - 60, -1, -1]]) {
    ctx.beginPath();
    ctx.moveTo(x, y + 80 * dy);
    ctx.lineTo(x, y);
    ctx.lineTo(x + 80 * dx, y);
    ctx.stroke();
  }
  // text: shrink until it fits
  let fontSize = 76;
  let lines: string[] = [];
  const maxW = W - 220;
  for (; fontSize >= 34; fontSize -= 4) {
    ctx.font = `600 ${fontSize}px ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`;
    lines = wrap(ctx, text || "Your words here", maxW);
    if (lines.length * fontSize * 1.3 < H - 420) break;
  }
  const lh = fontSize * 1.3;
  let y = (H - lines.length * lh) / 2 + fontSize * 0.8;
  ctx.fillStyle = t.fg;
  ctx.textAlign = "left";
  for (const line of lines) {
    ctx.fillText(line, 110, y);
    y += lh;
  }
  ctx.fillStyle = t.accent;
  ctx.fillRect(110, H - 190, 90, 6);
  ctx.font = `600 34px ui-sans-serif, system-ui, sans-serif`;
  ctx.fillStyle = t.accent2;
  ctx.fillText(brand, 110, H - 130);
  if (pages > 1) {
    ctx.textAlign = "right";
    ctx.fillStyle = t.fg;
    ctx.globalAlpha = 0.7;
    ctx.fillText(`${page + 1}/${pages}${page + 1 < pages ? "  →" : ""}`, W - 110, H - 130);
    ctx.globalAlpha = 1;
  }
}

/** Branded quote cards and carousels, drawn on your computer (nothing is sent anywhere) and saved to Media. */
export function CardMaker({ talkTo }: { talkTo: (agentId: string, text?: string) => void }) {
  const { client, notify } = useStark();
  const [text, setText] = useState("");
  const [brand, setBrand] = useState("@yourbrand");
  const [theme, setTheme] = useState<keyof typeof THEMES>("neon");
  const [size, setSize] = useState<keyof typeof SIZES>("square");
  const [page, setPage] = useState(0);
  const [saved, setSaved] = useState<string[]>([]);
  const ref = useRef<HTMLCanvasElement>(null);
  const pages = useMemo(() => (slides(text).length ? slides(text) : [""]), [text]);

  useEffect(() => {
    if (page >= pages.length) setPage(0);
    if (ref.current) draw(ref.current, pages[Math.min(page, pages.length - 1)], brand, theme, size, page, pages.length);
  }, [pages, brand, theme, size, page]);

  async function saveAll() {
    const off = document.createElement("canvas");
    const files: string[] = [];
    try {
      for (let i = 0; i < pages.length; i++) {
        draw(off, pages[i], brand, theme, size, i, pages.length);
        const blob = await new Promise<Blob>((res, rej) => off.toBlob((b) => (b ? res(b) : rej(new Error("Could not draw the image"))), "image/png"));
        const out = await client.upload<{ file: string }>(`/api/media/upload?name=${encodeURIComponent(pages.length > 1 ? `slide-${i + 1}` : "quote")}`, blob);
        files.push(out.file);
      }
      setSaved(files);
      notify("success", `${files.length} image(s) saved to Media.`);
    } catch (e: any) {
      notify("error", e.message);
    }
  }

  return (
    <Section title="Quote cards & carousels" right={<Images size={15} className="text-amber-300" />}>
      <div className="grid gap-3 lg:grid-cols-[1fr_260px]">
        <div className="space-y-2">
          <textarea className="input min-h-[110px]" aria-label="Card text" placeholder={"A quote, a tip or a short story.\n\nA blank line starts a new carousel slide."} value={text} onChange={(e) => setText(e.target.value)} />
          <div className="flex flex-wrap gap-2">
            <input className="input !w-40 !py-1 text-xs" aria-label="Brand line" value={brand} onChange={(e) => setBrand(e.target.value)} />
            <select className="input !w-auto !py-1 text-xs" aria-label="Card theme" value={theme} onChange={(e) => setTheme(e.target.value as keyof typeof THEMES)}>
              {Object.keys(THEMES).map((k) => (
                <option key={k} value={k} className="capitalize">
                  {k}
                </option>
              ))}
            </select>
            <select className="input !w-auto !py-1 text-xs" aria-label="Card size" value={size} onChange={(e) => setSize(e.target.value as keyof typeof SIZES)}>
              <option value="square">Square 1080×1080</option>
              <option value="portrait">Portrait 1080×1350</option>
              <option value="story">Story 1080×1920</option>
            </select>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn btn-primary" disabled={!text.trim()} onClick={saveAll}>
              <Save size={14} /> Save {pages.length > 1 ? `${pages.length} slides` : "card"}
            </button>
            {saved.length > 0 && (
              <button className="btn" onClick={() => talkTo("edith", `EDITH, write a post to go with these images (${saved.join(", ")}), attach them in this order as media with good alt text, and save it as a draft. The text on them: ${pages.join(" / ")}`)}>
                <Send size={14} /> Write a post for it
              </button>
            )}
          </div>
          <p className="text-[11px] text-[var(--color-mute)]">Drawn in your browser: nothing leaves your computer. Saved images appear in Library → Media.</p>
        </div>
        <div>
          <canvas ref={ref} aria-label="Card preview" className="w-full rounded-lg border border-[var(--color-line)]" />
          {pages.length > 1 && (
            <div className="mt-1 flex items-center justify-center gap-2 text-xs">
              <button aria-label="Previous slide" onClick={() => setPage((p) => Math.max(0, p - 1))}>
                <ChevronLeft size={14} />
              </button>
              {page + 1}/{pages.length}
              <button aria-label="Next slide" onClick={() => setPage((p) => Math.min(pages.length - 1, p + 1))}>
                <ChevronRight size={14} />
              </button>
            </div>
          )}
        </div>
      </div>
    </Section>
  );
}
