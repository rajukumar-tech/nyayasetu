"use client";

import { createContext, useContext, useEffect, type ReactNode } from "react";
import { useLocal, writeLocal } from "./store";

export type Lang = "en" | "kn" | "hi";

const en = {
  app: "NyayaSetu",
  tagline: "Bridge to justice — undertrial decision support",
  disclaimer: "Decision support for a qualified lawyer. Not legal advice. Verify all sections and citations.",
  signIn: "Sign in", email: "Email", password: "Password", signOut: "Sign out",
  myPrisoners: "My prisoners", prisoners: "Prisoners", alerts: "Alerts", review: "Review queue", district: "District",
  admin: "Admin", legalData: "Legal data", audit: "Audit log",
  search: "Search by name", status: "Status", custody: "Custody", days: "days", overdue: "overdue",
  eligibleFrom: "Eligible from", projected: "Projected", priority: "Priority", charges: "Charges", jail: "Jail",
  overview: "Eligibility", timeline: "Timeline", facts: "Facts & documents", insights: "Defense insights", drafts: "Drafts",
  trace: "How this was decided", needsVerification: "Needs verification", flags: "Flags", findings: "Other routes & alerts",
  interpretations: "Readings", countedDetention: "Counted detention", threshold: "Threshold", maximum: "Maximum",
  firstTime: "First-time offender", recompute: "Recompute", upload: "Upload document", uploading: "Uploading…",
  accept: "Accept", reject: "Reject", confirm: "Confirm", correct: "Correct", evidence: "Evidence in the record",
  nextSteps: "What to do next", similarJudgments: "Similar judgments (retrieved, never generated)",
  newDraft: "New draft", language: "Language", create: "Create", exportDocx: "Export DOCX", exportPdf: "Export PDF",
  approve: "Approve", save: "Save edits", grounding: "Grounding", verifier: "Verifier",
  acknowledge: "Acknowledge", noItems: "Nothing here.", loading: "Loading…",
  eligibleApply: "Eligible to apply — the court may still order continued detention for recorded reasons.",
  needsLegalVerification: "needs legal verification",
  superintendentApp: "Prepare superintendent's application",
  heatmap: "Overdue undertrials by district", workload: "Lawyer workload", vulnerable: "Vulnerable",
  avgDetention: "Avg detention (days)", assign: "Assign", verify: "Verify", runNightly: "Run nightly monitoring",
  delayPattern: "Rough historical pattern — not a prediction for this case",
  status_CRITICAL_ACQUITTED_DETAINED: "Critical: acquitted but detained",
  status_CRITICAL_MUST_RELEASE: "Critical: beyond maximum",
  status_URGENT_DEFAULT_BAIL: "Urgent: default bail",
  status_CRITICAL_BAIL_NOT_FURNISHED: "Critical: bail not furnished",
  status_DEFAULT_BAIL_WINDOW_SOON: "Default bail soon",
  status_DEFAULT_BAIL_RIGHT_ASSERTED: "Default bail applied",
  status_ELIGIBLE: "Eligible (479)", status_REVIEW_MULTIPLE_CASES: "Review: multiple cases", status_REVIEW: "Review",
  status_NOT_YET: "Not yet", status_EXCLUDED_479: "Excluded (death/life)", status_NOT_APPLICABLE: "Not applicable",
};
type Dict = typeof en;

