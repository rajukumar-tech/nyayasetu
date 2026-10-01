"use client";

import { useEffect, useState } from "react";
import { DocumentViewer } from "@/components/DocumentViewer";
import { useDialog } from "@/components/Dialog";
import { Shell } from "@/components/Shell";
import { Card, ErrorBox, Loading, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { apiErrorText, useI18n, type Key } from "@/lib/i18n";

interface Pair { name: string; relative: string; jail: string | null; dob: string | null }
interface Context { person?: string; jail?: string | null; filename?: string; doc_type?: string; field?: string; value?: unknown;
  page?: number; span_text?: string; notes?: string[]; hearing_date?: string; next_date?: string | null; pair?: Pair[] }
interface Item { id: string; kind: string; ref_id: string; title: string; confidence: number; created_at: string;
  payload: Record<string, unknown>; context?: Context }
interface Merge { id: string; kept_name?: string; merged_name?: string; score?: number; undone: boolean; created_at: string }

const KINDS: [string, Key][] = [["", "kind_all"], ["new_prisoner", "kind_new_prisoner"], ["extraction", "kind_extraction"], ["delay_attribution", "kind_delay_attribution"],
  ["identity_match", "kind_identity_match"], ["document_mismatch", "kind_document_mismatch"], ["document_type", "kind_document_type"],
  ["document", "kind_document"]];
const DOC_KINDS = ["document_mismatch", "document_type", "document"];
const ATTR = ["accused", "prosecution", "court", "both", "other", "unknown"];
/** Reading problems the extractor records on a fact, explained in plain words (flag_<code> keys). */
const FLAGS = ["AMBIGUOUS_DMY_MDY", "AMBIGUITY_RESOLVED_BY_CONTEXT", "PARSED_AS_MDY", "TWO_DIGIT_YEAR", "OCR_DIGIT_CORRECTED",
  "OCR_CORRECTED", "DISAGREEMENT", "PARTIAL_DATE", "TIME_MISSING", "ACT_NOT_STATED", "LOW_OCR_CONFIDENCE_POSSIBLE_HANDWRITING",
  "IMPOSSIBLE_DATE", "FUTURE_DATE"];

/** One decision: the button, and in plain words what pressing it does. */
function Choice({ button, children }: { button: React.ReactNode; children: React.ReactNode }) {
  return (
    <li className="flex flex-col sm:flex-row sm:items-start gap-1 sm:gap-3 py-2 border-t border-line first:border-t-0">
      <div className="shrink-0 sm:w-56">{button}</div>
      <p className="text-sm text-muted">{children}</p>
    </li>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-1">
      <h3 className="label">{title}</h3>
      <div className="text-sm">{children}</div>
    </section>
  );
}

export default function Reviewer() {
  const { t, tk, fd, fdt } = useI18n();
  const dialog = useDialog();
  const [items, setItems] = useState<Item[] | null>(null);
  const [merges, setMerges] = useState<Merge[]>([]);
  const [kind, setKind] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Item | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [help, setHelp] = useState(true);

  const toggleHelp = () => setHelp((h) => !h);

  const load = () => {
    api<Item[]>("/api/review").then((rows) => {
      setItems(rows);
      setOpen((o) => (o ? rows.find((r) => r.id === o.id) ?? null : null));
    }).catch((e) => setError(apiErrorText(t, e)));
    api<Merge[]>("/api/resolution/merges").then(setMerges).catch(() => {});
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function resolve(item: Item, action: string, value?: unknown, note?: string) {
    setError(null);
    try {
      await api(`/api/review/${item.id}/resolve`, { method: "POST", body: JSON.stringify({ action, value, note }) });
      setOpen(null); setMsg(t("reviewResolved")); load();
    } catch (e) { setError(apiErrorText(t, e)); }
  }
  async function scan() {
    try {
      const r = await api<{ candidates: number }>("/api/resolution/scan", { method: "POST" });
      setMsg(t("scanResult", { n: r.candidates }));
      load();
    } catch (e) { setError(apiErrorText(t, e)); }
  }
  async function undo(m: Merge) {
    try { await api(`/api/resolution/unmerge/${m.id}`, { method: "POST" }); setMsg(t("mergeUndone")); load(); }
    catch (e) { setError(apiErrorText(t, e)); }
  }

  const count = (k: string) => (items ?? []).filter((i) => !k || i.kind === k).length;
  const shown = (items ?? []).filter((i) => !kind || i.kind === kind);
  const pct = (i: Item) => Math.round(i.confidence * 100);
  const docLabel = (c?: Context) => c?.filename ? t("rvDocument", { file: c.filename, type: tk("docType_", c.doc_type) }) : null;
  /** Dates as the reader writes them ("9 Jan 2026, 19:30"), other values as they are. */
  function plain(v: unknown): string {
    const m = typeof v === "string" ? /^(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}))?/.exec(v) : null;
    if (m) return m[2] ? `${fd(m[1])}, ${m[2]}` : fd(m[1]);
    return v == null || v === "" ? "—" : Array.isArray(v) ? v.join(", ") : String(v);
  }
  /** A short human line for the list, instead of the technical title. */
  function summary(i: Item): string {
    const c = i.context ?? {};
    if (i.kind === "extraction" && c.field) return t("rvReadValue", { field: tk("field_", c.field), value: plain(c.value) });
    if (i.kind === "delay_attribution" && c.hearing_date) return t("rvHearing", { date: fd(c.hearing_date), next: c.next_date ? fd(c.next_date) : "—" });
    if (i.kind === "identity_match" && c.pair?.length === 2) return `${c.pair[0].name} ↔ ${c.pair[1].name}`;
    if (DOC_KINDS.includes(i.kind) && c.filename) return c.filename;
    if (i.kind === "new_prisoner" && c.person) return c.person;
    return i.title;
  }
  function flags(c?: Context): Key[] {
    const out = new Set<Key>();
    for (const n of c?.notes ?? []) {
      const code = String(n).replace(/^flag:/, "").split(":")[0].trim();
      if (FLAGS.includes(code)) out.add(`flag_${code}` as Key);
    }
    return [...out];
  }

  return (
    <Shell roles={["reviewer"]}>
      <div className="flex flex-wrap justify-between items-center gap-2 mb-4">
        <h1 className="text-2xl font-bold">{t("review")}</h1>
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-ghost" aria-expanded={help} onClick={toggleHelp}>{help ? t("rvHelpHide") : t("rvHelpShow")}</button>
          <button className="btn btn-ghost" onClick={scan}>{t("scanDuplicates")}</button>
        </div>
      </div>
      {help && (
        <Card title={t("rvIntroTitle")} className="mb-4">
          <p className="text-sm mb-3 max-w-4xl">{t("rvIntro")}</p>
          <ol className="grid md:grid-cols-3 gap-3 text-sm">
            {(["rvStep1", "rvStep2", "rvStep3"] as Key[]).map((k, n) => (
              <li key={k} className="flex gap-2">
                <span aria-hidden className="shrink-0 w-6 h-6 rounded-full bg-accent text-white text-xs font-bold grid place-items-center">{n + 1}</span>
                <span>{t(k)}</span>
              </li>
            ))}
          </ol>
          <p className="text-sm text-review mt-3">{t("rvIntroNote")}</p>
        </Card>
      )}
      <ErrorBox error={error} />
      <Notice text={msg} />
      <div className="flex flex-wrap gap-1 mb-3" role="group" aria-label={t("filter")}>
        {KINDS.map(([k, l]) => (
          <button key={k} aria-pressed={kind === k} onClick={() => setKind(k)}
            className={`btn ${kind === k ? "btn-primary" : "btn-ghost"} !py-1 !text-xs`}>
            {t(l)}{items && <span aria-hidden className="ml-1 opacity-75 tabular-nums">({count(k)})</span>}
          </button>
        ))}
      </div>
      {!items ? (!error && <Loading />) : shown.length === 0 ? <p className="text-muted max-w-3xl">{t("rvEmpty")}</p> : (
        <div className="grid lg:grid-cols-2 gap-4">
          <div className="min-w-0">
            <p className="text-xs text-muted mb-2">{t("rvWaiting", { n: shown.length })}</p>
            <ul className="space-y-2">
              {shown.map((i) => (
                <li key={i.id}>
                  <button onClick={() => setOpen(i)} aria-current={open?.id === i.id}
                    className={`card p-3 w-full text-left ${open?.id === i.id ? "ring-2 ring-accent" : ""}`}>
                    <div className="flex justify-between gap-2 text-xs">
                      <span className="label">{tk("kind_", i.kind)}</span>
                      <span title={t("rvConfidenceHelp")} className={i.confidence < 0.5 ? "text-critical" : "text-review"}>
                        {t("rvConfidence", { pct: pct(i) })}</span>
                    </div>
                    <div className="text-sm font-semibold mt-1 break-words">{summary(i)}</div>
                    <div className="text-xs text-muted mt-0.5 break-words">
                      {[i.context?.person && t("rvPrisoner", { name: i.context.person }), t("rvAdded", { date: fd(i.created_at) })]
                        .filter(Boolean).join(" · ")}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div className="lg:sticky lg:top-4 self-start min-w-0">
            {!open ? <p className="card p-4 text-sm text-muted">{t("rvSelect")}</p> : (
              <Card title={<span>{tk("kind_", open.kind)} — {summary(open)}</span>}>
                <div className="space-y-4">
                  <p className="text-xs text-muted">
                    {[open.context?.person && t("rvPrisoner", { name: open.context.person }), open.context?.jail,
                      docLabel(open.context)].filter(Boolean).join(" · ")}
                  </p>
                  <div className="text-xs">
                    <span className={open.confidence < 0.5 ? "text-critical font-semibold" : "text-review font-semibold"}>
                      {t("rvConfidence", { pct: pct(open) })}</span>
                    <span className="text-muted"> — {t("rvConfidenceHelp")}</span>
                  </div>

                  <Section title={t("rvWhy")}>
                    <p>{t(`rvWhy_${open.kind}` as Key)}</p>
                    {open.kind === "extraction" && open.context?.field && (
                      <div className="mt-2 space-y-1">
                        <p className="font-semibold">{summary(open)}</p>
                        {open.context.span_text && <p className="text-muted">{t("rvSourceText", { page: open.context.page ?? 1, text: open.context.span_text })}</p>}
                        {(flags(open.context).length ? flags(open.context) : ["rvFlagLow" as Key]).map((k) =>
                          <p key={k} className="text-review">• {t(k)}</p>)}
                      </div>
                    )}
                    {open.kind === "delay_attribution" && (
                      <div className="mt-2 space-y-1">
                        {open.context?.hearing_date && <p className="font-semibold">{summary(open)}</p>}
                        <p>{t("orderSheetEntry", { text: String(open.payload.reason_text ?? "") })}</p>
                        <p className="text-muted">{t("suggestedVia", { label: tk("attr_", String(open.payload.suggested)), method: tk("method_", String(open.payload.method), String(open.payload.method)) })}</p>
                      </div>
                    )}
                    {DOC_KINDS.includes(open.kind) && <p className="mt-2 text-muted break-words" lang="en">{open.title}</p>}
                  </Section>

                  <Section title={t("rvCheck")}>
                    <p>{t(DOC_KINDS.includes(open.kind) ? "rvCheck_document" : `rvCheck_${open.kind}` as Key)}</p>
                  </Section>

                  {open.kind === "new_prisoner" && (
                    <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                      {([["fullName", "name"], ["relativeName", "relative_name"], ["jailLabel", "jail"], ["districtLabel", "district"],
                        ["court", "court"], ["caseNumber", "case_number"], ["cnr", "cnr"], ["firNumber", "fir_number"],
                        ["charges", "charges"], ["offenceDate", "offence_date"], ["arrestDate", "arrest_date"],
                        ["firstRemandDate", "first_remand_date"], ["chargeSheetDate", "charge_sheet_date"],
                        ["custodyStatus", "custody_status"], ["createdBy", "created_by"]] as [Key, string][]).map(([label, k]) => {
                        const v = open.payload[k];
                        const val = Array.isArray(v) ? v.join(", ") : k === "custody_status" && v ? t(`cs_${v}` as Key)
                          : k.endsWith("date") && v ? fd(String(v)) : v == null || v === "" ? "—" : String(v);
                        return <div key={k} className="contents"><dt className="label self-center">{t(label)}</dt><dd className="break-words">{val}</dd></div>;
                      })}
                    </dl>
                  )}
                  {open.kind === "identity_match" && (
                    <div className="space-y-3 text-sm">
                      {open.context?.pair && open.context.pair.length === 2 && (
                        <table className="w-full text-xs">
                          <thead><tr className="text-muted text-left"><th></th><th>{t("rvRecordA")}</th><th>{t("rvRecordB")}</th></tr></thead>
                          <tbody>
                            {([["fullName", "name"], ["relativeName", "relative"], ["rvDob", "dob"], ["jailLabel", "jail"]] as [Key, keyof Pair][]).map(([label, f]) => (
                              <tr key={f} className="border-t border-line">
                                <th className="py-0.5 pr-2 text-left font-normal text-muted">{t(label)}</th>
                                {open.context!.pair!.map((p, n) => <td key={n} className="py-0.5 break-words">{(f === "dob" && p.dob ? fd(p.dob) : p[f]) || "—"}</td>)}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                      <p>{t("modelDecision", { decision: tk("decision_", String(open.payload.decision)) })}
                        {(open.payload.vetoes as string[])?.length ? <> · <span className="text-critical">{t("vetoes", { list: (open.payload.vetoes as string[]).join(", ") })}</span></> : null}</p>
                      <table className="text-xs w-full"><thead><tr className="text-muted text-left"><th>{t("feature")}</th><th className="text-right">{t("score")}</th></tr></thead><tbody>
                        {Object.entries((open.payload.features ?? {}) as Record<string, number>).map(([k, v]) =>
                          <tr key={k} className="border-t border-line"><td className="py-0.5">{tk("feat_", k)}</td><td className="text-right tabular-nums">{Number(v).toFixed(2)}</td></tr>)}
                      </tbody></table>
                      <p className="text-xs text-muted">{t("rvSignalsHelp")}</p>
                      <p className="text-urgent text-xs">{t("falseMergeWarning")}</p>
                    </div>
                  )}

                  <Section title={t("rvChoices")}>
                    <ul>
                      {open.kind === "new_prisoner" && <>
                        <Choice button={<button className="btn btn-primary w-full" onClick={() => resolve(open, "confirm")}>{t("verifyIntake")}</button>}>{t("rvDo_verify")}</Choice>
                        <Choice button={<button className="btn btn-danger w-full" onClick={async () => { const n = await dialog.ask({ title: t("returnIntake"), label: t("returnPrompt"), minLength: 3, confirmText: t("returnIntake"), danger: true }); if (n != null) resolve(open, "reject", undefined, n); }}>{t("returnIntake")}</button>}>{t("rvDo_return")}</Choice>
                      </>}
                      {open.kind === "extraction" && <>
                        <Choice button={<button className="btn btn-primary w-full" onClick={() => resolve(open, "confirm")}>{t("confirm")}</button>}>{t("rvDo_confirm")}</Choice>
                        <Choice button={<button className="btn btn-ghost w-full" onClick={async () => { const v = await dialog.ask({ title: t("correct"), label: t("correctValue"), confirmText: t("save") }); if (v != null && v.trim()) resolve(open, "correct", v); }}>{t("correct")}</button>}>{t("rvDo_correct")}</Choice>
                        <Choice button={<button className="btn btn-danger w-full" onClick={() => resolve(open, "reject")}>{t("reject")}</button>}>{t("rvDo_reject")}</Choice>
                      </>}
                      {open.kind === "delay_attribution" && <>
                        <li className="flex flex-wrap gap-1 pb-2">
                          {ATTR.map((a) => <button key={a} className={`btn ${a === "accused" ? "btn-primary" : "btn-ghost"} !py-1`} onClick={() => resolve(open, "set_attribution", a)}>{tk("attr_", a)}</button>)}
                        </li>
                        <li className="text-sm text-muted space-y-1 border-t border-line pt-2">
                          <p>• {t("rvDo_attr_accused")}</p><p>• {t("rvDo_attr_other")}</p><p>• {t("rvDo_attr_unsure")}</p>
                          <p className="text-xs">{t("delayRule")}</p>
                        </li>
                      </>}
                      {open.kind === "identity_match" && <>
                        <Choice button={<button className="btn btn-primary w-full" onClick={() => resolve(open, "link")}>{t("sameLink")}</button>}>{t("rvDo_link")}</Choice>
                        <Choice button={<button className="btn btn-ghost w-full" onClick={() => resolve(open, "not_same")}>{t("differentPeople")}</button>}>{t("rvDo_notSame")}</Choice>
                      </>}
                      {DOC_KINDS.includes(open.kind) && <>
                        <Choice button={<button className="btn btn-primary w-full" onClick={() => resolve(open, "confirm")}>{t("resolvedBtn")}</button>}>{t("rvDo_docResolved")}</Choice>
                        <Choice button={<button className="btn btn-ghost w-full" onClick={() => resolve(open, "reject")}>{t("dismiss")}</button>}>{t("rvDo_docDismiss")}</Choice>
                        <li className="text-xs text-review pt-1">{t("rvDocHeldNote")}</li>
                      </>}
                    </ul>
                    <p className="text-xs text-muted mt-2">{t("rvRecalc")}</p>
                  </Section>

                  {(open.kind === "extraction" || DOC_KINDS.includes(open.kind)) && (
                    <DocumentViewer docId={open.kind === "extraction" ? String(open.payload.document_id)
                      : typeof open.payload.document_id === "string" ? open.payload.document_id : open.ref_id} canCorrect={false} />
                  )}

                  <details className="text-xs text-muted">
                    <summary className="cursor-pointer">{t("rvTechnical")}</summary>
                    <p className="mt-1 break-words" lang="en">{open.title}</p>
                  </details>
                </div>
              </Card>
            )}
          </div>
        </div>
      )}
      {merges.length > 0 && (
        <Card title={t("merges")} className="mt-5">
          <p className="text-xs text-muted mb-2">{t("rvMergesHelp")}</p>
          <ul className="text-sm space-y-1">
            {merges.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-2">
                <span>{t("mergedLine", { merged: m.merged_name ?? "?", kept: m.kept_name ?? "?" })}</span>
                <span className="text-xs text-muted">{fdt(m.created_at)}</span>
                {m.undone ? <span className="text-xs text-muted">{t("mergeUndone")}</span>
                  : <button className="btn btn-ghost !py-0.5 !text-xs" onClick={() => undo(m)}>{t("undoMerge")}</button>}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </Shell>
  );
}
