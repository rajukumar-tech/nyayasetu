"use client";

import Link from "next/link";
import { useState } from "react";
import { Shell } from "@/components/Shell";
import { Card, ErrorBox, Field, Notice, inputCls } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { apiErrorText, useI18n } from "@/lib/i18n";

type Charge = { act: string; section: string };

export default function NewPrisoner() {
  const { t, ts } = useI18n();
  const { user } = useAuth();
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ name: "", relative_name: "", relation: "s/o", gender: "male", dob: "", address: "",
    jail: "", district: "", court: "", case_number: "", cnr: "", fir_number: "", police_station: "", offence_date: "",
    arrest_date: "", first_remand_date: "", charge_sheet_date: "", custody_status: "in_custody", status_change_date: "" });
  const [charges, setCharges] = useState<Charge[]>([{ act: "BNS", section: "" }]);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{ id: string; status: string; possible_duplicates_queued: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const isJail = user?.role === "jail_staff";
  const n = (v: string) => (v.trim() ? v.trim() : null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null); setCreated(null);
    try {
      const body = {
        name: f.name, relative_name: n(f.relative_name), relation: n(f.relative_name) ? f.relation : null, gender: f.gender,
        dob: n(f.dob), address: n(f.address), jail: isJail ? null : n(f.jail), district: n(f.district),
        case: { court: f.court, case_number: n(f.case_number), cnr: n(f.cnr), fir_number: n(f.fir_number),
          police_station: n(f.police_station), offence_date: n(f.offence_date), arrest_date: f.arrest_date,
          first_remand_date: n(f.first_remand_date), charge_sheet_date: n(f.charge_sheet_date), custody_status: f.custody_status,
          status_change_date: f.custody_status === "in_custody" ? null : n(f.status_change_date),
          charges: charges.filter((c) => c.section.trim()) },
      };
      setCreated(await api("/api/persons", { method: "POST", body: JSON.stringify(body) }));
    } catch (err) {
      const e = err as { status?: number; message?: string };
      // a duplicate: say so in the user's language and keep the server's detail (which record matched) as data
      setError(e.status === 409 && /already exists/.test(e.message ?? "") ? `${t("duplicateExists")} (${e.message})` : apiErrorText(t, err));
    } finally { setBusy(false); }
  }

  const date = (k: keyof typeof f, label: string, required = false) => (
    <Field label={`${label}${required ? "" : ` (${t("optional")})`}`}>
      <input type="date" max={today} required={required} value={f[k]} onChange={set(k)} className={inputCls} />
    </Field>
  );

  return (
    <Shell roles={["jail_staff"]}>
      <h1 className="text-2xl font-bold mb-2">{t("newPrisonerTitle")}</h1>
      <p className="text-sm text-muted mb-4 max-w-3xl">{t("newPrisonerIntro")}</p>
      <ErrorBox error={error} />
      {created && (
        <div className="mb-4">
          <Notice text={t("createdNote", { status: ts(created.status) })} />
          {created.possible_duplicates_queued > 0 && <Notice tone="urgent" text={t("possibleDuplicates", { n: created.possible_duplicates_queued })} />}
          <Link href={`/prisoners/${created.id}`} className="btn btn-primary">{t("openRecord")}</Link>
        </div>
      )}
      <form onSubmit={submit} className="space-y-4">
        <Card title={t("personalDetails")}>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <Field label={t("fullName")}><input required minLength={2} value={f.name} onChange={set("name")} className={inputCls} /></Field>
            <Field label={`${t("relativeName")} (${t("optional")})`}><input value={f.relative_name} onChange={set("relative_name")} className={inputCls} /></Field>
            <Field label={t("relation")}><select value={f.relation} onChange={set("relation")} className={inputCls}>
              <option value="s/o">s/o</option><option value="d/o">d/o</option><option value="w/o">w/o</option></select></Field>
            <Field label={t("gender")}><select value={f.gender} onChange={set("gender")} className={inputCls}>
              <option value="male">{t("gender_male")}</option><option value="female">{t("gender_female")}</option><option value="other">{t("gender_other")}</option></select></Field>
            {date("dob", t("dob"))}
            <Field label={`${t("address")} (${t("optional")})`}><input value={f.address} onChange={set("address")} className={inputCls} /></Field>
            <Field label={t("jailLabel")}>{isJail ? <input readOnly value={user?.jail ?? ""} className={`${inputCls} bg-neutral-bg`} />
              : <input required value={f.jail} onChange={set("jail")} className={inputCls} />}</Field>
            <Field label={`${t("districtLabel")}${isJail ? ` (${t("optional")})` : ""}`}><input required={!isJail} value={f.district} onChange={set("district")} className={inputCls} /></Field>
          </div>
        </Card>
        <Card title={t("caseDetails")}>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <Field label={t("court")}><input required minLength={2} value={f.court} onChange={set("court")} className={inputCls} /></Field>
            <Field label={`${t("caseNumber")} (${t("optional")})`}><input value={f.case_number} onChange={set("case_number")} className={inputCls} /></Field>
            <Field label={`${t("cnr")} (${t("optional")})`}><input maxLength={32} value={f.cnr} onChange={set("cnr")} className={inputCls} /></Field>
            <Field label={`${t("firNumber")} (${t("optional")})`}><input value={f.fir_number} onChange={set("fir_number")} className={inputCls} /></Field>
            <Field label={`${t("policeStation")} (${t("optional")})`}><input value={f.police_station} onChange={set("police_station")} className={inputCls} /></Field>
            {date("offence_date", t("offenceDate"))}
            {date("arrest_date", t("arrestDate"), true)}
            {date("first_remand_date", t("firstRemandDate"))}
            {date("charge_sheet_date", t("chargeSheetDate"))}
            <Field label={t("custodyStatus")}><select value={f.custody_status} onChange={set("custody_status")} className={inputCls}>
              <option value="in_custody">{t("cs_in_custody")}</option><option value="on_bail">{t("cs_on_bail")}</option>
              <option value="released">{t("cs_released")}</option></select></Field>
            {f.custody_status !== "in_custody" && date("status_change_date", t("statusChangeDate"), true)}
          </div>
          <fieldset className="mt-4">
            <legend className="label mb-1">{t("sectionsHint")}</legend>
            <div className="space-y-2">
              {charges.map((c, i) => (
                <div key={i} className="flex flex-wrap gap-2 items-end">
                  <Field label={t("act")}><select value={c.act} onChange={(e) => setCharges(charges.map((x, j) => (j === i ? { ...x, act: e.target.value } : x)))} className={inputCls}>
                    {["BNS", "IPC", "NDPS", "POCSO", "ARMS", "SCST", "UAPA", "PMLA"].map((a) => <option key={a} value={a}>{a}</option>)}</select></Field>
                  <Field label={t("section")}><input required={i === 0} value={c.section} placeholder="303(2)"
                    onChange={(e) => setCharges(charges.map((x, j) => (j === i ? { ...x, section: e.target.value } : x)))} className={inputCls} /></Field>
                  {charges.length > 1 && <button type="button" className="btn btn-ghost" onClick={() => setCharges(charges.filter((_, j) => j !== i))}>{t("removeSection")}</button>}
                </div>
              ))}
              <button type="button" className="btn btn-ghost" onClick={() => setCharges([...charges, { act: "BNS", section: "" }])}>{t("addSection")}</button>
            </div>
          </fieldset>
        </Card>
        <button className="btn btn-primary" disabled={busy}>{busy ? t("working") : t("createPrisoner")}</button>
      </form>
    </Shell>
  );
}
