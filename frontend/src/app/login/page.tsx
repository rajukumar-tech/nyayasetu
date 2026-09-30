"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Logo } from "@/components/Logo";
import { LangSelect } from "@/components/Shell";
import { ErrorBox } from "@/components/ui";
import { API_URL } from "@/lib/api";
import { homeFor, useAuth } from "@/lib/auth";
import { apiErrorText, useI18n, type Key } from "@/lib/i18n";
import { useLocal, writeLocal } from "@/lib/store";

const DEMO: [string, Key][] = [
  ["lawyer@nyayasetu.test", "role_legal_aid_lawyer"],
  ["jail@nyayasetu.test", "role_jail_staff"],
  ["dlsa@nyayasetu.test", "role_dlsa_admin"],
  ["reviewer@nyayasetu.test", "role_reviewer"],
  ["admin@nyayasetu.test", "role_system_admin"],
];
const POINTS: Key[] = ["loginPoint1", "loginPoint2", "loginPoint3"];

export default function Login() {
  const { login, user, ready } = useAuth();
  const { t } = useI18n();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState(false);
  const notice = useLocal("nyaya_notice");

  // demo accounts are listed ONLY when the server says it runs in demo mode — never on a real deployment
  useEffect(() => {
    fetch(`${API_URL}/api/health`).then((r) => r.json()).then((h) => setDemo(Boolean(h.demo_mode))).catch(() => setDemo(false));
  }, []);
  // already signed in → straight to the home page
  useEffect(() => {
    if (ready && user) router.replace(homeFor(user.role));
  }, [ready, user, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const u = await login(email.trim(), password);
      writeLocal("nyaya_notice", null);
      router.replace(homeFor(u.role));
    } catch (err) {
      const s = (err as { status?: number }).status;
      setError(s === 401 ? t("err_badLogin") : apiErrorText(t, err));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen grid lg:grid-cols-[1.1fr_1fr] bg-paper">
      {/* ------------------------------------------------ brand panel */}
      <section className="relative overflow-hidden bg-navy text-white px-5 py-5 sm:px-10 sm:py-8 lg:px-14 lg:py-12 flex flex-col">
        <div aria-hidden="true" className="pointer-events-none absolute -right-24 -bottom-24 h-80 w-80 rounded-full border-[36px] border-white/5" />
        <div aria-hidden="true" className="pointer-events-none absolute right-16 top-24 h-40 w-40 rounded-full border-[18px] border-white/5" />
        <div className="flex items-center gap-3">
          <Logo className="h-10 w-10 text-white" />
          <div>
            <p className="text-xl font-bold leading-tight">{t("app")}</p>
            <p className="text-xs text-white/70">{t("tagline")}</p>
          </div>
        </div>
        <div className="mt-4 sm:mt-10 lg:mt-auto max-w-lg">
          <h1 className="text-lg sm:text-3xl lg:text-4xl font-bold leading-snug">{t("decides")}</h1>
          <p className="mt-4 text-white/80 leading-relaxed hidden sm:block">{t("loginIntro")}</p>
          <ul className="mt-6 space-y-3 hidden sm:block">
            {POINTS.map((k) => (
              <li key={k} className="flex gap-3 text-white/90">
                <span aria-hidden="true" className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white/15 text-xs">✓</span>
                <span>{t(k)}</span>
              </li>
            ))}
          </ul>
        </div>
        <p className="mt-10 lg:mt-auto pt-8 text-xs text-white/60 max-w-lg hidden sm:block">{t("disclaimer")}</p>
      </section>

      {/* ------------------------------------------------ sign-in form */}
      <section className="flex items-start sm:items-center justify-center px-4 py-5 sm:py-10 sm:px-8">
        <div className="w-full max-w-md">
          <form onSubmit={submit} className="card p-6 sm:p-8 shadow-sm space-y-5" aria-labelledby="signin-h">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 id="signin-h" className="text-2xl font-semibold">{t("signIn")}</h2>
                <p className="text-sm text-muted mt-1">{t("loginWelcome")}</p>
              </div>
              <LangSelect className="border border-line rounded-md px-2 py-1.5 text-sm bg-surface" />
            </div>

            {notice && <p role="status" className="rounded-md bg-urgent-bg text-urgent p-3 text-sm">{t("sessionExpired")}</p>}
            <ErrorBox error={error} />

            <label className="block">
              <span className="label">{t("email")}</span>
              <input type="email" required autoFocus autoComplete="username" inputMode="email" value={email}
                placeholder={t("emailPlaceholder")} onChange={(e) => setEmail(e.target.value)}
                className="mt-1 w-full border border-line rounded-lg px-3 py-2.5 bg-surface focus:border-navy-2" />
            </label>
            <label className="block">
              <span className="label">{t("password")}</span>
              <span className="relative mt-1 block">
                <input type={show ? "text" : "password"} required autoComplete="current-password" value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full border border-line rounded-lg px-3 py-2.5 pr-24 bg-surface focus:border-navy-2" />
                <button type="button" onClick={() => setShow((s) => !s)} aria-pressed={show}
                  className="absolute inset-y-0 right-0 px-3 text-sm text-navy-2 underline-offset-2 hover:underline">
                  {show ? t("hidePassword") : t("showPassword")}
                </button>
              </span>
            </label>

            <button className="btn btn-primary w-full justify-center !py-2.5 text-base" disabled={busy || !email || !password}>
              {busy && <span aria-hidden="true" className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />}
              {busy ? t("signingIn") : t("signIn")}
            </button>
            <p className="text-xs text-muted">{t("forgotPassword")}</p>

            {demo && (
              <div className="rounded-lg border border-dashed border-urgent/40 bg-urgent-bg/60 p-3">
                <p className="label !text-urgent mb-1">{t("demoAccounts")}</p>
                <p className="text-xs text-muted mb-2">{t("demoNote")}</p>
                <div className="flex flex-wrap gap-1.5">
                  {DEMO.map(([e, r]) => (
                    <button key={e} type="button" title={e} onClick={() => setEmail(e)}
                      className={`rounded-full border px-2.5 py-1 text-xs font-medium ${email === e ? "border-navy bg-navy text-white" : "border-line bg-surface hover:bg-neutral-bg"}`}>
                      {t(r)}
                    </button>
                  ))}
                </div>
                <p className="text-xs text-muted mt-2">{t("demoPasswordNote")}</p>
              </div>
            )}
          </form>
          <p className="mt-3 text-xs text-muted text-center sm:hidden">{t("disclaimer")}</p>
          <p className="mt-4 flex items-center justify-center gap-2 text-xs text-muted text-center">
            <span aria-hidden="true">🔒</span>{t("loginSecure")}
          </p>
        </div>
      </section>
    </main>
  );
}
