"use client";

import { AlertTriangle, CheckCircle2, PlugZap, RefreshCw, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { isDesktop } from "@/lib/api";
import { useStark } from "@/lib/store";
import { Section } from "./ui";

export type HealthEntry = { platform: string; status: "ok" | "warning" | "error"; message: string; failed_recently: number; checked_at: string };
export type HealthReport = { accounts: HealthEntry[]; overall: "ok" | "warning" | "error"; needs_attention: string[]; checked_at: string | null };

const ICON = { ok: CheckCircle2, warning: AlertTriangle, error: XCircle };
const TONE = { ok: "text-emerald-300", warning: "text-amber-300", error: "text-red-400" };

/** Connected accounts checked without posting; broken ones get a Reconnect button. */
export function AccountHealth({ onReconnect }: { onReconnect: () => void }) {
  const { client, notify } = useStark();
  const [report, setReport] = useState<HealthReport | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    client.get<HealthReport>("/api/social/health").then(setReport).catch(() => {});
  }, [client]);

  const check = useCallback(async () => {
    setBusy(true);
    try {
      setReport(await client.post<HealthReport>("/api/social/health/check"));
    } catch (e: any) {
      notify("error", e.message);
    } finally {
      setBusy(false);
    }
  }, [client, notify]);

  const reconnect = () => (isDesktop() ? window.dispatchEvent(new Event("stark:desktop-setup")) : onReconnect());
  const accounts = report?.accounts || [];

  return (
    <Section
      title="Account health"
      right={
        <button className="btn !py-1 text-xs" onClick={check} disabled={busy} aria-label="Check accounts now">
          <RefreshCw size={12} className={`mr-1 inline ${busy ? "animate-spin" : ""}`} /> {busy ? "Checking…" : "Check now"}
        </button>
      }
    >
      {accounts.length === 0 ? (
        <p className="text-sm text-[var(--color-mute)]">
          {report?.checked_at ? "No accounts connected yet." : "Connected accounts are checked every 6 hours without posting. Press Check now to run it."}
        </p>
      ) : (
        <ul className="space-y-2">
          {accounts.map((a) => {
            const Icon = ICON[a.status];
            return (
              <li key={a.platform} className="flex items-start gap-2 rounded-lg border border-[var(--color-line)] p-2 text-sm">
                <Icon size={16} className={`mt-0.5 shrink-0 ${TONE[a.status]}`} aria-label={a.status} />
                <span className="min-w-0 flex-1">
                  <span className="block font-medium capitalize">{a.platform}</span>
                  <span className="break-anywhere block text-xs text-[var(--color-mute)]">{a.message}</span>
                </span>
                {a.status === "error" && (
                  <button className="btn btn-primary !py-1 text-xs" onClick={reconnect}>
                    <PlugZap size={12} className="mr-1 inline" /> Reconnect
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {report?.checked_at && <p className="mt-2 text-xs text-[var(--color-mute)]">Last check: {new Date(report.checked_at).toLocaleString()}</p>}
    </Section>
  );
}

export function healthSummary(r: HealthReport | null): string {
  if (!r || !r.accounts.length) return "";
  return r.overall === "ok" ? "All accounts working" : r.needs_attention.length ? `Needs reconnecting: ${r.needs_attention.join(", ")}` : "Some accounts have warnings";
}
