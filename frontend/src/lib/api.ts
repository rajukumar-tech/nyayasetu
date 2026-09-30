import { writeLocal } from "./store";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** status 0 = network failure. The message is the server's text; pages show a localised message via apiErrorText. */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem("nyaya_token");
  } catch {
    return null;
  }
}

export function clearSession(noticeKey: string | null) {
  writeLocal("nyaya_notice", noticeKey);
  writeLocal("nyaya_token", null);
  writeLocal("nyaya_user", null);
  writeLocal("nyaya_session_start", null);
}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "network");
  }
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/auth/login")) {
    // session expired / signed out / account deactivated: clearing the session makes <Shell> route to /login
    clearSession("sessionExpired");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail
        : Array.isArray(body.detail) ? body.detail.map((d: { loc?: string[]; msg?: string }) => `${(d.loc ?? []).slice(-1)[0] ?? ""}: ${d.msg ?? ""}`).join("; ")
        : JSON.stringify(body.detail);
    } catch {}
    throw new ApiError(res.status, msg);
  }
  const ct = res.headers.get("content-type") ?? "";
  return (ct.includes("application/json") ? res.json() : res.blob()) as Promise<T>;
}

export async function download(path: string, filename: string) {
  const blob = await api<Blob>(path);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.style.display = "none";
  // the link must be in the page for some browsers, and the blob URL must outlive the click: revoking it in the same
  // tick cancels the download in Chrome
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

// ---------- types (subset of the API) ----------
export type Role = "legal_aid_lawyer" | "jail_staff" | "dlsa_admin" | "reviewer" | "system_admin";
export interface User { id: string; email: string; name: string; role: Role; jail?: string; district?: string }

export interface PersonRow {
  id: string; name: string; relative?: string; relation?: string; gender?: string; jail?: string; district?: string;
  vulnerability: string[]; status: string | null; urgency: string; eligible_from_date?: string | null;
  days_overdue?: number | null; custody_days: number; needs_verification: number;
  cases: { id: string; cnr?: string; status: string; charges: string[] }[];
  priority?: number; delay_pattern?: { p_pending_3y: number | null; label: string }; assigned_lawyer_id?: string | null;
  demo_label?: string | null; as_of?: string | null; intake?: "pending_review" | "verified" | "returned";
}

export interface TraceStep { rule: string; text: string; refs: string[] }
export interface Flag { code: string; message: string; severity: string }
export interface Finding { code: string; message: string; severity: string; date?: string | null; refs: string[] }
export interface Interval { start: string; end: string; kind: string; explanation: string; jails: string[] }
export interface CaseResult {
  case_id: string; status: string; urgency?: string; eligible_from_date?: string | null; projected_date?: string | null;
  days_overdue?: number | null; custody_days: number; accused_days: number; counted_days: number;
  threshold_days?: number | null; max_days?: number | null; max_term?: string | null; fraction?: string | null;
  first_time_offender?: boolean | null; trace: TraceStep[]; flags: Flag[]; needs_verification: string[];
  charge_calcs: { charge: string; max_term: string; max_days: number | null; threshold_days: number | null;
    eligible_from: string | null; is_death_or_life: boolean; special_law: boolean; unverified: string[] }[];
  interpretations: Record<string, Record<string, string | null>>; findings: Finding[];
  timeline?: { intervals: Interval[]; excluded: Interval[]; gaps: [string, string][]; lenient_custody_days: number | null;
    arrest: { chosen: string | null; conflict: boolean } };
}

export interface Fact {
  id: string; document_id: string; case_id?: string; field: string; value: unknown; original_value: unknown; page: number;
  span_start: number; span_end: number; span_text: string; method: string; confidence: number; review_status: string;
  notes: string[];
}

export interface PersonDetail extends PersonRow {
  dob?: string; name_variants: string[]; can_see_insights: boolean; can_draft: boolean; assigned_lawyer?: string | null;
  eligibility: { overall_status: string; cases: CaseResult[]; disclaimer: string; rule_version: string;
    legal_data_version: string; computed_at: string; as_of?: string };
  rule_version: string; legal_data_version: string; computed_at: string;
  case_details: {
    id: string; cnr?: string; case_numbers: string[]; court?: string; status: string; fir_number?: string;
    police_station?: string; offence_date?: string; first_remand_date?: string; charge_sheet_date?: string;
    bail_granted_date?: string; default_bail_application_date?: string;
    charges: { act: string; section: string; modifier?: string; confidence: number;
      record?: { key: string; title: string; max: string | null; verified: boolean; verified_by?: string; source: string;
        compoundable?: string; special_law: boolean } | null }[];
    hearings: { id: string; date: string; next_date?: string; reason: string; attribution: string; confidence: number;
      method?: string; verified: boolean }[];
  }[];
  custody_events: { id: string; type: string; start: string; end?: string; case_id?: string; jail?: string;
    confidence: number; primary: boolean }[];
  convictions: { case_id: string; date: string; status: string; offence: string }[];
  documents: { id: string; filename: string; doc_type: string; language?: string; status: string; warnings: string[];
    case_id?: string }[];
  facts: Fact[];
}

export interface Insight {
  id: string; case_id: string; code: string; category: string; severity: string; title: string; explanation: string;
  next_steps: string; rank_score: number; status: string; legal_basis: string[];
  evidence: { fact_id: string; document_id: string; doc_type: string; page: number; start: number; end: number; text: string;
    field: string }[];
  judgments: { id: string; citation: string; court: string; date: string; url: string; passage: string; synthetic: boolean }[];
}

export interface Draft {
  id: string; case_id: string; type: string; language: string; content: string; status: string; created_at: string;
  grounding: { id: string; text: string; status: string; problems: string[];
    sources: { type: string; ref: string; values: string[] }[] }[];
  verifier_report: { sentences: number; rejected: number; fully_grounded_pct: number; problems: string[]; notes: string[];
    disclaimer: string; title: string; lawyer_edited?: boolean };
  versions: { at: string; by: string; content: string }[];
}
