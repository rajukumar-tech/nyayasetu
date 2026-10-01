"use client";

import { useEffect, useState } from "react";
import { useDialog } from "@/components/Dialog";
import { Shell } from "@/components/Shell";
import { Card, ErrorBox, Loading, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { apiErrorText, useI18n, type Key } from "@/lib/i18n";

interface Rec { key: string; title: string; punishment_summary: string; max: string | null; kind: string; verified: boolean;
  verified_by?: string; source: string; notes?: string; special_law: boolean }
interface Legal { version: string; records: Rec[]; rules: { key: string; ref: string; verified: boolean }[]; unverified: number; demo_verified_only: number }
interface AuditRow { id: number; ts: string; role: string; action: string; entity_type: string; entity_id?: string; detail?: string;
  user_name?: string | null; user_email?: string | null; outcome: "ok" | "denied" }
interface UserRow { id: string; email: string; name: string; role: string; active: boolean }
export default function Admin() {
  const { t, tk, fdt } = useI18n();
  const { user } = useAuth();
  const dialog = useDialog();
  const [legal, setLegal] = useState<Legal | null>(null);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [session, setSession] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const after = user?.session_audit_id ? user.session_audit_id - 1 : null;
  const loadAudit = (s = session) => api<AuditRow[]>(`/api/admin/audit?limit=300${s && after != null ? `&after_id=${after}` : ""}`)
    .then(setAudit).catch((e) => setError(apiErrorText(t, e)));
  const load = () => {
    api<Legal>("/api/legal/records").then(setLegal).catch((e) => setError(apiErrorText(t, e)));
    api<UserRow[]>("/api/admin/users").then(setUsers).catch(() => {});
  };
  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps
  // the page mounts before the signed-in user is known: (re)load the audit log once the session id is available,
  // otherwise "This session" would briefly show every entry
  useEffect(() => { if (user) loadAudit(); }, [after, user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function verify(key: string, verified: boolean) {
    const note = await dialog.ask({ title: verified ? t("verify") : t("markUnverified"), label: t("verifyPrompt", { key }),
      minLength: 5, confirmText: verified ? t("verify") : t("markUnverified") });
    if (note == null) return;
    try {
      await api(`/api/legal/records/${encodeURIComponent(key)}/verify`, { method: "POST", body: JSON.stringify({ verified, note }) });
      load(); loadAudit();
    } catch (e) { setError(apiErrorText(t, e)); }
  }
  async function nightly() {
    try {
      const r = await api<{ persons: number; alerts_created: number; escalated: number }>("/api/admin/run-nightly", { method: "POST" });
      setMsg(t("nightlyResult", { persons: r.persons, alerts: r.alerts_created, escalated: r.escalated }));
      loadAudit();
    } catch (e) { setError(apiErrorText(t, e)); }
  }
  async function toggleUser(u: UserRow) {
    if (u.active && !(await dialog.confirm({ title: t("deactivate"), message: t("deactivateUserConfirm", { name: u.name }),
      confirmText: t("deactivate"), danger: true }))) return;
    try { await api(`/api/admin/users/${u.id}`, { method: "PATCH", body: JSON.stringify({ active: !u.active }) }); load(); loadAudit(); }
    catch (e) { setError(apiErrorText(t, e)); }
  }
  async function resetPw(u: UserRow) {
    const pw = await dialog.ask({ title: t("resetPassword"), label: t("newPasswordPrompt", { email: u.email }), type: "password",
      minLength: 10, confirmText: t("resetPassword") });
    if (pw == null) return;
    try { await api(`/api/admin/users/${u.id}/password`, { method: "POST", body: JSON.stringify({ password: pw }) }); setMsg(t("passwordReset")); loadAudit(); }
    catch (e) { setError(apiErrorText(t, e)); }
  }

  return (
    <Shell roles={["system_admin"]}>
      <div className="flex flex-wrap justify-between gap-2 mb-4">
        <h1 className="text-2xl font-bold">{t("admin")}</h1>
        <button className="btn btn-primary" onClick={nightly}>{t("runNightly")}</button>
      </div>
      <ErrorBox error={error} />
      <Notice text={msg} />

      <Card title={t("audit")} className="mb-5" actions={
        <div role="group" className="flex gap-1">
          <button aria-pressed={session} className={`btn ${session ? "btn-primary" : "btn-ghost"} !py-1 !text-xs`} onClick={() => { setSession(true); loadAudit(true); }}>{t("auditThisSession")}</button>
          <button aria-pressed={!session} className={`btn ${!session ? "btn-primary" : "btn-ghost"} !py-1 !text-xs`} onClick={() => { setSession(false); loadAudit(false); }}>{t("auditAll")}</button>
        </div>}>
        {session && <p className="text-xs text-muted mb-2">{t("auditSessionNote", { n: audit.length })}</p>}
        <div className="overflow-x-auto max-h-96">
          <table className="w-full text-xs">
            <thead className="text-left text-muted sticky top-0 bg-surface"><tr>
              <th className="py-1 pr-2">{t("time")}</th><th className="pr-2">{t("user")}</th><th className="pr-2">{t("role")}</th>
              <th className="pr-2">{t("actionCol")}</th><th className="pr-2">{t("target")}</th><th className="pr-2">{t("outcome")}</th><th>{t("detail")}</th></tr></thead>
            <tbody>{audit.map((a) => (
              <tr key={a.id} className="border-t border-line align-top">
                <td className="py-0.5 pr-2 whitespace-nowrap">{fdt(a.ts)}</td>
                <td className="pr-2">{a.user_name ?? "—"}</td>
                <td className="pr-2">{tk("role_", a.role)}</td>
                <td className="pr-2">{tk("act_", a.action)}</td>
                <td className="pr-2 break-all">{a.entity_type} {a.entity_id}</td>
                <td className={`pr-2 ${a.outcome === "denied" ? "text-critical font-semibold" : "text-ok"}`}>{t(`outcome_${a.outcome}` as Key)}</td>
                <td lang="en" className="break-words">{a.detail}</td>
              </tr>
            ))}</tbody>
          </table>
          {audit.length === 0 && <p className="p-2 text-muted">{t("noItems")}</p>}
        </div>
      </Card>

      <Card title={t("users")} className="mb-5">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-muted"><tr><th className="py-1 pr-2">{t("name")}</th><th className="pr-2">{t("role")}</th><th className="pr-2">{t("status")}</th><th /></tr></thead>
            <tbody>{users.map((u) => (
              <tr key={u.id} className="border-t border-line align-top">
                <td className="py-1 pr-2"><div className="font-medium">{u.name}</div><div className="text-xs text-muted break-all">{u.email}</div></td>
                <td className="pr-2">{tk("role_", u.role)}</td>
                <td className={`pr-2 ${u.active ? "text-ok" : "text-urgent"}`}>{u.active ? t("accountActive") : t("accountInactive")}</td>
                <td className="flex flex-wrap gap-1 py-1">
                  {u.id !== user?.id && <button className={`btn ${u.active ? "btn-danger" : "btn-primary"} !py-0.5 !text-xs`} onClick={() => toggleUser(u)}>{u.active ? t("deactivate") : t("activate")}</button>}
                  <button className="btn btn-ghost !py-0.5 !text-xs" onClick={() => resetPw(u)}>{t("resetPassword")}</button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </Card>

      {!legal ? <Loading /> : (
        <Card title={t("legalDataVersion", { v: legal.version })}
          actions={<span className="text-sm font-semibold"><span className="text-review">{t("unverifiedCount", { n: legal.unverified })}</span>
            {legal.demo_verified_only > 0 && <span className="text-critical"> · {t("demoVerifiedCount", { n: legal.demo_verified_only })}</span>}</span>}>
          <p className="text-sm text-muted mb-2">{t("legalNote")}</p>
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t("filterRecords")} aria-label={t("filterRecords")}
            className="border border-line rounded-md px-3 py-1.5 text-sm mb-2 w-full sm:w-64" />
          <div className="overflow-x-auto max-h-[28rem]">
            <table className="w-full text-sm">
              <thead className="text-left text-muted sticky top-0 bg-surface"><tr><th className="py-1 pr-2">{t("record")}</th><th>{t("maximum")}</th><th>{t("status")}</th><th /></tr></thead>
              <tbody>
                {[...legal.records.map((r) => ({ ...r, isRule: false })),
                  ...legal.rules.map((r) => ({ key: r.key, title: r.ref, punishment_summary: "", max: null, kind: "rule", verified: r.verified,
                    source: "", special_law: false, isRule: true, verified_by: undefined }))]
                  .filter((r) => !filter || r.key.toLowerCase().includes(filter.toLowerCase()) || r.title.toLowerCase().includes(filter.toLowerCase()))
                  .map((r) => (
                    <tr key={r.key} className="border-t border-line align-top">
                      <td className="py-1.5 pr-2"><div className="font-medium">{r.key}</div><div className="text-xs text-muted" lang="en">{r.title}</div>
                        {r.punishment_summary && <div className="text-xs" lang="en">{r.punishment_summary}</div>}</td>
                      <td className="pr-2">{r.max ?? "—"}</td>
                      <td className="pr-2 text-xs">{r.verified
                        ? <span className={r.verified_by?.startsWith("DEMO") ? "text-urgent" : "text-ok"}>{r.verified_by ? t("verifiedBy", { by: r.verified_by }) : t("legalVerified")}</span>
                        : <span className="text-review font-semibold">{t("needsLegalVerification")}</span>}</td>
                      <td><button className="btn btn-ghost !py-0.5 !text-xs" onClick={() => verify(r.key, !r.verified)}>{r.verified ? t("markUnverified") : t("verify")}</button></td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </Shell>
  );
}
