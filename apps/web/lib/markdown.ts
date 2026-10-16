/**
 * Tiny, safe Markdown parser for agent replies.
 *
 * It produces a small AST that components/Markdown.tsx turns into React elements, never HTML strings,
 * so model output (which may contain injected text from web pages or social posts) can't inject markup.
 * Links are kept only when they are http(s) URLs.
 */

export type Inline =
  | { t: "text"; v: string }
  | { t: "code"; v: string }
  | { t: "strong"; c: Inline[] }
  | { t: "em"; c: Inline[] }
  | { t: "link"; href: string; c: Inline[] };

export type Block =
  | { t: "p"; lines: Inline[][] }
  | { t: "h"; level: number; c: Inline[] }
  | { t: "hr" }
  | { t: "pre"; v: string }
  | { t: "ul" | "ol"; items: Inline[][] }
  | { t: "quote"; lines: Inline[][] }
  | { t: "table"; head: Inline[][]; rows: Inline[][][] };

export function safeHref(url: string): string | null {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : null;
  } catch {
    return null;
  }
}

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\[[^\]\n]+\]\([^)\s]+\))|(https?:\/\/[^\s<>"'`)\]]*[^\s<>"'`)\].,;:!?])|((?<![\w*])\*[^*\s][^*\n]*\*(?!\w))|((?<![\w_])_[^_\s][^_\n]*_(?!\w))/;

export function parseInline(src: string, depth = 0): Inline[] {
  const out: Inline[] = [];
  let rest = src;
  while (rest) {
    const m = depth > 3 ? null : INLINE.exec(rest);
    if (!m) {
      out.push({ t: "text", v: rest });
      break;
    }
    if (m.index > 0) out.push({ t: "text", v: rest.slice(0, m.index) });
    const tok = m[0];
    if (m[1]) out.push({ t: "code", v: tok.slice(1, -1) });
    else if (m[2]) out.push({ t: "strong", c: parseInline(tok.slice(2, -2), depth + 1) });
    else if (m[3]) {
      const close = tok.indexOf("](");
      const label = tok.slice(1, close);
      const href = safeHref(tok.slice(close + 2, -1));
      if (href) out.push({ t: "link", href, c: parseInline(label, depth + 1) });
      else out.push({ t: "text", v: label });
    } else if (m[4]) {
      const href = safeHref(tok);
      out.push(href ? { t: "link", href, c: [{ t: "text", v: tok }] } : { t: "text", v: tok });
    } else out.push({ t: "em", c: parseInline(tok.slice(1, -1), depth + 1) });
    rest = rest.slice(m.index + tok.length);
  }
  return out;
}

const cells = (line: string) =>
  line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => parseInline(c.trim()));

export function parseMarkdown(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    if (/^\s*```/.test(line)) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) body.push(lines[i++]);
      i++; // closing fence (or end)
      blocks.push({ t: "pre", v: body.join("\n") });
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      blocks.push({ t: "h", level: h[1].length, c: parseInline(h[2].trim()) });
      i++;
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      blocks.push({ t: "hr" });
      i++;
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]) && lines[i + 1].includes("-")) {
      const head = cells(line);
      const rows: Inline[][][] = [];
      i += 2;
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
      blocks.push({ t: "table", head, rows });
      continue;
    }
    const ul = /^\s*[-*+]\s+/;
    const ol = /^\s*\d+[.)]\s+/;
    if (ul.test(line) || ol.test(line)) {
      const kind = ul.test(line) ? "ul" : "ol";
      const re = kind === "ul" ? ul : ol;
      const items: Inline[][] = [];
      while (i < lines.length && re.test(lines[i])) items.push(parseInline(lines[i++].replace(re, "")));
      blocks.push({ t: kind, items });
      continue;
    }
    if (/^\s*>\s?/.test(line)) {
      const q: Inline[][] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) q.push(parseInline(lines[i++].replace(/^\s*>\s?/, "")));
      blocks.push({ t: "quote", lines: q });
      continue;
    }
    const para: Inline[][] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^\s*```|^#{1,6}\s|^\s*[-*+]\s+|^\s*\d+[.)]\s+|^\s*>|^\s*\|.*\|\s*$/.test(lines[i]) &&
      !/^\s*([-*_])(\s*\1){2,}\s*$/.test(lines[i])
    )
      para.push(parseInline(lines[i++]));
    if (para.length) blocks.push({ t: "p", lines: para });
    else i++; // safety: never loop forever
  }
  return blocks;
}
