"use client";

import { useCallback, useEffect, useState } from "react";
import { ConnectScreen } from "@/components/ConnectScreen";
import { Shell } from "@/components/Shell";
import { loadConnection, saveConnection, type Connection } from "@/lib/api";
import { StarkProvider } from "@/lib/store";

export default function Home() {
  const [conn, setConn] = useState<Connection | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setConn(loadConnection());
    setReady(true);
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
  return (
    <StarkProvider conn={conn} onAuthError={signOut}>
      <Shell onSignOut={signOut} />
    </StarkProvider>
  );
}
