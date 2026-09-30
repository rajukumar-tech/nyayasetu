"use client";

import { useEffect, useState } from "react";
import { DocumentViewer } from "@/components/DocumentViewer";
import { useDialog } from "@/components/Dialog";
import { Shell } from "@/components/Shell";
import { Card, ErrorBox, Loading, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { apiErrorText, useI18n, type Key } from "@/lib/i18n";

interface Item { id: string; kind: string; ref_id: string; title: string; confidence: number; created_at: string;
  payload: Record<string, unknown> }
interface Merge { id: string; kept_name?: string; merged_name?: string; score?: number; undone: boolean; created_at: string }

const KINDS: [string, Key][] = [["", "kind_all"], ["new_prisoner", "kind_new_prisoner"], ["extraction", "kind_extraction"], ["delay_attribution", "kind_delay_attribution"],
  ["identity_match", "kind_identity_match"], ["document_mismatch", "kind_document_mismatch"], ["document_type", "kind_document_type"],
  ["document", "kind_document"]];
const ATTR = ["accused", "prosecution", "court", "both", "other", "unknown"];

export default function Reviewer() {
  const { t, tk, fd, fdt } = useI18n();
  const dialog = useDialog();
  const [items, setItems] = useState<Item[] | null>(null);
  const [merges, setMerges] = useState<Merge[]>([]);
  const [kind, setKind] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Item | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = () => {
    api<Item[]>(`/api/review${kind ? `?kind=${kind}` : ""}`).then(setItems).catch((e) => setError(apiErrorText(t, e)));
    api<Merge[]>("/api/resolution/merges").then(setMerges).catch(() => {});
  };
  useEffect(() => { load(); }, [kind]); // eslint-disable-line react-hooks/exhaustive-deps

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

  return (
    <Shell roles={["reviewer"]}>
      <div className="flex flex-wrap justify-between gap-2 mb-4">
        <h1 className="text-2xl font-bold">{t("review")}</h1>
        <button className="btn btn-ghost" onClick={scan}>{t("scanDuplicates")}</button>
      </div>
      <ErrorBox error={error} />
      <Notice text={msg} />
      <div className="flex flex-wrap gap-1 mb-3" role="group" aria-label={t("filter")}>
        {KINDS.map(([k, l]) => <button key={k} aria-pressed={kind === k} onClick={() => setKind(k)}
          className={`btn ${kind === k ? "btn-primary" : "btn-ghost"} !py-1 !text-xs`}>{t(l)}</button>)}
      </div>
      {!items ? (!error && <Loading />) : items.length === 0 ? <p className="text-muted">{t("noItems")}</p> : (
        <div className="grid lg:grid-cols-2 gap-4">
          <ul className="space-y-2 min-w-0">
            {items.map((i) => (
              <li key={i.id}>
                <button onClick={() => setOpen(i)} className={`card p-3 w-full text-left ${open?.id === i.id ? "ring-2 ring-accent" : ""}`}>
                  <div className="flex justify-between gap-2 text-xs"><span className="label">{tk("kind_", i.kind)}</span>
                    <span className={i.confidence < 0.5 ? "text-critical" : "text-review"}>{Math.round(i.confidence * 100)}%</span></div>
                  <div className="text-sm mt-1 break-words" lang="en">{i.title}</div>
                </button>
              </li>
            ))}
          </ul>
          <div className="lg:sticky lg:top-4 self-start min-w-0">
            {open && (
              <Card title={<span lang="en">{open.title}</span>}>
                {open.kind === "new_prisoner" && (
                  <div className="space-y-2 text-sm">
                    <p className="text-muted">{t("intakeCheck")}</p>
                    <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
                      {([["fullName", "name"], ["relativeName", "relative_name"], ["jailLabel", "jail"], ["districtLabel", "district"],
                        ["court", "court"], ["caseNumber", "case_number"], ["cnr", "cnr"], ["firNumber", "fir_number"],
                        ["charges", "charges"], ["offenceDate", "offence_date"], ["arrestDate", "arrest_date"],
                        ["firstRemandDate", "first_remand_date"], ["chargeSheetDate", "charge_sheet_date"],
                        ["custodyStatus", "custody_status"], ["createdBy", "created_by"]] as [Key, string][]).map(([label, k]) => {
                        const v = open.payload[k];
                        const shown = Array.isArray(v) ? v.join(", ") : k === "custody_status" && v ? t(`cs_${v}` as Key)
                          : k.endsWith("date") && v ? fd(String(v)) : v == null || v === "" ? "—" : String(v);
                        return <div key={k} className="contents"><dt className="label self-center">{t(label)}</dt><dd className="break-words">{shown}</dd></div>;
                      })}
                    </dl>
                    <div className="flex flex-wrap gap-2 pt-1">
                      <button className="btn btn-primary" onClick={() => resolve(open, "confirm")}>{t("verifyIntake")}</button>
                      <button className="btn btn-danger" onClick={async () => { const n = await dialog.ask({ title: t("returnIntake"), label: t("returnPrompt"), minLength: 3, confirmText: t("returnIntake"), danger: true }); if (n != null) resolve(open, "reject", undefined, n); }}>{t("returnIntake")}</button>
                    </div>
                  </div>
                )}
                {open.kind === "delay_attribution" && (
                  <div className="space-y-2 text-sm">
                    <p>{t("orderSheetEntry", { text: String(open.payload.reason_text ?? "") })}</p>
                    <p className="text-muted">{t("suggestedVia", { label: tk("attr_", String(open.payload.suggested)), method: tk("method_", String(open.payload.method), String(open.payload.method)) })} {t("delayRule")}</p>
                    <div className="flex flex-wrap gap-1">
                      {ATTR.map((a) => <button key={a} className="btn btn-ghost !py-1" onClick={() => resolve(open, "set_attribution", a)}>{tk("attr_", a)}</button>)}
                    </div>
                  </div>
                )}
                {open.kind === "extraction" && (
                  <div className="space-y-3">
                    <DocumentViewer docId={String(open.payload.document_id)} canCorrect={false} />
                    <div className="flex flex-wrap gap-2">
                      <button className="btn btn-primary" onClick={() => resolve(open, "confirm")}>{t("confirm")}</button>
                      <button className="btn btn-ghost" onClick={async () => { const v = await dialog.ask({ title: t("correct"), label: t("correctValue"), confirmText: t("save") }); if (v != null && v.trim()) resolve(open, "correct", v); }}>{t("correct")}</button>
                      <button className="btn btn-danger" onClick={() => resolve(open, "reject")}>{t("reject")}</button>
                    </div>
                  </div>
                )}
                {open.kind === "identity_match" && (
                  <div className="space-y-2 text-sm">
                    <p>{t("modelDecision", { decision: tk("decision_", String(open.payload.decision)) })}
                      {(open.payload.vetoes as string[])?.length ? <> · <span className="text-critical">{t("vetoes", { list: (open.payload.vetoes as string[]).join(", ") })}</span></> : null}</p>
                    <table className="text-xs w-full"><thead><tr className="text-muted text-left"><th>{t("feature")}</th><th className="text-right">{t("score")}</th></tr></thead><tbody>
                      {Object.entries(open.payload.features as Record<string, number>).map(([k, v]) =>
                        <tr key={k} className="border-t border-line"><td className="py-0.5">{k}</td><td className="text-right tabular-nums">{v.toFixed(2)}</td></tr>)}
                    </tbody></table>
                    <p className="text-urgent text-xs">{t("falseMergeWarning")}</p>
                    <div className="flex flex-wrap gap-2">
                      <button className="btn btn-primary" onClick={() => resolve(open, "link")}>{t("sameLink")}</button>
                      <button className="btn btn-ghost" onClick={() => resolve(open, "not_same")}>{t("differentPeople")}</button>
                    </div>
                  </div>
                )}
                {["document_mismatch", "document_type", "document"].includes(open.kind) && (
                  <div className="space-y-2 text-sm">
                    <DocumentViewer docId={typeof open.payload.document_id === "string" ? open.payload.document_id : open.ref_id} canCorrect={false} />
                    <div className="flex flex-wrap gap-2">
                      <button className="btn btn-primary" onClick={() => resolve(open, "confirm")}>{t("resolvedBtn")}</button>
                      <button className="btn btn-ghost" onClick={() => resolve(open, "reject")}>{t("dismiss")}</button>
                    </div>
                  </div>
                )}
              </Card>
            )}
          </div>
        </div>
      )}
      {merges.length > 0 && (
        <Card title={t("merges")} className="mt-5">
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
