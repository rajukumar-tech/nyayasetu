"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { Logo } from "@/components/Logo";
import type { Role } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useI18n, type Key, type Lang } from "@/lib/i18n";

const NAV: Record<Role, { href: string; key: Key }[]> = {
  legal_aid_lawyer: [{ href: "/lawyer", key: "myPrisoners" }, { href: "/alerts", key: "alerts" }],
  jail_staff: [{ href: "/jail", key: "prisoners" }, { href: "/prisoners/new", key: "addPrisoner" }, { href: "/alerts", key: "alerts" }],
  dlsa_admin: [{ href: "/dlsa", key: "district" }, { href: "/lawyers", key: "lawyers" }, { href: "/alerts", key: "alerts" }],
  reviewer: [{ href: "/reviewer", key: "review" }],
  // the admin runs the system: dashboard (register, assignment, accounts, audit), new prisoners, lawyer accounts
  system_admin: [{ href: "/admin", key: "admin" }, { href: "/prisoners/new", key: "addPrisoner" }, { href: "/lawyers", key: "lawyers" }],
};

export function LangSelect({ className = "" }: { className?: string }) {
  const { t, lang, setLang } = useI18n();
  return (
    <>
      <label className="sr-only" htmlFor="lang">{t("language")}</label>
      <select id="lang" value={lang} onChange={(e) => setLang(e.target.value as Lang)} className={className}>
        <option value="en">{t("lang_en")}</option>
        <option value="kn">{t("lang_kn")}</option>
        <option value="hi">{t("lang_hi")}</option>
      </select>
    </>
  );
}

export function Shell({ children, roles }: { children: ReactNode; roles?: Role[] }) {
  const { user, ready, logout } = useAuth();
  const { t } = useI18n();
  const router = useRouter();
  const path = usePathname();
  useEffect(() => {
    if (ready && !user) router.replace("/login");
  }, [ready, user, router]);
  if (!ready || !user) return <p className="p-8 text-muted" role="status">{t("loading")}</p>;
  const allowed = !roles || roles.includes(user.role);
  return (
    <div className="min-h-screen flex flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:m-2 focus:p-2 focus:bg-surface">{t("skipToContent")}</a>
      <header className="bg-navy text-white">
        <div className="mx-auto max-w-7xl px-4 py-3 flex flex-wrap items-center gap-x-6 gap-y-2">
          <Link href="/" className="flex items-center gap-2 min-w-0">
            <Logo className="h-7 w-7 text-white" />
            <span className="text-lg font-bold tracking-tight">{t("app")}</span>
            <span className="hidden lg:inline text-xs text-white/70">{t("tagline")}</span>
          </Link>
          <nav aria-label={t("nav_main")} className="flex gap-1 flex-wrap">
            {NAV[user.role].map((n) => (
              <Link key={n.href} href={n.href}
                className={`px-3 py-1.5 rounded-md text-sm font-medium ${path === n.href || (n.href !== "/prisoners/new" && path.startsWith(n.href + "/") && !path.startsWith("/prisoners/new")) ? "bg-white/15" : "hover:bg-white/10"}`}>
                {t(n.key)}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex flex-wrap items-center gap-3 text-sm">
            <LangSelect className="bg-navy-2 text-white rounded-md px-2 py-1 border border-white/20" />
            <span className="hidden sm:inline text-white/80" title={user.email}>{user.name} · {t(`role_${user.role}` as Key)}</span>
            <button onClick={() => logout()} className="underline underline-offset-2 hover:text-white/80">{t("signOut")}</button>
          </div>
        </div>
      </header>
      <div className="bg-urgent-bg border-b border-line text-urgent text-xs">
        <p className="mx-auto max-w-7xl px-4 py-1.5">{t("disclaimer")} <strong>{t("decides")}</strong></p>
      </div>
      <main id="main" className="flex-1 mx-auto w-full max-w-7xl px-4 py-6 min-w-0">
        {allowed ? children : <p role="alert" className="card border-critical/40 bg-critical-bg text-critical p-4">{t("roleCannotOpen")}</p>}
      </main>
      <footer className="text-xs text-muted text-center py-4 border-t border-line px-4">{t("footer")}</footer>
    </div>
  );
}
