"use client";

import { Download, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useStark } from "@/lib/store";
import { errorText } from "@/lib/errors";

type Info = {
  current: string;
  latest: string | null;
  update: boolean;
  url: string;
  notes: string;
  asset: { name: string; size: number } | null;
};
type Progress = { status: "idle" | "downloading" | "ready" | "error"; done: number; total: number; path: string | null; error: string | null };

const SKIP_KEY = "stark.update.skip";
const RECHECK_MS = 6 * 60 * 60 * 1000;

function skipped(): string | null {
  try {
    return localStorage.getItem(SKIP_KEY);
  } catch {
    return null;
  }
}

/** Desktop app: asks when a new release is out (on start and every 6 hours), downloads the right installer and opens it.
 *  Settings → "Check for updates" dispatches `stark:check-update` to check right away. */
export function UpdatePrompt() {
  const { client, notify } = useStark();
  const [info, setInfo] = useState<Info | null>(null);
  const [prog, setProg] = useState<Progress | null>(null);
  const snoozed = useRef<string | null>(null);
  const isMac = typeof navigator !== "undefined" && /Mac/i.test(navigator.userAgent);

  const check = useCallback(
    async (manual: boolean) => {
      try {
        const i = await client.get<Info>("/api/desktop/update");
        if (!i.latest) {
          if (manual) notify("error", "Could not reach the update server. Check your internet connection.");
          return;
        }
        if (!i.update) {
          if (manual) notify("success", `You have the latest version (${i.current}).`);
          return;
        }
        if (manual || (skipped() !== i.latest && snoozed.current !== i.latest)) setInfo(i);
      } catch (e: unknown) {
        if (manual) notify("error", errorText(e, "Could not check for updates."));
      }
    },
    [client, notify],
  );

  useEffect(() => {
    const first = setTimeout(() => check(false), 5000);
    const every = setInterval(() => check(false), RECHECK_MS);
    const manual = () => check(true);
    window.addEventListener("stark:check-update", manual);
    return () => {
      clearTimeout(first);
      clearInterval(every);
      window.removeEventListener("stark:check-update", manual);
    };
  }, [check]);

  useEffect(() => {
    if (prog?.status !== "downloading") return;
    const t = setInterval(() => {
      client.get<Progress>("/api/desktop/update/progress").then(setProg).catch(() => {});
    }, 700);
    return () => clearInterval(t);
  }, [client, prog?.status]);

  async function install() {
    try {
      setProg(await client.post<Progress>("/api/desktop/update/download", {}));
    } catch (e: unknown) {
      notify("error", errorText(e, "Could not start the download."));
    }
  }

  function close(skip: boolean) {
    if (info?.latest) {
      snoozed.current = info.latest;
      if (skip) {
        try {
          localStorage.setItem(SKIP_KEY, info.latest);
        } catch {
          /* private mode: skip only for this session */
        }
      }
    }
    setInfo(null);
    setProg(null);
  }

  if (!info) return null;
  const pct = prog && prog.total ? Math.min(100, Math.round((prog.done / prog.total) * 100)) : 0;
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm" role="presentation">
      <div role="dialog" aria-modal="true" aria-label="Update available" className="panel view-enter w-full max-w-lg p-5">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="hud-label text-cyan-300">Update available</div>
            <h2 className="mt-1 text-lg font-semibold">STARK AI {info.latest}</h2>
            <p className="text-xs text-[var(--color-mute)]">You have {info.current}.</p>
          </div>
          <button className="btn !p-1.5" aria-label="Close" onClick={() => close(false)}>
            <X size={14} />
          </button>
        </div>
        {info.notes && (
          <pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-[var(--color-line)] p-3 text-xs text-[var(--color-mute)]">
            {info.notes}
          </pre>
        )}
        {prog?.status === "downloading" && (
          <div className="mt-4" aria-live="polite">
            <div className="h-2 overflow-hidden rounded bg-[var(--color-line)]">
              <div className="h-full bg-cyan-400 transition-all" style={{ width: `${pct}%` }} />
            </div>
            <p className="mt-1 text-xs text-[var(--color-mute)]">Downloading {info.asset?.name}… {pct}%</p>
          </div>
        )}
        {prog?.status === "ready" && (
          <p className="mt-4 text-sm" role="status">
            {isMac
              ? "The installer is open. Quit STARK AI, drag the new STARK AI onto Applications (replace the old one), then open it again."
              : "The installer is open. Follow its steps; it closes STARK AI and starts the new version."}
            <span className="mt-1 block text-xs text-[var(--color-mute)]">Saved to {prog.path}</span>
          </p>
        )}
        {prog?.status === "error" && (
          <p className="mt-4 text-sm text-red-400" role="alert">Download failed: {prog.error}</p>
        )}
        <div className="mt-5 flex flex-wrap gap-2">
          {info.asset && prog?.status !== "ready" && (
            <button className="btn btn-primary" onClick={install} disabled={prog?.status === "downloading"}>
              <Download size={14} /> {prog?.status === "downloading" ? "Downloading…" : prog?.status === "error" ? "Try again" : "Download and install"}
            </button>
          )}
          {!info.asset && (
            <a className="btn btn-primary" href={info.url} target="_blank" rel="noreferrer">
              <Download size={14} /> Open the download page
            </a>
          )}
          <button className="btn" onClick={() => close(false)}>Later</button>
          {prog?.status !== "ready" && (
            <button className="btn ml-auto" onClick={() => close(true)}>Skip this version</button>
          )}
        </div>
      </div>
    </div>
  );
}
