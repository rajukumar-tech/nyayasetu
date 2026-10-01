"use client";

import { useEffect, useState } from "react";
import { useDialog } from "@/components/Dialog";
import { Shell } from "@/components/Shell";
import { Card, ErrorBox, Field, Loading, Notice, inputCls } from "@/components/ui";
import { api } from "@/lib/api";
import { apiErrorText, useI18n } from "@/lib/i18n";

interface LawyerRow { id: string; name: string; email: string; active: boolean; status: "active" | "pending_approval" | "deactivated"; prisoners: number }

export default function Lawyers() {
  const { t } = useI18n();
  const dialog = useDialog();
  const [rows, setRows] = useState<LawyerRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", email: "", password: "", approve: true });
  const [busy, setBusy] = useState(false);
  const load = () => api<LawyerRow[]>("/api/lawyers").then(setRows).catch((e) => setError(apiErrorText(t, e)));
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null); setNotice(null);
    try {
      await api("/api/lawyers", { method: "POST", body: JSON.stringify(form) });
      setNotice(t("lawyerCreated", { name: form.name }));
      setForm({ name: "", email: "", password: "", approve: true });
      load();
    } catch (err) { setError(apiErrorText(t, err)); } finally { setBusy(false); }
  }
  async function setActive(l: LawyerRow, on: boolean) {
    if (!on && !(await dialog.confirm({ title: t("deactivate"), message: t("deactivateConfirm", { name: l.name, n: l.prisoners }),
      confirmText: t("deactivate"), danger: true }))) return;
    setError(null);
    try {
      const r = await api<{ unassigned_prisoners?: number }>(`/api/lawyers/${l.id}/${on ? "activate" : "deactivate"}`, { method: "POST" });
      setNotice(on ? t("lawyerActivated", { name: l.name }) : t("lawyerDeactivated", { name: l.name, n: r.unassigned_prisoners ?? 0 }));
      load();
    } catch (err) { setError(apiErrorText(t, err)); }
  }
  const status = (l: LawyerRow) => l.status === "active" ? t("accountActive") : l.status === "pending_approval" ? t("accountPending") : t("accountInactive");

  return (
    <Shell roles={["dlsa_admin"]}>
      <h1 className="text-2xl font-bold mb-2">{t("lawyersTitle")}</h1>
      <p className="text-sm text-muted mb-4 max-w-3xl">{t("lawyersIntro")}</p>
      <ErrorBox error={error} />
      <Notice text={notice} />
      <div className="grid lg:grid-cols-3 gap-4">
        <Card title={t("addLawyer")}>
          <form onSubmit={create} className="space-y-3">
            <Field label={t("lawyerName")}><input required minLength={2} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={inputCls} /></Field>
            <Field label={t("email")}><input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className={inputCls} /></Field>
            <Field label={t("tempPassword")}><input required minLength={10} type="password" autoComplete="new-password" value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })} className={inputCls} /></Field>
            <label className="flex gap-2 text-sm"><input type="checkbox" checked={form.approve} onChange={(e) => setForm({ ...form, approve: e.target.checked })} />{t("approveNow")}</label>
            <button className="btn btn-primary" disabled={busy}>{busy ? t("working") : t("addLawyer")}</button>
          </form>
        </Card>
        <div className="lg:col-span-2 min-w-0">
          {!rows ? (!error && <Loading />) : (
            <div className="card overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-neutral-bg text-left"><tr>
                  <th className="px-3 py-2">{t("name")}</th><th className="px-3 py-2">{t("status")}</th>
                  <th className="px-3 py-2 text-right">{t("prisonersCount")}</th><th className="px-3 py-2"><span className="sr-only">{t("action")}</span></th></tr></thead>
                <tbody>
                  {rows.map((l) => (
                    <tr key={l.id} className="border-t border-line align-top">
                      <td className="px-3 py-2"><div className="font-semibold">{l.name}</div><div className="text-xs text-muted break-all">{l.email}</div></td>
                      <td className={`px-3 py-2 ${l.active ? "text-ok" : "text-urgent"}`}>{status(l)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{l.prisoners}</td>
                      <td className="px-3 py-2">
                        {l.active ? <button className="btn btn-danger !py-1 !text-xs" onClick={() => setActive(l, false)}>{t("deactivate")}</button>
                          : <button className="btn btn-primary !py-1 !text-xs" onClick={() => setActive(l, true)}>{l.status === "pending_approval" ? t("approve_account") : t("activate")}</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {rows.length === 0 && <p className="p-4 text-muted">{t("noItems")}</p>}
            </div>
          )}
        </div>
      </div>
    </Shell>
  );
}
