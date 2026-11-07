"use client";

import { useCallback, useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import type { Brand } from "@/lib/types";
import { errorText } from "@/lib/errors";

/** Header switch between brands: the active brand scopes agents, queue, analytics and campaigns. */
export function BrandSwitcher({ onChange }: { onChange: () => void }) {
  const { client, notify } = useStark();
  const [brands, setBrands] = useState<Brand[]>([]);
  const [failed, setFailed] = useState(false);
  const load = useCallback(() => {
    client
      .get<{ brands: Brand[] }>("/api/brands")
      .then((r) => {
        setBrands(r.brands);
        setFailed(false);
      })
      .catch(() => setFailed(true));
  }, [client]);
  useEffect(() => {
    load();
    window.addEventListener("stark:brands-changed", load);
    return () => window.removeEventListener("stark:brands-changed", load);
  }, [load]);
  if (failed && brands.length === 0) {
    return (
      <button type="button" className="btn !py-1.5 text-xs" onClick={load} title="Brands could not be loaded">
        Brands unavailable · Retry
      </button>
    );
  }
  if (brands.length === 0) return null;
  const active = brands.find((b) => b.active);

  async function pick(id: string) {
    try {
      await client.post("/api/brands/active", { id: id || null });
      load();
      onChange();
    } catch (e: unknown) {
      notify("error", errorText(e, "Could not change the brand."));
    }
  }

  return (
    <select
      aria-label="Active brand"
      className="input !w-auto !py-1.5 text-xs"
      style={active ? { borderColor: active.color } : undefined}
      value={active?.id || ""}
      onChange={(e) => pick(e.target.value)}
    >
      <option value="">All brands</option>
      {brands.map((b) => (
        <option key={b.id} value={b.id}>Brand: {b.name}</option>
      ))}
    </select>
  );
}
