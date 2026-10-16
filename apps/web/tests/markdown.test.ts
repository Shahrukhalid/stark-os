import { describe, expect, it } from "vitest";
import { parseInline, parseMarkdown, safeHref } from "../lib/markdown";

describe("safe markdown", () => {
  it("only keeps http(s) links", () => {
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,x")).toBeNull();
    expect(safeHref("https://example.com/a")).toBe("https://example.com/a");
    const nodes = parseInline("[click](javascript:alert(1)) and [ok](https://example.com)");
    expect(nodes.filter((n) => n.t === "link")).toHaveLength(1);
    expect(nodes[0]).toEqual({ t: "text", v: "click" });
  });

  it("parses the blocks agents use", () => {
    const b = parseMarkdown("## Plan\n**Hook:** go\n\n- one\n- two\n\n1. a\n2. b\n\n---\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```\ncode <b>\n```\n> quote");
    expect(b.map((x) => x.t)).toEqual(["h", "p", "ul", "ol", "hr", "table", "pre", "quote"]);
    const pre = b.find((x) => x.t === "pre");
    expect(pre && pre.t === "pre" && pre.v).toBe("code <b>");
  });

  it("links bare URLs without trailing punctuation and never hangs on odd input", () => {
    const n = parseInline("see https://example.com/x.");
    expect(n.some((x) => x.t === "link" && x.href === "https://example.com/x")).toBe(true);
    expect(() => parseMarkdown("***\n|\n|-|\n* \n**unclosed\n`x".repeat(50))).not.toThrow();
  });
});
