"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { DocumentViewer } from "@/components/DocumentViewer";
import { DraftsPanel } from "@/components/DraftsPanel";
import { EligibilityPanel } from "@/components/EligibilityPanel";
import { InsightsPanel } from "@/components/InsightsPanel";
import { Shell } from "@/components/Shell";
import { TimelineChart } from "@/components/TimelineChart";
import { Card, ErrorBox, Loading, StatusBadge, fmtDate } from "@/components/ui";
import { api, type PersonDetail } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useI18n, type Key } from "@/lib/i18n";

type Tab = "overview" | "timeline" | "facts" | "insights" | "drafts";

export default function PrisonerPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useI18n();
  const { user } = useAuth();
  const [p, setP] = useState<PersonDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [caseId, setCaseId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [doc, setDoc] = useState<{ id: string; start: number; end: number } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = () => api<PersonDetail>(`/api/persons/${id}`).then((d) => {
    setP(d);
    setCaseId((c) => c ?? d.eligibility.cases.find((x) => x.status !== "NOT_APPLICABLE")?.case_id ?? d.case_details[0]?.id ?? null);
  }).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function upload(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setUploading(true); setError(null); setNotice(null);
    const fd = new FormData();
    fd.append("file", f);
    if (caseId) fd.append("case_id", caseId);
    try {
      const r = await api<{ duplicate: boolean; doc_type?: string; warnings?: string[]; status?: string; result_changed?: boolean; message?: string }>(
        `/api/persons/${id}/documents`, { method: "POST", body: fd });
      setNotice(r.duplicate ? r.message! : `Uploaded as ${r.doc_type}.${r.warnings?.length ? " Warnings: " + r.warnings.join(", ") : ""}`
        + (r.result_changed ? ` Eligibility changed → ${r.status}.` : ""));
      await load();
    } catch (err) { setError((err as Error).message); } finally { setUploading(false); e.target.value = ""; }
  }

  async function recompute() {
    await api(`/api/persons/${id}/recompute`, { method: "POST" });
    load();
  }

  if (error && !p) return <Shell><ErrorBox error={error} /></Shell>;
  if (!p) return <Shell><Loading /></Shell>;
  const r = p.eligibility.cases.find((c) => c.case_id === caseId);
  const detail = p.case_details.find((c) => c.id === caseId);
  const tabs: [Tab, Key][] = [["overview", "overview"], ["timeline", "timeline"], ["facts", "facts"],
    ...(p.can_see_insights ? [["insights", "insights"] as [Tab, Key]] : []), ["drafts", "drafts"]];
  const isJail = user?.role === "jail_staff";

  return (
    <Shell>
      <div className="flex flex-wrap items-start gap-4 justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold">{p.name}</h1>
          <p className="text-sm text-muted">{p.relation} {p.relative} · {p.gender} · DOB {fmtDate(p.dob)} · {p.jail} · {p.district}</p>
          {p.vulnerability.length > 0 && <p className="text-sm text-accent font-semibold">Vulnerable: {p.vulnerability.join(", ")}</p>}
          {p.name_variants.length > 0 && <p className="text-xs text-muted">Also recorded as: {p.name_variants.join(", ")}</p>}
        </div>
        <div className="flex flex-col items-end gap-2">
          <StatusBadge code={p.urgency} className="text-sm" />
          <div className="flex gap-2">
            <label className="btn btn-ghost cursor-pointer">
              {uploading ? t("uploading") : t("upload")}
              <input type="file" className="sr-only" accept=".pdf,.jpg,.jpeg,.png,.docx,.txt" onChange={upload} disabled={uploading} />
            </label>
            <button className="btn btn-ghost" onClick={recompute}>{t("recompute")}</button>
          </div>
          <p className="text-[11px] text-muted">rules {p.rule_version} · legal data {p.legal_data_version} · {new Date(p.computed_at).toLocaleString()}</p>
        </div>
      </div>
      <ErrorBox error={error} />
      {notice && <p role="status" className="card bg-ok-bg text-ok p-3 text-sm mb-3">{notice}</p>}

      {p.case_details.length > 1 && (
        <div className="flex flex-wrap gap-2 mb-3" role="tablist" aria-label="Cases">
          {p.case_details.map((c) => {
            const cr = p.eligibility.cases.find((x) => x.case_id === c.id);
            return (
              <button key={c.id} role="tab" aria-selected={c.id === caseId} onClick={() => setCaseId(c.id)}
                className={`btn ${c.id === caseId ? "btn-primary" : "btn-ghost"} !py-1`}>
                {c.case_numbers[0] ?? c.cnr} · {c.charges.map((x) => `${x.act} ${x.section}`).join(", ")}
                {cr && <StatusBadge code={cr.status} />}
              </button>
            );
          })}
        </div>
      )}

      <div role="tablist" aria-label="Sections" className="flex gap-1 border-b border-line mb-4 overflow-x-auto">
        {tabs.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px whitespace-nowrap ${tab === k ? "border-navy text-navy" : "border-transparent text-muted hover:text-ink"}`}>
            {t(label)}
          </button>
        ))}
      </div>

      {r && detail && tab === "overview" && <EligibilityPanel r={r} detail={detail} />}
      {r && detail && tab === "timeline" && (
        <div className="space-y-4">
          <Card title={t("timeline")}><TimelineChart result={r} detail={detail} /></Card>
          <Card title="Custody records">
            <ul className="text-sm space-y-1">
              {p.custody_events.map((e) => (
                <li key={e.id} className="flex flex-wrap gap-2">
                  <span className="font-medium">{e.type.replaceAll("_", " ")}</span>
                  <span>{fmtDate(e.start)} → {e.end ? fmtDate(e.end) : "ongoing"}</span>
                  {e.jail && <span className="text-muted">{e.jail}</span>}
                  {!e.primary && <span className="text-xs text-review">secondary source</span>}
                  {e.case_id && e.case_id !== caseId && <span className="text-xs text-urgent">other case</span>}
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Hearings & delay attribution">
            <table className="w-full text-sm">
              <thead className="text-left text-muted"><tr><th className="py-1">Date</th><th>Reason</th><th>Attributed to</th></tr></thead>
              <tbody>
                {detail.hearings.map((h) => (
                  <tr key={h.id} className="border-t border-line align-top">
                    <td className="py-1 pr-2 whitespace-nowrap">{fmtDate(h.date)}</td>
                    <td className="py-1 pr-2">{h.reason || <span className="text-muted">no reason recorded</span>}</td>
                    <td className="py-1 whitespace-nowrap">{h.attribution} <span className="text-xs text-muted">{Math.round(h.confidence * 100)}% {h.method}{h.verified ? " ✓" : ""}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}
      {tab === "facts" && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {p.documents.map((d) => (
              <button key={d.id} onClick={() => setDoc({ id: d.id, start: -1, end: -1 })}
                className={`btn ${doc?.id === d.id ? "btn-primary" : "btn-ghost"} !py-1 !text-xs`}>
                {d.doc_type} · {d.filename}{d.warnings.length ? " ⚠" : ""}
              </button>
            ))}
          </div>
          {doc ? <DocumentViewer docId={doc.id} focus={doc.start >= 0 ? doc : null} canCorrect={!isJail} onChanged={load} />
            : <p className="text-muted text-sm">Select a document to see its text with every extracted fact highlighted at its source.</p>}
        </div>
      )}
      {tab === "insights" && caseId && p.can_see_insights && (
        <InsightsPanel personId={p.id} caseId={caseId} onEvidence={(d, s, e) => { setDoc({ id: d, start: s, end: e }); setTab("facts"); }} />
      )}
      {tab === "drafts" && caseId && (
        <DraftsPanel personId={p.id} caseId={caseId} canDraft={p.can_draft && p.can_see_insights} superintendentOnly={isJail} />
      )}
    </Shell>
  );
}
