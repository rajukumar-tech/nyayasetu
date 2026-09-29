"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ErrorBox } from "@/components/ui";
import { homeFor, useAuth } from "@/lib/auth";
import { useI18n, type Lang } from "@/lib/i18n";
import { useLocal, writeLocal } from "@/lib/store";

const DEMO = [
  ["lawyer@nyayasetu.test", "Legal-aid lawyer"],
  ["jail@nyayasetu.test", "Jail staff"],
  ["dlsa@nyayasetu.test", "DLSA / UTRC"],
  ["reviewer@nyayasetu.test", "Reviewer"],
  ["admin@nyayasetu.test", "System admin"],
];

export default function Login() {
  const { login } = useAuth();
  const { t, lang, setLang } = useI18n();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const notice = useLocal("nyaya_notice");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const u = await login(email, password);
      writeLocal("nyaya_notice", null);
      router.replace(homeFor(u.role));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen grid md:grid-cols-2">
      <div className="bg-navy text-white p-10 flex flex-col justify-between">
        <div>
          <p className="text-sm text-white/70 tracking-wide uppercase">{t("tagline")}</p>
          <h1 className="text-4xl font-bold mt-3">{t("app")}</h1>
          <p className="mt-6 max-w-md text-white/85 leading-relaxed">
            Builds each undertrial prisoner&apos;s legal picture from messy records, computes Section 479 BNSS and
            default-bail eligibility with a deterministic rule engine, and drafts grounded applications for legal-aid
            lawyers to review.
          </p>
        </div>
        <p className="text-xs text-white/60 mt-10">{t("disclaimer")}</p>
      </div>
      <div className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="card w-full max-w-sm p-6 space-y-4" aria-labelledby="signin-h">
          <div className="flex justify-between items-center">
            <h2 id="signin-h" className="text-xl font-semibold">{t("signIn")}</h2>
            <select aria-label={t("language")} value={lang} onChange={(e) => setLang(e.target.value as Lang)}
              className="border border-line rounded-md px-2 py-1 text-sm">
              <option value="en">English</option><option value="kn">ಕನ್ನಡ</option><option value="hi">हिन्दी</option>
            </select>
          </div>
          {notice && <p role="status" className="card bg-urgent-bg text-urgent p-3 text-sm">{notice}</p>}
          <ErrorBox error={error} />
          <label className="block">
            <span className="label">{t("email")}</span>
            <input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full border border-line rounded-md px-3 py-2" />
          </label>
          <label className="block">
            <span className="label">{t("password")}</span>
            <input type="password" required autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} className="mt-1 w-full border border-line rounded-md px-3 py-2" />
          </label>
          <button className="btn btn-primary w-full justify-center" disabled={busy}>{busy ? "…" : t("signIn")}</button>
          <div className="pt-2 border-t border-line">
            <p className="label mb-2">Demo accounts (synthetic data)</p>
            <ul className="text-sm space-y-1">
              {DEMO.map(([e, r]) => (
                <li key={e}>
                  <button type="button" className="underline underline-offset-2 text-navy-2" onClick={() => setEmail(e)}>{r}</button>
                  <span className="text-muted"> — {e}</span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted mt-2">Password for all demo accounts is in the project README.</p>
          </div>
        </form>
      </div>
    </main>
  );
}
