"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { DocumentViewer } from "@/components/DocumentViewer";
import { DraftsPanel } from "@/components/DraftsPanel";
import { EligibilityPanel } from "@/components/EligibilityPanel";
import { InsightsPanel } from "@/components/InsightsPanel";
import { Shell } from "@/components/Shell";
import { TimelineChart } from "@/components/TimelineChart";
import { Card, DemoBadge, ErrorBox, Field, Loading, Notice, StatusBadge, inputCls } from "@/components/ui";
import { api, type PersonDetail } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { apiErrorText, useI18n, type Key } from "@/lib/i18n";

type Tab = "overview" | "timeline" | "facts" | "insights" | "drafts";
type Upload = { duplicate: boolean; doc_type?: string; warnings?: string[]; status?: string; result_changed?: boolean };

export default function PrisonerPage() {
  const { id } = useParams<{ id: string }>();
  const { t, ts, tk, fd, fdt } = useI18n();
  const { user } = useAuth();
  const [p, setP] = useState<PersonDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [caseId, setCaseId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [doc, setDoc] = useState<{ id: string; start: number; end: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"transfer" | "release" | null>(null);

  const load = () => api<PersonDetail>(`/api/persons/${id}`).then((d) => {
    setP(d);
    setCaseId((c) => c ?? d.eligibility.cases.find((x) => x.status !== "NOT_APPLICABLE")?.case_id ?? d.case_details[0]?.id ?? null);
  }).catch((e) => setError(apiErrorText(t, e)));
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function upload(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setBusy(true); setError(null); setNotice(null);
    const fd_ = new FormData();
    fd_.append("file", f);
    if (caseId) fd_.append("case_id", caseId);
    try {
      const r = await api<Upload>(`/api/persons/${id}/documents`, { method: "POST", body: fd_ });
      if (r.duplicate) setNotice(t("duplicateUpload"));
      else {
        const w = (r.warnings ?? []).map((x) => tk("warn_", x.replace(/^DESKEWED.*/, ""), x)).filter(Boolean);
        const unverified = (r.warnings ?? []).some((x) => ["CONTENT_INCOMPLETE", "CASE_MISMATCH", "NAME_MISMATCH"].includes(x))
          || r.doc_type === "unknown";
        setNotice([t("uploadedAs", { type: tk("docType_", r.doc_type) }), w.length ? t("uploadWarnings", { list: w.join(", ") }) : "",
          unverified ? t("uploadUnverified") : "", r.result_changed ? t("eligibilityChanged", { status: ts(r.status ?? "") }) : ""]
          .filter(Boolean).join(" "));
      }
      await load();
    } catch (err) { setError(apiErrorText(t, err)); } finally { setBusy(false); e.target.value = ""; }
  }

  async function recompute() {
    setBusy(true); setError(null);
    try {
      const r = await api<{ status: string; previous_status: string | null; changed: boolean }>(`/api/persons/${id}/recompute`, { method: "POST" });
      setNotice(r.previous_status && r.previous_status !== r.status ? t("recomputedChanged", { from: ts(r.previous_status), to: ts(r.status) })
        : t("recomputedSame", { status: ts(r.status) }));
      await load();
    } catch (e) { setError(apiErrorText(t, e)); } finally { setBusy(false); }
  }

  if (error && !p) return <Shell><ErrorBox error={error} /></Shell>;
  if (!p) return <Shell><Loading /></Shell>;
  const r = p.eligibility.cases.find((c) => c.case_id === caseId);
  const detail = p.case_details.find((c) => c.id === caseId);
  const tabs: [Tab, Key][] = [["overview", "overview"], ["timeline", "timeline"], ["facts", "facts"],
    ...(p.can_see_insights ? [["insights", "insights"] as [Tab, Key]] : []), ["drafts", "drafts"]];
  const isJail = user?.role === "jail_staff";
  const canCustody = user?.role === "jail_staff" || user?.role === "system_admin";

  return (
    <Shell>
      <div className="flex flex-wrap items-start gap-4 justify-between mb-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold break-words">{p.name}<DemoBadge label={p.demo_label} /></h1>
          <p className="text-sm text-muted">
            {[p.relative ? `${p.relation ?? ""} ${p.relative}` : null, p.gender ? tk("gender_", p.gender) : null,
              `${t("dob")} ${fd(p.dob)}`, p.jail, p.district].filter(Boolean).join(" · ")}
          </p>
          <p className="text-sm">{p.assigned_lawyer ? t("assignedLawyer", { name: p.assigned_lawyer }) : <span className="text-urgent font-semibold">{t("noLawyer")}</span>}</p>
          {p.vulnerability.length > 0 && <p className="text-sm text-accent font-semibold">{t("vulnerableLabel", { list: p.vulnerability.map((v) => tk("vuln_", v)).join(", ") })}</p>}
          {p.name_variants.length > 0 && <p className="text-xs text-muted">{t("alsoRecordedAs", { names: p.name_variants.join(", ") })}</p>}
        </div>
        <div className="flex flex-col items-end gap-2">
          <StatusBadge code={p.urgency} className="text-sm" />
          <div className="flex flex-wrap justify-end gap-2">
            {user?.role === "legal_aid_lawyer" && (
              <label className={`btn btn-ghost ${busy ? "opacity-60" : "cursor-pointer"}`}>
                {busy ? t("working") : t("upload")}
                <input type="file" className="sr-only" accept=".pdf,.jpg,.jpeg,.png,.docx,.txt" onChange={upload} disabled={busy} />
              </label>
            )}
            <button className="btn btn-ghost" onClick={recompute} disabled={busy}>{t("recompute")}</button>
            {canCustody && <button className="btn btn-ghost" onClick={() => setDialog("transfer")}>{t("transfer")}</button>}
            {canCustody && <button className="btn btn-ghost" onClick={() => setDialog("release")}>{t("release")}</button>}
          </div>
          <p className="text-[11px] text-muted text-right">{t("computedMeta", { rules: p.rule_version, legal: p.legal_data_version, at: fdt(p.computed_at) })}</p>
        </div>
      </div>
      <ErrorBox error={error} />
      <Notice text={notice} />
      {dialog && <CustodyDialog kind={dialog} person={p} caseId={caseId} onClose={() => setDialog(null)}
        onDone={(msg) => { setDialog(null); setNotice(msg); load(); }} />}

      {p.case_details.length > 1 && (
        <div className="flex flex-wrap gap-2 mb-3" role="tablist" aria-label={t("casesLabel")}>
          {p.case_details.map((c) => {
            const cr = p.eligibility.cases.find((x) => x.case_id === c.id);
            return (
              <button key={c.id} role="tab" aria-selected={c.id === caseId} onClick={() => setCaseId(c.id)}
                className={`btn ${c.id === caseId ? "btn-primary" : "btn-ghost"} !py-1 flex-wrap`}>
                {c.case_numbers[0] ?? c.cnr} · {c.charges.map((x) => `${x.act} ${x.section}`).join(", ")}
                {cr && <StatusBadge code={cr.status} />}
              </button>
            );
          })}
        </div>
      )}

      <div role="tablist" aria-label={t("sectionsLabel")} className="flex gap-1 border-b border-line mb-4 overflow-x-auto">
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
          <Card title={t("custodyRecords")}>
            <ul className="text-sm space-y-1">
              {p.custody_events.map((e) => (
                <li key={e.id} className="flex flex-wrap gap-x-2">
                  <span className="font-medium">{tk("custodyType_", e.type)}</span>
                  <span>{fd(e.start)}{["arrest", "re_arrest", "released", "escaped", "surrendered", "transfer"].includes(e.type) && !e.end ? "" : ` → ${e.end ? fd(e.end) : t("ongoing")}`}</span>
                  {e.jail && <span className="text-muted">{e.jail}</span>}
                  {!e.primary && <span className="text-xs text-review">{t("secondarySource")}</span>}
                  {e.case_id && e.case_id !== caseId && <span className="text-xs text-urgent">{t("otherCase")}</span>}
                </li>
              ))}
            </ul>
          </Card>
          <Card title={t("hearingsTitle")}>
            {detail.hearings.length === 0 ? <p className="text-sm text-muted">{t("noHearings")}</p> : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-muted"><tr><th className="py-1">{t("hearingDate")}</th><th>{t("reason")}</th><th>{t("attributedTo")}</th></tr></thead>
                  <tbody>
                    {detail.hearings.map((h) => (
                      <tr key={h.id} className="border-t border-line align-top">
                        <td className="py-1 pr-2 whitespace-nowrap">{fd(h.date)}{h.next_date ? ` → ${fd(h.next_date)}` : ""}</td>
                        <td className="py-1 pr-2">{h.reason || <span className="text-muted">{t("noReason")}</span>}</td>
                        <td className="py-1">{tk("attr_", h.attribution)} <span className="text-xs text-muted">{Math.round(h.confidence * 100)}% {tk("method_", h.method ?? "", h.method ?? "")}{h.verified ? ` ✓ ${t("verifiedMark")}` : ""}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      )}
      {tab === "facts" && (
        <div className="space-y-4">
          {user?.role !== "legal_aid_lawyer" && <p className="text-xs text-muted">{t("onlyLawyerUploads")}</p>}
          {p.documents.length === 0 ? <p className="text-muted text-sm">{t("noDocuments")}</p> : (
            <div className="flex flex-wrap gap-2">
              {p.documents.map((d) => (
                <button key={d.id} onClick={() => setDoc({ id: d.id, start: -1, end: -1 })}
                  className={`btn ${doc?.id === d.id ? "btn-primary" : "btn-ghost"} !py-1 !text-xs`}>
                  {tk("docType_", d.doc_type)} · {d.filename}{d.warnings.length || d.status === "needs_review" ? " ⚠" : ""}
                </button>
              ))}
            </div>
          )}
          {doc ? <DocumentViewer docId={doc.id} focus={doc.start >= 0 ? doc : null} canCorrect={!isJail && user?.role !== "dlsa_admin"} onChanged={load} />
            : p.documents.length > 0 && <p className="text-muted text-sm">{t("selectDocument")}</p>}
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

function CustodyDialog({ kind, person, caseId, onClose, onDone }: {
  kind: "transfer" | "release"; person: PersonDetail; caseId: string | null; onClose: () => void; onDone: (msg: string) => void;
}) {
  const { t, ts } = useI18n();
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(today);
  const [jail, setJail] = useState("");
  const [district, setDistrict] = useState("");
  const [scope, setScope] = useState<"all" | "case">("all");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      if (kind === "transfer") {
        const r = await api<{ status: string }>(`/api/persons/${person.id}/transfer`, { method: "POST",
          body: JSON.stringify({ to_jail: jail, to_district: district || null, date, note: note || null }) });
        onDone(t("transferDone", { status: ts(r.status) }));
      } else {
        const r = await api<{ status: string }>(`/api/persons/${person.id}/release`, { method: "POST",
          body: JSON.stringify({ date, case_id: scope === "case" ? caseId : null, note: note || null }) });
        onDone(t("releaseDone", { status: ts(r.status) }));
      }
    } catch (err) { setError(apiErrorText(t, err)); } finally { setBusy(false); }
  }
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="cd-title" className="fixed inset-0 z-20 bg-black/40 flex items-center justify-center p-4">
      <form onSubmit={submit} className="card w-full max-w-md p-5 space-y-3 max-h-[90vh] overflow-auto">
        <h2 id="cd-title" className="text-lg font-semibold">{kind === "transfer" ? t("transferTitle") : t("releaseTitle")}</h2>
        <ErrorBox error={error} />
        <Field label={t("date")}><input type="date" required max={today} value={date} onChange={(e) => setDate(e.target.value)} className={inputCls} /></Field>
        {kind === "transfer" ? (
          <>
            <Field label={t("toJail")}><input required minLength={3} value={jail} onChange={(e) => setJail(e.target.value)} className={inputCls} /></Field>
            <Field label={`${t("toDistrict")} (${t("optional")})`}><input value={district} onChange={(e) => setDistrict(e.target.value)} className={inputCls} /></Field>
          </>
        ) : person.case_details.length > 1 && (
          <fieldset className="text-sm space-y-1">
            <label className="flex gap-2"><input type="radio" checked={scope === "all"} onChange={() => setScope("all")} />{t("releaseAll")}</label>
            <label className="flex gap-2"><input type="radio" checked={scope === "case"} onChange={() => setScope("case")} />{t("releaseCaseOnly")}</label>
          </fieldset>
        )}
        <Field label={`${t("note")} (${t("optional")})`}><input value={note} onChange={(e) => setNote(e.target.value)} className={inputCls} /></Field>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-ghost" onClick={onClose}>{t("cancel")}</button>
          <button className="btn btn-primary" disabled={busy}>{busy ? t("working") : t("submit")}</button>
        </div>
      </form>
    </div>
  );
}
