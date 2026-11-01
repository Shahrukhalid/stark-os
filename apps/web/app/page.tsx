"use client";

import { useCallback, useEffect, useState } from "react";
import { ConnectScreen } from "@/components/ConnectScreen";
import { DesktopSetup } from "@/components/DesktopSetup";
import { Shell } from "@/components/Shell";
import { isDesktop, loadConnection, saveConnection, StarkClient, type Connection } from "@/lib/api";
import { StarkProvider } from "@/lib/store";

export default function Home() {
  const [conn, setConn] = useState<Connection | null>(null);
  const [ready, setReady] = useState(false);
  const [setup, setSetup] = useState<"no" | "first" | "manual">("no");

  useEffect(() => {
    const c = loadConnection();
    setConn(c);
    if (c && isDesktop()) {
      // Desktop app: run the setup wizard until an AI key is saved; Settings can open it again later.
      new StarkClient(c)
        .get<{ needs_setup: boolean }>("/api/desktop/status")
        .then((s) => setSetup(s.needs_setup ? "first" : "no"))
        .catch(() => setSetup("no"))
        .finally(() => setReady(true));
    } else setReady(true);
    const open = () => setSetup("manual");
    window.addEventListener("stark:desktop-setup", open);
    return () => window.removeEventListener("stark:desktop-setup", open);
  }, []);

  const signOut = useCallback(() => {
    saveConnection(null);
    setConn(null);
  }, []);

  if (!ready) return null;
  if (!conn)
    return (
      <ConnectScreen
        onConnect={(c) => {
          saveConnection(c);
          setConn(c);
        }}
      />
    );
  if (setup !== "no")
    return (
      <DesktopSetup
        conn={conn}
        canSkip={setup === "manual"}
        onDone={() => (setup === "first" ? window.location.reload() : setSetup("no"))}
      />
    );
  return (
    <StarkProvider conn={conn} onAuthError={signOut}>
      <Shell onSignOut={signOut} />
    </StarkProvider>
  );
}
