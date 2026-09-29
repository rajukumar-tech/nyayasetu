"use client";

import { useEffect, useState } from "react";
import { api, download, type Draft } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Card, ErrorBox, fmtDate } from "./ui";

const TYPES: [string, string][] = [
  ["section_479", "Section 479 BNSS application"], ["default_bail", "Default bail application"],
  ["regular_bail", "Regular bail application"], ["surety_modification", "Bail-condition modification (surety relief)"],
  ["speedy_trial", "Speedy-trial petition"], ["plea_bargaining", "Plea-bargaining application"], ["discharge", "Discharge application"],
];

export function DraftsPanel({ personId, caseId, canDraft, superintendentOnly }: {
  personId: string; caseId: string; canDraft: boolean; superintendentOnly?: boolean;
}) {
  const { t } = useI18n();
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [open, setOpen] = useState<Draft | null>(null);
  const [type, setType] = useState(superintendentOnly ? "section_479" : "section_479");
  const [lang, setLang] = useState("en");
  const [busy, setBusy] = useState(false);
  const [edit, setEdit] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => api<Draft[]>(`/api/persons/${personId}/drafts`).then((d) => setDrafts(d.filter((x) => x.case_id === caseId)))
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, [personId, caseId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function create() {
    setBusy(true); setError(null);
    try {
      const d = await api<Draft>(`/api/persons/${personId}/drafts`, { method: "POST",
        body: JSON.stringify({ case_id: caseId, type, language: lang, use_llm: true }) });
      setOpen(d); load();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function patch(body: object) {
    if (!open) return;
    const d = await api<Draft>(`/api/drafts/${open.id}`, { method: "PATCH", body: JSON.stringify(body) });
    setOpen(d); setEdit(null); load();
  }

  return (
    <div className="space-y-4">
      <ErrorBox error={error} />
      {(canDraft || superintendentOnly) && (
        <Card title={superintendentOnly ? t("superintendentApp") : t("newDraft")}>
          <div className="flex flex-wrap gap-2 items-end">
            {!superintendentOnly && (
              <label className="text-sm"><span className="label block">Type</span>
                <select value={type} onChange={(e) => setType(e.target.value)} className="border border-line rounded-md px-2 py-1.5">
                  {TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
              </label>
            )}
            <label className="text-sm"><span className="label block">{t("language")}</span>
              <select value={lang} onChange={(e) => setLang(e.target.value)} className="border border-line rounded-md px-2 py-1.5">
                <option value="en">English</option><option value="kn">ಕನ್ನಡ (Kannada)</option>
              </select>
            </label>
            <button className="btn btn-primary" disabled={busy} onClick={create}>{busy ? "…" : t("create")}</button>
          </div>
          <p className="text-xs text-muted mt-2">Every sentence is built from a verified fact, the eligibility trace, a legal-data record,
            an accepted insight or a retrieved passage — and re-checked by the verifier.</p>
        </Card>
      )}

      {drafts.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {drafts.map((d) => (
            <li key={d.id}>
              <button onClick={() => { setOpen(d); setEdit(null); }}
                className={`btn ${open?.id === d.id ? "btn-primary" : "btn-ghost"} !py-1 !text-xs`}>
                {d.type} · {d.language} · {fmtDate(d.created_at)} · {d.status}
              </button>
            </li>
          ))}
        </ul>
      )}

      {open && (
        <Card title={open.verifier_report.title} actions={
          <div className="flex flex-wrap gap-1">
            <button className="btn btn-ghost !py-1" onClick={() => download(`/api/drafts/${open.id}/export?format=docx`, `${open.type}_${open.language}.docx`)}>{t("exportDocx")}</button>
            <button className="btn btn-ghost !py-1" onClick={() => download(`/api/drafts/${open.id}/export?format=pdf`, `${open.type}_${open.language}.pdf`)}>{t("exportPdf")}</button>
            {canDraft && edit == null && <button className="btn btn-ghost !py-1" onClick={() => setEdit(open.content)}>Edit</button>}
            {canDraft && open.status !== "approved" && <button className="btn btn-primary !py-1" onClick={() => patch({ status: "approved" })}>{t("approve")}</button>}
          </div>
        }>
          <div className={`text-sm mb-3 p-2 rounded-md ${open.verifier_report.rejected ? "bg-critical-bg text-critical" : "bg-ok-bg text-ok"}`} role="status">
            {t("verifier")}: {open.verifier_report.fully_grounded_pct}% of {open.verifier_report.sentences} sentences grounded;
            {" "}{open.verifier_report.rejected} rejected.{open.verifier_report.lawyer_edited ? " Edited by lawyer after verification — re-check before filing." : ""}
            {open.verifier_report.notes?.map((n) => <div key={n} className="text-urgent">{n}</div>)}
          </div>
          {edit != null ? (
            <div>
              <label className="sr-only" htmlFor="draft-edit">Draft text</label>
              <textarea id="draft-edit" value={edit} onChange={(e) => setEdit(e.target.value)} rows={18}
                className="w-full border border-line rounded-md p-3 text-sm font-sans" />
              <div className="flex gap-2 mt-2">
                <button className="btn btn-primary" onClick={() => patch({ content: edit })}>{t("save")}</button>
                <button className="btn btn-ghost" onClick={() => setEdit(null)}>Cancel</button>
              </div>
              <p className="text-xs text-muted mt-1">Edits are tracked ({open.versions.length} earlier version(s)).</p>
            </div>
          ) : open.verifier_report.lawyer_edited ? (
            <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{open.content.replace(/[«»]/g, "")}</pre>
          ) : (
            <ol className="space-y-2">
              {open.grounding.map((s) => (
                <li key={s.id} className={`text-sm leading-relaxed border-l-4 pl-3 ${s.status === "ok" ? "border-ok/40" : "border-critical bg-critical-bg"}`}>
                  <span>{s.text.replace(/[«»]/g, "")}</span>
                  <details className="text-xs text-muted">
                    <summary className="cursor-pointer">{t("grounding")}: {s.sources.map((x) => x.type).join(", ") || "none"}</summary>
                    <ul className="pl-3">{s.sources.map((x, k) => <li key={k}>{x.type} {x.ref}: {x.values.filter(Boolean).slice(0, 4).join(" | ")}</li>)}</ul>
                    {s.problems.map((p) => <div key={p} className="text-critical">✗ {p}</div>)}
                  </details>
                </li>
              ))}
            </ol>
          )}
        </Card>
      )}
    </div>
  );
}
