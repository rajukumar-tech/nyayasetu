"use client";

import { useEffect, useRef, useState } from "react";
import { api, type Fact } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ErrorBox, Loading } from "./ui";

interface Doc {
  id: string; filename: string; doc_type: string; doc_type_confidence: number; language: string; scripts: string[];
  warnings: string[]; text: string; facts: Fact[];
}

function show(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "object") return Object.entries(v as Record<string, unknown>).filter(([, x]) => x != null)
    .map(([k, x]) => `${k}: ${x}`).join(", ");
  return String(v);
}

/** Document text with every extracted fact highlighted at its source span. */
export function DocumentViewer({ docId, focus, canCorrect, onChanged }: {
  docId: string; focus?: { start: number; end: number } | null; canCorrect: boolean; onChanged?: () => void;
}) {
  const { t } = useI18n();
  const [doc, setDoc] = useState<Doc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [clicked, setActive] = useState<string | null>(null);
  const activeRef = useRef<HTMLElement | null>(null);

  const load = () => api<Doc>(`/api/documents/${docId}`).then(setDoc).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [docId]); // eslint-disable-line react-hooks/exhaustive-deps
  const focusId = doc && focus ? (doc.facts.find((x) => x.span_start === focus.start)?.id ?? "__focus") : null;
  const active = clicked ?? focusId;
  useEffect(() => { activeRef.current?.scrollIntoView({ block: "center", behavior: "smooth" }); }, [active]);

  if (error) return <ErrorBox error={error} />;
  if (!doc) return <Loading />;

  const spans = [...doc.facts.filter((f) => f.span_end > f.span_start).map((f) => ({ s: f.span_start, e: f.span_end, id: f.id })),
    ...(focus && !doc.facts.some((f) => f.span_start === focus.start) ? [{ s: focus.start, e: focus.end, id: "__focus" }] : [])]
    .sort((a, b) => a.s - b.s);
  const parts: React.ReactNode[] = [];
  let pos = 0;
  for (const sp of spans) {
    if (sp.s < pos) continue;
    parts.push(doc.text.slice(pos, sp.s));
    const isActive = sp.id === active;
    parts.push(
      <mark key={sp.id + sp.s} ref={isActive ? (el) => { activeRef.current = el; } : undefined}
        className={isActive ? "src src-active" : "src"} onClick={() => setActive(sp.id)}>
        {doc.text.slice(sp.s, sp.e)}
      </mark>,
    );
    pos = sp.e;
  }
  parts.push(doc.text.slice(pos));

  async function review(f: Fact, action: "confirm" | "correct" | "reject") {
    let value: unknown = undefined;
    if (action === "correct") {
      const v = window.prompt(`Correct value for ${f.field}`, show(f.value));
      if (v == null) return;
      value = v;
    }
    try {
      await api(`/api/facts/${f.id}`, { method: "PATCH", body: JSON.stringify({ action, value }) });
      await load();
      onChanged?.();
    } catch (e) { setError((e as Error).message); }
  }

  return (
    <div className="grid lg:grid-cols-5 gap-4">
      <div className="lg:col-span-3">
        <div className="flex flex-wrap gap-2 text-xs text-muted mb-2">
          <span className="font-semibold text-ink">{doc.filename}</span>
          <span>type: {doc.doc_type} ({Math.round(doc.doc_type_confidence * 100)}%)</span>
          <span>language: {doc.language}</span>
          {doc.warnings.map((w) => <span key={w} className="text-critical font-semibold">{w}</span>)}
        </div>
        <pre className="card p-3 whitespace-pre-wrap text-sm leading-relaxed max-h-[32rem] overflow-auto font-sans">{parts}</pre>
      </div>
      <div className="lg:col-span-2">
        <p className="label mb-2">Extracted facts ({doc.facts.length})</p>
        <ul className="space-y-2 max-h-[32rem] overflow-auto pr-1">
          {doc.facts.map((f) => (
            <li key={f.id} className={`card p-2 text-sm ${active === f.id ? "ring-2 ring-accent" : ""}`}>
              <button className="text-left w-full" onClick={() => setActive(f.id)}>
                <span className="font-semibold">{f.field}</span>: {show(f.value)}
              </button>
              <div className="text-xs text-muted flex flex-wrap gap-x-2">
                <span>{f.method}</span>
                <span className={f.confidence < 0.8 ? "text-review font-semibold" : ""}>{Math.round(f.confidence * 100)}%</span>
                <span>{f.review_status}</span>
                {f.notes.map((n) => <span key={n} className="text-urgent">{n}</span>)}
              </div>
              {canCorrect && f.review_status === "pending" && (
                <div className="flex gap-1 mt-1">
                  <button className="btn btn-ghost !py-0.5 !px-2 !text-xs" onClick={() => review(f, "confirm")}>{t("confirm")}</button>
                  <button className="btn btn-ghost !py-0.5 !px-2 !text-xs" onClick={() => review(f, "correct")}>{t("correct")}</button>
                  <button className="btn btn-danger !py-0.5 !px-2 !text-xs" onClick={() => review(f, "reject")}>{t("reject")}</button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
