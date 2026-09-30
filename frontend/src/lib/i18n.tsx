"use client";

import { createContext, useContext, useEffect, type ReactNode } from "react";
import { en, type Key } from "./i18n/en";
import { hi } from "./i18n/hi";
import { kn } from "./i18n/kn";
import { useLocal, writeLocal } from "./store";

export type Lang = "en" | "kn" | "hi";
export type { Key };

const dicts: Record<Lang, Record<Key, string>> = { en, kn, hi };
const LOCALE: Record<Lang, string> = { en: "en-IN", kn: "kn-IN", hi: "hi-IN" };

type Vars = Record<string, string | number | null | undefined>;

function fill(s: string, vars?: Vars): string {
  return vars ? s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] == null ? "—" : String(vars[k]))) : s;
}

export interface I18n {
  lang: Lang;
  setLang: (l: Lang) => void;
  /** a UI string, with {placeholders} filled */
  t: (k: Key, vars?: Vars) => string;
  /** a label for a status / finding / flag code (falls back to the code in readable form) */
  ts: (code: string) => string;
  /** a label for a prefixed code such as custodyType_arrest or docType_fir; `fallback` if there is none */
  tk: (prefix: string, code: string | null | undefined, fallback?: string) => string;
  /** a date in the current language (data dates are shown, month names are localised) */
  fd: (d?: string | null) => string;
  /** a timestamp (date + time) in the current language, in the viewer's time zone */
  fdt: (d?: string | null) => string;
  /** a punishment term as written by the engine ("3 years", "2 years 6 months", "imprisonment for life") */
  fterm: (term?: string | null) => string;
}

function make(lang: Lang, setLang: (l: Lang) => void): I18n {
  const dict = dicts[lang];
  const has = (k: string): k is Key => k in en;
  const t = (k: Key, vars?: Vars) => fill(dict[k] ?? en[k], vars);
  const tk = (prefix: string, code: string | null | undefined, fallback?: string) => {
    if (!code) return fallback ?? "—";
    const k = `${prefix}${code}`;
    return has(k) ? t(k) : (fallback ?? code.replaceAll("_", " "));
  };
  const ts = (code: string) => {
    if (has(`status_${code}`)) return t(`status_${code}` as Key);
    if (has(`code_${code}`)) return t(`code_${code}` as Key);
    return code.replaceAll("_", " ");
  };
  const fd = (d?: string | null) => {
    if (!d) return "—";
    const x = new Date(d.length === 10 ? d + "T00:00:00" : d);
    if (Number.isNaN(x.getTime())) return d;
    return x.toLocaleDateString(LOCALE[lang], { day: "2-digit", month: "short", year: "numeric" });
  };
  const fdt = (d?: string | null) => {
    if (!d) return "—";
    const x = new Date(d);
    if (Number.isNaN(x.getTime())) return d;
    return x.toLocaleString(LOCALE[lang], { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  };
  const fterm = (term?: string | null) => {
    if (!term) return "—";
    if (term === "imprisonment for life") return t("term_life");
    if (term === "death") return t("term_death");
    if (term === "fine only") return t("term_fine");
    const parts: string[] = [];
    const y = term.match(/(\d+) years?/), m = term.match(/(\d+) months?/);
    if (y) parts.push(y[1] === "1" ? t("term_year") : t("term_years", { n: y[1] }));
    if (m) parts.push(m[1] === "1" ? t("term_month") : t("term_months", { n: m[1] }));
    return parts.length ? parts.join(" ") : term;
  };
  return { lang, setLang, t, ts, tk, fd, fdt, fterm };
}

const Ctx = createContext<I18n>(make("en", () => {}));

export function I18nProvider({ children }: { children: ReactNode }) {
  const saved = useLocal("nyaya_lang");
  const lang: Lang = saved && saved in dicts ? (saved as Lang) : "en";
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const setLang = (l: Lang) => writeLocal("nyaya_lang", l);
  return <Ctx.Provider value={make(lang, setLang)}>{children}</Ctx.Provider>;
}

export const useI18n = () => useContext(Ctx);

/** Map an API failure to a localised message (the server's English text is not shown to the user). */
export function apiErrorText(t: I18n["t"], err: unknown): string {
  const e = err as { status?: number; message?: string };
  switch (e?.status) {
    case 0: return t("err_network");
    case 401: return t("err_unauthorized");
    case 403: return t("err_forbidden");
    case 404: return t("err_notFound");
    case 409: case 422: return `${t("err_validation")} ${e.message ?? ""}`.trim();
    case 429: return t("err_tooMany");
    default: return e?.status && e.status >= 500 ? t("err_server") : (e?.message ?? t("err_server"));
  }
}
