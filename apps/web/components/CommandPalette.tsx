"use client";

import { CornerDownLeft, Search, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

export interface PaletteAction {
  id: string;
  label: string;
  hint?: string;
  group: string;
  icon?: React.ElementType;
  color?: string;
  run: () => void;
}

function score(q: string, text: string): number {
  if (!q) return 1;
  const t = text.toLowerCase();
  const i = t.indexOf(q);
  if (i === 0) return 3;
  if (i > 0) return 2;
  // loose subsequence match ("aprv" → "approvals")
  let k = 0;
  for (const ch of t) if (ch === q[k]) k++;
  return k === q.length ? 1 : 0;
}

/** Cmd/Ctrl+K: jump to any tab, talk to an agent or run an action. Unknown text is sent to J.A.R.V.I.S. */
export function CommandPalette({ open, onClose, actions, onAsk }: { open: boolean; onClose: () => void; actions: PaletteAction[]; onAsk: (text: string) => void }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const prev = useRef<Element | null>(null);

  useEffect(() => {
    if (open) {
      prev.current = document.activeElement;
      setQ("");
      setSel(0);
      setTimeout(() => input.current?.focus(), 10);
    } else if (prev.current instanceof HTMLElement) prev.current.focus();
  }, [open]);

  const list = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const hits = actions
      .map((a) => ({ a, s: Math.max(score(needle, a.label), score(needle, a.group) && needle ? 0.5 : 0) }))
      .filter((x) => x.s > 0)
      .sort((x, y) => y.s - x.s)
      .map((x) => x.a)
      .slice(0, 12);
    if (q.trim().length > 2) hits.push({ id: "__ask", label: `Ask J.A.R.V.I.S.: “${q.trim()}”`, group: "Command", icon: Sparkles, color: "#22d3ee", run: () => onAsk(q.trim()) });
    return hits;
  }, [q, actions, onAsk]);

  useEffect(() => setSel(0), [q]);
  if (!open) return null;

  const go = (a?: PaletteAction) => {
    if (!a) return;
    onClose();
    a.run();
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-start justify-center bg-black/50 p-4 pt-[12vh] backdrop-blur-sm" onMouseDown={onClose} role="presentation">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="panel view-enter w-full max-w-xl overflow-hidden !border-cyan-400/40 shadow-[0_0_60px_-10px_var(--color-glow)]"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
          else if (e.key === "ArrowDown") {
            e.preventDefault();
            setSel((s) => Math.min(list.length - 1, s + 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setSel((s) => Math.max(0, s - 1));
          } else if (e.key === "Enter") {
            e.preventDefault();
            go(list[sel]);
          }
        }}
      >
        <div className="flex items-center gap-2 border-b border-[var(--color-line)] px-4 py-3">
          <Search size={16} className="text-cyan-300" />
          <input
            ref={input}
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Jump to a tab, talk to an agent, or type a request…"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-[var(--color-mute)]"
            aria-label="Search commands"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-activedescendant={list[sel] ? `pal-${list[sel].id}` : undefined}
          />
          <kbd className="chip">Esc</kbd>
        </div>
        <ul id="palette-list" role="listbox" className="max-h-[50vh] overflow-y-auto p-2">
          {list.map((a, i) => {
            const Icon = a.icon;
            return (
              <li
                key={a.id}
                id={`pal-${a.id}`}
                role="option"
                aria-selected={i === sel}
                onMouseEnter={() => setSel(i)}
                onClick={() => go(a)}
                className={`flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm ${i === sel ? "bg-cyan-400/10 text-[var(--color-ink)] ring-1 ring-cyan-400/30" : "text-[var(--color-mute)]"}`}
              >
                {Icon ? <Icon size={15} style={{ color: a.color }} /> : <span className="w-[15px]" />}
                <span className="min-w-0 flex-1 truncate">{a.label}</span>
                {a.hint && <span className="text-[11px] text-[var(--color-mute)]">{a.hint}</span>}
                <span className="hud-label text-[var(--color-mute)]">{a.group}</span>
                {i === sel && <CornerDownLeft size={12} className="text-cyan-300" />}
              </li>
            );
          })}
          {!list.length && <li className="px-3 py-6 text-center text-sm text-[var(--color-mute)]">No match. Keep typing to send it to J.A.R.V.I.S.</li>}
        </ul>
      </div>
    </div>
  );
}