const kn: Partial<Dict> = {
  app: "ನ್ಯಾಯಸೇತು",
  tagline: "ನ್ಯಾಯದ ಸೇತುವೆ — ವಿಚಾರಣಾಧೀನ ಕೈದಿಗಳ ನಿರ್ಧಾರ ಸಹಾಯ",
  disclaimer: "ಅರ್ಹ ವಕೀಲರಿಗೆ ನಿರ್ಧಾರ ಸಹಾಯ ಮಾತ್ರ. ಕಾನೂನು ಸಲಹೆ ಅಲ್ಲ. ಎಲ್ಲಾ ಕಲಂಗಳು ಮತ್ತು ಉಲ್ಲೇಖಗಳನ್ನು ಪರಿಶೀಲಿಸಿ.",
  signIn: "ಲಾಗಿನ್", email: "ಇಮೇಲ್", password: "ಪಾಸ್‌ವರ್ಡ್", signOut: "ಲಾಗ್ ಔಟ್",
  myPrisoners: "ನನ್ನ ಕೈದಿಗಳು", prisoners: "ಕೈದಿಗಳು", alerts: "ಎಚ್ಚರಿಕೆಗಳು", review: "ಪರಿಶೀಲನಾ ಸರದಿ", district: "ಜಿಲ್ಲೆ",
  admin: "ನಿರ್ವಾಹಕ", legalData: "ಕಾನೂನು ದತ್ತಾಂಶ", audit: "ಲೆಕ್ಕಪರಿಶೋಧನೆ ದಾಖಲೆ",
  search: "ಹೆಸರಿನಿಂದ ಹುಡುಕಿ", status: "ಸ್ಥಿತಿ", custody: "ಬಂಧನ", days: "ದಿನಗಳು", overdue: "ಮೀರಿದೆ",
  eligibleFrom: "ಅರ್ಹತೆ ದಿನಾಂಕ", projected: "ನಿರೀಕ್ಷಿತ", priority: "ಆದ್ಯತೆ", charges: "ಆರೋಪಗಳು", jail: "ಕಾರಾಗೃಹ",
  overview: "ಅರ್ಹತೆ", timeline: "ಕಾಲರೇಖೆ", facts: "ಸಂಗತಿಗಳು ಮತ್ತು ದಾಖಲೆಗಳು", insights: "ರಕ್ಷಣಾ ಒಳನೋಟಗಳು", drafts: "ಕರಡುಗಳು",
  trace: "ಇದನ್ನು ಹೇಗೆ ನಿರ್ಧರಿಸಲಾಯಿತು", needsVerification: "ಪರಿಶೀಲನೆ ಅಗತ್ಯ", flags: "ಗಮನಿಸಬೇಕಾದವು",
  findings: "ಇತರ ಮಾರ್ಗಗಳು ಮತ್ತು ಎಚ್ಚರಿಕೆಗಳು", interpretations: "ವ್ಯಾಖ್ಯಾನಗಳು", countedDetention: "ಎಣಿಸಿದ ಬಂಧನ",
  threshold: "ಮಿತಿ", maximum: "ಗರಿಷ್ಠ", firstTime: "ಮೊದಲ ಬಾರಿ ಅಪರಾಧಿ", recompute: "ಮರುಲೆಕ್ಕ", upload: "ದಾಖಲೆ ಅಪ್‌ಲೋಡ್",
  uploading: "ಅಪ್‌ಲೋಡ್ ಆಗುತ್ತಿದೆ…", accept: "ಒಪ್ಪಿ", reject: "ತಿರಸ್ಕರಿಸಿ", confirm: "ದೃಢೀಕರಿಸಿ", correct: "ಸರಿಪಡಿಸಿ",
  evidence: "ದಾಖಲೆಯಲ್ಲಿನ ಸಾಕ್ಷ್ಯ", nextSteps: "ಮುಂದೇನು ಮಾಡಬೇಕು", similarJudgments: "ಹೋಲುವ ತೀರ್ಪುಗಳು (ಹುಡುಕಿದವು, ರಚಿಸಿದವಲ್ಲ)",
  newDraft: "ಹೊಸ ಕರಡು", language: "ಭಾಷೆ", create: "ರಚಿಸಿ", exportDocx: "DOCX ರಫ್ತು", exportPdf: "PDF ರಫ್ತು",
  approve: "ಅನುಮೋದಿಸಿ", save: "ತಿದ್ದುಪಡಿ ಉಳಿಸಿ", acknowledge: "ಸ್ವೀಕರಿಸಿ", noItems: "ಇಲ್ಲಿ ಏನೂ ಇಲ್ಲ.", loading: "ಲೋಡ್ ಆಗುತ್ತಿದೆ…",
  eligibleApply: "ಅರ್ಜಿ ಸಲ್ಲಿಸಲು ಅರ್ಹ — ದಾಖಲಿಸಿದ ಕಾರಣಗಳಿಗಾಗಿ ನ್ಯಾಯಾಲಯ ಬಂಧನ ಮುಂದುವರಿಸಬಹುದು.",
  needsLegalVerification: "ಕಾನೂನು ಪರಿಶೀಲನೆ ಅಗತ್ಯ", superintendentApp: "ಅಧೀಕ್ಷಕರ ಅರ್ಜಿ ಸಿದ್ಧಪಡಿಸಿ",
  heatmap: "ಜಿಲ್ಲಾವಾರು ಅವಧಿ ಮೀರಿದ ವಿಚಾರಣಾಧೀನರು", workload: "ವಕೀಲರ ಕೆಲಸದ ಹೊರೆ", vulnerable: "ದುರ್ಬಲ",
  avgDetention: "ಸರಾಸರಿ ಬಂಧನ (ದಿನ)", assign: "ನಿಯೋಜಿಸಿ", verify: "ಪರಿಶೀಲಿಸಿ",
  delayPattern: "ಹಿಂದಿನ ಪ್ರಕರಣಗಳ ಸ್ಥೂಲ ಮಾದರಿ — ಈ ಪ್ರಕರಣದ ಮುನ್ಸೂಚನೆ ಅಲ್ಲ",
  status_CRITICAL_ACQUITTED_DETAINED: "ತುರ್ತು: ಖುಲಾಸೆಯಾದರೂ ಬಂಧನ", status_CRITICAL_MUST_RELEASE: "ತುರ್ತು: ಗರಿಷ್ಠ ಮೀರಿದೆ",
  status_URGENT_DEFAULT_BAIL: "ತುರ್ತು: ಡಿಫಾಲ್ಟ್ ಜಾಮೀನು", status_CRITICAL_BAIL_NOT_FURNISHED: "ತುರ್ತು: ಜಾಮೀನುದಾರರಿಲ್ಲ",
  status_ELIGIBLE: "ಅರ್ಹ (479)", status_REVIEW_MULTIPLE_CASES: "ಪರಿಶೀಲನೆ: ಬಹು ಪ್ರಕರಣಗಳು", status_REVIEW: "ಪರಿಶೀಲನೆ",
  status_NOT_YET: "ಇನ್ನೂ ಇಲ್ಲ", status_EXCLUDED_479: "ಹೊರಗಿಡಲಾಗಿದೆ (ಮರಣ/ಜೀವಾವಧಿ)", status_NOT_APPLICABLE: "ಅನ್ವಯಿಸುವುದಿಲ್ಲ",
};

