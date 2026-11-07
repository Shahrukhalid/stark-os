"use client";
import { useCallback, useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import { Section } from "./ui";

type Info = { enabled: boolean; error: string | null; models: string[]; jobs: {id:string; model:string; status:string; completed:number; total:number}[]; agents:{id:string; name:string; provider:string; model:string}[] };
export function LocalModelsView() {
  const { client, notify } = useStark();
  const [info, setInfo] = useState<Info | null>(null);
  const [agent, setAgent] = useState("");
  const [model, setModel] = useState("");
  const [download, setDownload] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { setInfo(await client.get<Info>("/api/models/local")); }
    catch(e:any) { notify("error", e.message); }
  }, [client, notify]);
  useEffect(() => { void load(); }, [load]);
  const running = info?.jobs.some(j => ["queued", "downloading", "verifying"].includes(j.status));
  useEffect(() => { if (!running) return; const id = setInterval(load, 2000); return () => clearInterval(id); }, [running, load]);
  async function act(path:string, body:unknown, method:"post"|"put" = "post") {
    setBusy(true);
    try { await client[method](path, body); await load(); }
    catch(e:any) { notify("error", e.message); }
    finally { setBusy(false); }
  }
  return <Section title="Local models (Ollama)">
    <p className="text-sm">Local conversations stay with your configured Ollama service. Local failure stops the request. Cloud fallback is disabled.</p>
    {!info ? <p>Checking local provider…</p> : !info.enabled ? <p className="mt-2 text-sm">Enable Ollama with STARK_OLLAMA_URL=http://127.0.0.1:11434 and restart the API. Install Ollama separately, then choose a model whose license and hardware requirements suit your computer.</p> : <div className="mt-3 space-y-3">
      {info.error && <p role="alert">{info.error}</p>}
      <button className="btn" onClick={load}>Refresh installed models</button>
      <div className="flex flex-wrap gap-2">
        <select aria-label="Agent for local model" value={agent} onChange={e=>setAgent(e.target.value)}><option value="">Choose agent</option>{info.agents.map(a=><option key={a.id} value={a.id}>{a.name} ({a.provider})</option>)}</select>
        <select aria-label="Installed local model" value={model} onChange={e=>setModel(e.target.value)}><option value="">Choose installed model</option>{info.models.map(m=><option key={m}>{m}</option>)}</select>
        <button className="btn" disabled={busy || !agent || !model} onClick={()=>act("/api/models/local/selection", {agent, provider:"ollama", model}, "put")}>Use local model</button>
      </div>
      <p className="text-xs">Downloads use your internet connection and disk space. Default limit is 4 GiB. Review the model publisher’s license before proceeding. Cancelling stops this client request; Ollama may retain cached partial layers.</p>
      <input aria-label="Model to download" placeholder="Model name, for example qwen3:0.6b" value={download} onChange={e=>{setDownload(e.target.value);setReviewed(false);}} />
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={reviewed} onChange={e=>setReviewed(e.target.checked)} />I reviewed this model’s license and approve downloading it.</label>
      <button className="btn" disabled={busy || running || !download || !reviewed} onClick={()=>act("/api/models/local/downloads", {model:download, license_reviewed:reviewed})}>Download model</button>
      {info.jobs.map(j=><div key={j.id} className="text-sm">{j.model} — {j.status} {j.total>0 && `${Math.round(j.completed / j.total * 100)}%`}{["queued","downloading","verifying"].includes(j.status) && <button className="btn ml-2" disabled={busy} onClick={()=>act(`/api/models/local/downloads/${j.id}/cancel`, {})}>Cancel</button>}</div>)}
    </div>}
  </Section>;
}
