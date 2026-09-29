"use client";

import { useEffect, useState } from "react";
import { api, type Insight } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Card, ErrorBox, Loading, Severity } from "./ui";

const CAT: Record<string, string> = {
  A: "Arrest safeguards", B: "Investigation & evidence", C: "Charge-level", D: "Faster exits & release routes",
  E: "Delay & fundamental rights", F: "Similar judgments",
};

export function InsightsPanel({ personId, caseId, onEvidence }: {
  personId: string; caseId: string; onEvidence: (docId: string, start: number, end: number) => void;
}) {
  const { t } = useI18n();
  const [data, setData] = useState<{ disclaimer: string; insights: Insight[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => api<{ disclaimer: string; insights: Insight[] }>(`/api/persons/${personId}/insights`).then(setData)
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, [personId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function decide(i: Insight, status: "accepted" | "rejected" | "new") {
    await api(`/api/insights/${i.id}`, { method: "PATCH", body: JSON.stringify({ status }) });
    load();
  }

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const items = data.insights.filter((i) => i.case_id === caseId);
  return (
    <div className="space-y-3">
      <p className="card bg-urgent-bg border-urgent/30 text-urgent text-sm p-3" role="note">
        <strong>Privileged — assigned lawyer only.</strong> {data.disclaimer} Every view is audit-logged.
        Accept an insight to use it in a draft.
      </p>
      {items.length === 0 && <p className="text-muted">{t("noItems")}</p>}
      {items.map((i) => (
        <Card key={i.id} className={i.status === "rejected" ? "opacity-60" : ""}>
          <div className="flex flex-wrap items-start gap-2 justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <Severity level={i.severity} />
                <span className="label">{i.category} · {CAT[i.category]}</span>
                {i.status !== "new" && <span className={`text-xs font-semibold ${i.status === "accepted" ? "text-ok" : "text-muted"}`}>{i.status}</span>}
              </div>
              <h3 className="font-semibold mt-1">{i.title}</h3>
            </div>
            <div className="flex gap-1">
              {i.status !== "accepted" && <button className="btn btn-primary !py-1" onClick={() => decide(i, "accepted")}>{t("accept")}</button>}
              {i.status !== "rejected" && <button className="btn btn-ghost !py-1" onClick={() => decide(i, "rejected")}>{t("reject")}</button>}
              {i.status !== "new" && <button className="btn btn-ghost !py-1" onClick={() => decide(i, "new")}>Undo</button>}
            </div>
          </div>
          <p className="text-sm mt-2">{i.explanation}</p>
          <p className="text-sm mt-2"><span className="label">{t("nextSteps")}: </span>{i.next_steps}</p>
          <div className="mt-3">
            <p className="label mb-1">{t("evidence")}</p>
            <ul className="flex flex-wrap gap-2">
              {i.evidence.map((e, k) => (
                <li key={k}>
                  <button onClick={() => onEvidence(e.document_id, e.start, e.end)}
                    className="text-xs border border-line rounded-md px-2 py-1 bg-paper hover:bg-neutral-bg text-left">
                    <span className="font-semibold">{e.doc_type || "document"}</span> p.{e.page}: “{e.text || "(blank field)"}”
                  </button>
                </li>
              ))}
            </ul>
          </div>
          {i.legal_basis.length > 0 && <p className="text-xs text-muted mt-2">Legal basis (verify): {i.legal_basis.join("; ")}</p>}
          {i.judgments.length > 0 && (
            <details className="mt-2">
              <summary className="text-sm cursor-pointer text-navy-2">{t("similarJudgments")} ({i.judgments.length})</summary>
              <ul className="mt-2 space-y-2">
                {i.judgments.map((j) => (
                  <li key={j.id} className="border-l-4 border-line pl-3 text-sm">
                    <div className="font-semibold">
                      {j.citation} <span className="font-normal text-muted">· {j.court}</span>
                      {j.synthetic && <span className="ml-2 text-xs text-critical font-semibold">SYNTHETIC TEST PASSAGE — not a real judgment</span>}
                    </div>
                    {j.url ? <a href={j.url} className="text-xs underline" target="_blank" rel="noreferrer">source</a>
                      : <span className="text-xs text-muted">no source link (test corpus)</span>}
                    <p className="text-muted mt-1">{j.passage}</p>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </Card>
      ))}
    </div>
  );
}