// Hindi is scaffolded: untranslated keys fall back to English.
const hi: Partial<Dict> = {
  app: "न्यायसेतु", signIn: "साइन इन", signOut: "साइन आउट", myPrisoners: "मेरे बंदी", alerts: "अलर्ट",
  disclaimer: "योग्य वकील के लिए निर्णय सहायता। कानूनी सलाह नहीं। सभी धाराएँ और उद्धरण सत्यापित करें।",
};

const dicts: Record<Lang, Partial<Dict>> = { en, kn, hi };
export type Key = keyof Dict;

const Ctx = createContext<{ lang: Lang; setLang: (l: Lang) => void; t: (k: Key) => string; ts: (status: string) => string }>({
  lang: "en", setLang: () => {}, t: (k) => en[k], ts: (s) => s,
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const saved = useLocal("nyaya_lang");
  const lang: Lang = saved && saved in dicts ? (saved as Lang) : "en";
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const setLang = (l: Lang) => writeLocal("nyaya_lang", l);
  const t = (k: Key) => (dicts[lang][k] as string) ?? en[k];
  const ts = (s: string) => ((dicts[lang] as Record<string, string>)[`status_${s}`] ?? (en as Record<string, string>)[`status_${s}`] ?? s.replaceAll("_", " "));
  return <Ctx.Provider value={{ lang, setLang, t, ts }}>{children}</Ctx.Provider>;
}

export const useI18n = () => useContext(Ctx);
