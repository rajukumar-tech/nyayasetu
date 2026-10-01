"use client";

import { useEffect, useState } from "react";
import { api, download, type Draft } from "@/lib/api";
import { apiErrorText, useI18n, type Key } from "@/lib/i18n";
import { Card, ErrorBox, Notice } from "./ui";

const TYPES = ["section_479", "default_bail", "regular_bail", "surety_modification", "speedy_trial", "plea_bargaining", "discharge"];

export function DraftsPanel({ personId, caseId, canDraft, superintendentOnly }: {
  personId: string; caseId: string; canDraft: boolean; superintendentOnly?: boolean;
}) {
  const { t, tk, fd } = useI18n();
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [open, setOpen] = useState<Draft | null>(null);
  const [type, setType] = useState("section_479");
  const [lang, setLang] = useState("en");
  const [busy, setBusy] = useState(false);
  const [edit, setEdit] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = () => api<Draft[]>(`/api/persons/${personId}/drafts`).then((d) => setDrafts(d.filter((x) => x.case_id === caseId)))
    .catch((e) => setError(apiErrorText(t, e)));
  useEffect(() => { load(); }, [personId, caseId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function create() {
    setBusy(true); setError(null);
    try {
      const d = await api<Draft>(`/api/persons/${personId}/drafts`, { method: "POST",
        body: JSON.stringify({ case_id: caseId, type: superintendentOnly ? "section_479" : type, language: lang, use_llm: true }) });
      setOpen(d); load();
    } catch (e) { setError(apiErrorText(t, e)); } finally { setBusy(false); }
  }
  async function patch(body: object) {
    if (!open) return;
    try {
      const d = await api<Draft>(`/api/drafts/${open.id}`, { method: "PATCH", body: JSON.stringify(body) });
      setOpen(d); setEdit(null); load();
    } catch (e) { setError(apiErrorText(t, e)); }
  }
  async function exportAs(fmt: "docx" | "pdf") {
    if (!open) return;
    try { await download(`/api/drafts/${open.id}/export?format=${fmt}`, `${open.type}_${open.language}.${fmt}`); setNotice(t("exportStarted")); }
    catch (e) { setError(apiErrorText(t, e)); }
  }

  return (
    <div className="space-y-4">
      <ErrorBox error={error} />
      <Notice text={notice} />
      {(canDraft || superintendentOnly) && (
        <Card title={superintendentOnly ? t("superintendentApp") : t("newDraft")}>
          <div className="flex flex-wrap gap-2 items-end">
            {!superintendentOnly && (
              <label className="text-sm"><span className="label block">{t("draftType")}</span>
                <select value={type} onChange={(e) => setType(e.target.value)} className="border border-line rounded-md px-2 py-1.5 max-w-full">
                  {TYPES.map((k) => <option key={k} value={k}>{t(`draft_${k}` as Key)}</option>)}
                </select>
              </label>
            )}
            <label className="text-sm"><span className="label block">{t("draftLanguage")}</span>
              <select value={lang} onChange={(e) => setLang(e.target.value)} className="border border-line rounded-md px-2 py-1.5">
                <option value="en">{t("draftLang_en")}</option><option value="kn">{t("draftLang_kn")}</option>
              </select>
            </label>
            <button className="btn btn-primary" disabled={busy} onClick={create}>{busy ? t("working") : t("create")}</button>
          </div>
          <p className="text-xs text-muted mt-2">{t("draftExplainer")} {t("draftContentNote")}</p>
        </Card>
      )}

      {drafts.length > 0 ? (
        <ul className="flex flex-wrap gap-2">
          {drafts.map((d) => (
            <li key={d.id}>
              <button onClick={() => { setOpen(d); setEdit(null); }}
                className={`btn ${open?.id === d.id ? "btn-primary" : "btn-ghost"} !py-1 !text-xs`}>
                {tk("draft_", d.type)} · {d.language.toUpperCase()} · {fd(d.created_at)} · {tk("draftStatus_", d.status)}
              </button>
            </li>
          ))}
        </ul>
      ) : !canDraft && !superintendentOnly && <p className="text-muted text-sm">{t("noItems")}</p>}

      {open && (
        <Card title={<span lang={open.language}>{open.verifier_report.title}</span>} actions={
          <div className="flex flex-wrap gap-1">
            <button className="btn btn-ghost !py-1" onClick={() => exportAs("docx")}>{t("exportDocx")}</button>
            <button className="btn btn-ghost !py-1" onClick={() => exportAs("pdf")}>{t("exportPdf")}</button>
            {canDraft && edit == null && <button className="btn btn-ghost !py-1" onClick={() => setEdit(open.content)}>{t("edit")}</button>}
          </div>
        }>
          <div className={`text-sm mb-3 p-2 rounded-md ${open.verifier_report.rejected ? "bg-critical-bg text-critical" : "bg-ok-bg text-ok"}`} role="status">
            {t("verifierLine", { pct: open.verifier_report.fully_grounded_pct, n: open.verifier_report.sentences, rej: open.verifier_report.rejected })}
            {open.verifier_report.lawyer_edited ? ` ${t("lawyerEdited")}` : ""}
            {open.verifier_report.notes?.map((n) => <div key={n} className="text-urgent" lang="en">{n}</div>)}
          </div>
          {edit != null ? (
            <div>
              <label className="sr-only" htmlFor="draft-edit">{t("draftText")}</label>
              <textarea id="draft-edit" value={edit} onChange={(e) => setEdit(e.target.value)} rows={18} lang={open.language}
                className="w-full border border-line rounded-md p-3 text-sm font-sans" />
              <div className="flex gap-2 mt-2">
                <button className="btn btn-primary" onClick={() => patch({ content: edit })}>{t("saveEdits")}</button>
                <button className="btn btn-ghost" onClick={() => setEdit(null)}>{t("cancel")}</button>
              </div>
              <p className="text-xs text-muted mt-1">{t("editsTracked", { n: open.versions.length })}</p>
            </div>
          ) : open.verifier_report.lawyer_edited ? (
            <pre lang={open.language} className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{open.content.replace(/[«»]/g, "")}</pre>
          ) : (
            <ol className="space-y-2" lang={open.language}>
              {open.grounding.map((s) => (
                <li key={s.id} className={`text-sm leading-relaxed border-l-4 pl-3 ${s.status === "ok" ? "border-ok/40" : "border-critical bg-critical-bg"}`}>
                  <span>{s.text.replace(/[«»]/g, "")}</span>
                  <details className="text-xs text-muted" lang="en">
                    <summary className="cursor-pointer">{t("grounding")}: {s.sources.map((x) => x.type).join(", ") || t("none")}</summary>
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
