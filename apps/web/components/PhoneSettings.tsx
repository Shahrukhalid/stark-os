"use client";

import { BellRing, Send, Smartphone } from "lucide-react";
import { useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import { Section } from "./ui";

/** Settings section: Telegram / Discord notifications and installing the dashboard as an app. */
export function PhoneSettings() {
  const { client, notify } = useStark();
  const [st, setSt] = useState<{ telegram: boolean; discord: boolean; digest_hour: number } | null>(null);
  useEffect(() => {
    client.get("/api/notify/status").then(setSt).catch(() => {});
  }, [client]);
  const act = (path: string, ok: string) => client.post(path).then(() => notify("success", ok), (e) => notify("error", e.message));
  const on = st && (st.telegram || st.discord);

  return (
    <Section title="Phone notifications" right={<Smartphone size={15} className="text-cyan-300" />}>
      <div className="flex flex-wrap gap-2 text-xs">
        <span className="chip" style={{ color: st?.telegram ? "#34d399" : undefined }}>Telegram: {st?.telegram ? "connected" : "off"}</span>
        <span className="chip" style={{ color: st?.discord ? "#34d399" : undefined }}>Discord: {st?.discord ? "connected" : "off"}</span>
        {st && <span className="chip">Daily digest at {String(st.digest_hour).padStart(2, "0")}:00</span>}
      </div>
      <p className="mt-2 text-sm text-[var(--color-mute)]">
        Approvals, new drafts and urgent mentions are sent to your phone. On Telegram you can press <b>Approve</b>, <b>Reject</b>, <b>Publish</b> or <b>Discard</b> right in the message; a button only acts on the exact text it showed.
      </p>
      {!on && (
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-[var(--color-mute)]">
          <li>In Telegram, talk to <span className="font-mono">@BotFather</span>, send <span className="font-mono">/newbot</span> and copy the token.</li>
          <li>Send your new bot any message, then open <span className="font-mono break-anywhere">https://api.telegram.org/bot&lt;token&gt;/getUpdates</span> and copy <span className="font-mono">chat.id</span>.</li>
          <li>
            Add <span className="font-mono">TELEGRAM_BOT_TOKEN</span> and <span className="font-mono">TELEGRAM_CHAT_ID</span> (or <span className="font-mono">DISCORD_WEBHOOK_URL</span>) to <span className="font-mono">.env</span> and restart STARK OS.
          </li>
        </ol>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn text-xs" disabled={!on} onClick={() => act("/api/notify/test", "Test message sent")}>
          <Send size={13} /> Send a test
        </button>
        <button className="btn text-xs" disabled={!on} onClick={() => act("/api/notify/digest", "Digest sent")}>
          <BellRing size={13} /> Send today&apos;s digest
        </button>
      </div>
      <p className="mt-3 text-xs text-[var(--color-mute)]">
        Install the dashboard as an app: in Chrome or Edge choose <i>Install STARK OS</i> in the address bar; in Safari choose <i>Add to Dock</i> or <i>Add to Home Screen</i>.
      </p>
    </Section>
  );
}
