"use client";

import { useEffect, useState } from "react";
import { DocumentViewer } from "@/components/DocumentViewer";
import { Shell } from "@/components/Shell";
import { Card, ErrorBox, Loading } from "@/components/ui";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

interface Item { id: string; kind: string; ref_id: string; title: string; confidence: number; created_at: string;
  payload: Record<string, unknown> }

const KINDS: [string, string][] = [["", "All"], ["extraction", "Extractions"], ["delay_attribution", "Delay attribution"],
  ["identity_match", "Identity matches"], ["document_mismatch", "Document mismatches"], ["document_type", "Document type"]];
const ATTR = ["accused", "prosecution", "court", "both", "other", "unknown"];

export default function Reviewer() {
  const { t } = useI18n();
  const [items, setItems] = useState<Item[] | null>(null);
  const [kind, setKind] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Item | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = () => api<Item[]>(`/api/review${kind ? `?kind=${kind}` : ""}`).then(setItems).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [kind]); // eslint-disable-line react-hooks/exhaustive-deps

  async function resolve(item: Item, action: string, value?: unknown) {
    try {
      await api(`/api/review/${item.id}/resolve`, { method: "POST", body: JSON.stringify({ action, value }) });
      setOpen(null); load();
    } catch (e) { setError((e as Error).message); }
  }
  async function scan() {
    const r = await api<{ candidates: number }>("/api/resolution/scan", { method: "POST" });
    setMsg(`${r.candidates} new identity-match candidate pair(s) queued. Nothing is merged without review.`);
    load();
  }

  return (
    <Shell roles={["reviewer"]}>
      <div className="flex flex-wrap justify-between gap-2 mb-4">
        <h1 className="text-2xl font-bold">{t("review")}</h1>
        <button className="btn btn-ghost" onClick={scan}>Scan for duplicate identities</button>
      </div>
      <ErrorBox error={error} />
      {msg && <p role="status" className="card bg-ok-bg text-ok p-3 text-sm mb-3">{msg}</p>}
      <div className="flex flex-wrap gap-1 mb-3" role="group" aria-label="Filter by kind">
        {KINDS.map(([k, l]) => <button key={k} aria-pressed={kind === k} onClick={() => setKind(k)}
          className={`btn ${kind === k ? "btn-primary" : "btn-ghost"} !py-1 !text-xs`}>{l}</button>)}
      </div>
      {!items ? <Loading /> : items.length === 0 ? <p className="text-muted">{t("noItems")}</p> : (
        <div className="grid lg:grid-cols-2 gap-4">
          <ul className="space-y-2">
            {items.map((i) => (
              <li key={i.id}>
                <button onClick={() => setOpen(i)} className={`card p-3 w-full text-left ${open?.id === i.id ? "ring-2 ring-accent" : ""}`}>
                  <div className="flex justify-between gap-2 text-xs"><span className="label">{i.kind.replaceAll("_", " ")}</span>
                    <span className={i.confidence < 0.5 ? "text-critical" : "text-review"}>{Math.round(i.confidence * 100)}%</span></div>
                  <div className="text-sm mt-1">{i.title}</div>
                </button>
              </li>
            ))}
          </ul>
          <div className="lg:sticky lg:top-4 self-start">
            {open && (
              <Card title={open.title}>
                {open.kind === "delay_attribution" && (
                  <div className="space-y-2 text-sm">
                    <p>Order-sheet entry: “{String(open.payload.reason_text ?? "")}”</p>
                    <p className="text-muted">Suggested: <strong>{String(open.payload.suggested)}</strong> via {String(open.payload.method)}.
                      Only delay caused by the accused is excluded from detention. Non-production by the jail is NOT the accused&apos;s delay.</p>
                    <div className="flex flex-wrap gap-1">
                      {ATTR.map((a) => <button key={a} className="btn btn-ghost !py-1" onClick={() => resolve(open, "set_attribution", a)}>{a}</button>)}
                    </div>
                  </div>
                )}
                {open.kind === "extraction" && (
                  <div className="space-y-3">
                    <DocumentViewer docId={String(open.payload.document_id)} canCorrect={false} />
                    <div className="flex gap-2">
                      <button className="btn btn-primary" onClick={() => resolve(open, "confirm")}>{t("confirm")}</button>
                      <button className="btn btn-ghost" onClick={() => { const v = window.prompt("Correct value"); if (v != null) resolve(open, "correct", v); }}>{t("correct")}</button>
                      <button className="btn btn-danger" onClick={() => resolve(open, "reject")}>{t("reject")}</button>
                    </div>
                  </div>
                )}
                {open.kind === "identity_match" && (
                  <div className="space-y-2 text-sm">
                    <p>Model decision: <strong>{String(open.payload.decision)}</strong>
                      {(open.payload.vetoes as string[])?.length ? <> · vetoes: <span className="text-critical">{(open.payload.vetoes as string[]).join(", ")}</span></> : null}</p>
                    <table className="text-xs w-full"><tbody>
                      {Object.entries(open.payload.features as Record<string, number>).map(([k, v]) =>
                        <tr key={k} className="border-t border-line"><td className="py-0.5">{k}</td><td className="text-right tabular-nums">{v.toFixed(2)}</td></tr>)}
                    </tbody></table>
                    <p className="text-urgent text-xs">A false merge can make someone look like a repeat offender. Link only if you are sure; merges can be undone.</p>
                    <div className="flex gap-2">
                      <button className="btn btn-primary" onClick={() => resolve(open, "link")}>Same person — link</button>
                      <button className="btn btn-ghost" onClick={() => resolve(open, "not_same")}>Different people</button>
                    </div>
                  </div>
                )}
                {["document_mismatch", "document_type", "document"].includes(open.kind) && (
                  <div className="space-y-2 text-sm">
                    <pre className="whitespace-pre-wrap text-xs bg-paper p-2 rounded">{JSON.stringify(open.payload, null, 1)}</pre>
                    <div className="flex gap-2">
                      <button className="btn btn-primary" onClick={() => resolve(open, "confirm")}>Resolved</button>
                      <button className="btn btn-ghost" onClick={() => resolve(open, "reject")}>Dismiss</button>
                    </div>
                  </div>
                )}
              </Card>
            )}
          </div>
        </div>
      )}
    </Shell>
  );
}
