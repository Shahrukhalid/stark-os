/** Split long text into carousel slides: blank lines start a new slide; long paragraphs are split too. */
export function slides(text: string, maxChars = 220): string[] {
  const out: string[] = [];
  for (const para of text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean)) {
    if (para.length <= maxChars) {
      out.push(para);
      continue;
    }
    let cur = "";
    for (const sentence of para.split(/(?<=[.!?])\s+/)) {
      if ((cur + " " + sentence).trim().length > maxChars && cur) {
        out.push(cur.trim());
        cur = sentence;
      } else cur = `${cur} ${sentence}`;
    }
    if (cur.trim()) out.push(cur.trim());
  }
  return out.slice(0, 10);
}
