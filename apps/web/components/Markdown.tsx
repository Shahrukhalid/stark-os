"use client";

import { Fragment, useMemo } from "react";
import { parseMarkdown, type Inline } from "@/lib/markdown";

function Inlines({ nodes }: { nodes: Inline[] }) {
  return (
    <>
      {nodes.map((n, i) => {
        switch (n.t) {
          case "text":
            return <Fragment key={i}>{n.v}</Fragment>;
          case "code":
            return <code key={i}>{n.v}</code>;
          case "strong":
            return <strong key={i} className="font-semibold text-white"><Inlines nodes={n.c} /></strong>;
          case "em":
            return <em key={i}><Inlines nodes={n.c} /></em>;
          case "link":
            return (
              <a key={i} href={n.href} target="_blank" rel="noreferrer noopener" className="text-cyan-300 underline-offset-2 hover:underline">
                <Inlines nodes={n.c} />
              </a>
            );
        }
      })}
    </>
  );
}

/** Renders agent output as formatted text. Builds React elements only: no HTML injection is possible. */
export function Markdown({ text, className = "" }: { text: string; className?: string }) {
  const blocks = useMemo(() => parseMarkdown(text), [text]);
  return (
    <div className={`md break-anywhere ${className}`}>
      {blocks.map((b, i) => {
        switch (b.t) {
          case "h":
            return <p key={i} className="mt-3 mb-1 font-semibold text-white first:mt-0"><Inlines nodes={b.c} /></p>;
          case "hr":
            return <hr key={i} className="my-3 border-[var(--color-line)]" />;
          case "pre":
            return <pre key={i} className="my-2 overflow-x-auto rounded-lg bg-black/40 p-3 font-mono text-xs"><code>{b.v}</code></pre>;
          case "ul":
          case "ol": {
            const Tag = b.t;
            return (
              <Tag key={i} className={`my-1.5 space-y-0.5 pl-5 ${b.t === "ul" ? "list-disc" : "list-decimal"}`}>
                {b.items.map((it, j) => <li key={j}><Inlines nodes={it} /></li>)}
              </Tag>
            );
          }
          case "quote":
            return (
              <blockquote key={i} className="my-2 border-l-2 border-cyan-400/40 pl-3 text-[var(--color-mute)]">
                {b.lines.map((l, j) => <p key={j}><Inlines nodes={l} /></p>)}
              </blockquote>
            );
          case "table":
            return (
              <div key={i} className="my-2 overflow-x-auto">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr>{b.head.map((c, j) => <th key={j} className="border-b border-[var(--color-line-strong)] px-2 py-1 text-left font-semibold"><Inlines nodes={c} /></th>)}</tr>
                  </thead>
                  <tbody>
                    {b.rows.map((r, j) => (
                      <tr key={j}>{r.map((c, k) => <td key={k} className="border-b border-[var(--color-line)] px-2 py-1 align-top"><Inlines nodes={c} /></td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "p":
            return (
              <p key={i} className="my-1.5 first:mt-0 last:mb-0">
                {b.lines.map((l, j) => (
                  <Fragment key={j}>
                    {j > 0 && <br />}
                    <Inlines nodes={l} />
                  </Fragment>
                ))}
              </p>
            );
        }
      })}
    </div>
  );
}
