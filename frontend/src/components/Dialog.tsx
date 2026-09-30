"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useI18n } from "@/lib/i18n";

/** In-app replacement for window.prompt / window.confirm, which many browsers (and embedded views) block.
 *  const dialog = useDialog();
 *  const pw = await dialog.ask({ title, label, type: "password", minLength: 10 });   // string | null
 *  if (await dialog.confirm({ title, message, danger: true })) { ... }               // boolean */
interface AskOptions {
  title: string;
  label?: string;
  message?: string;
  initial?: string;
  type?: "text" | "password";
  minLength?: number;
  confirmText?: string;
  danger?: boolean;
}
interface ConfirmOptions { title: string; message: string; confirmText?: string; danger?: boolean }
type Pending = (AskOptions & { mode: "ask" | "confirm"; resolve: (v: string | null) => void }) | null;

const Ctx = createContext<{ ask: (o: AskOptions) => Promise<string | null>; confirm: (o: ConfirmOptions) => Promise<boolean> }>({
  ask: async () => null, confirm: async () => false,
});

export function DialogProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending>(null);
  const ask = useCallback((o: AskOptions) => new Promise<string | null>((resolve) => setPending({ ...o, mode: "ask", resolve })), []);
  const confirm = useCallback((o: ConfirmOptions) => new Promise<boolean>((resolve) =>
    setPending({ ...o, mode: "confirm", resolve: (v) => resolve(v !== null) })), []);
  const close = (v: string | null) => { pending?.resolve(v); setPending(null); };
  return (
    <Ctx.Provider value={{ ask, confirm }}>
      {children}
      {pending && <DialogView p={pending} onClose={close} />}
    </Ctx.Provider>
  );
}

function DialogView({ p, onClose }: { p: NonNullable<Pending>; onClose: (v: string | null) => void }) {
  const { t } = useI18n();
  const [value, setValue] = useState(p.initial ?? "");
  const [show, setShow] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const tooShort = p.mode === "ask" && (value.trim().length < (p.minLength ?? 1));
  useEffect(() => {
    input.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(null); }}>
      <form role="dialog" aria-modal="true" aria-labelledby="dlg-title" className="card w-full max-w-md p-5 space-y-3 shadow-lg"
        onSubmit={(e) => { e.preventDefault(); if (!tooShort) onClose(p.mode === "ask" ? value : ""); }}>
        <h2 id="dlg-title" className="text-lg font-semibold">{p.title}</h2>
        {p.message && <p className="text-sm text-muted">{p.message}</p>}
        {p.mode === "ask" && (
          <label className="block text-sm">
            {p.label && <span className="label block mb-1">{p.label}</span>}
            <span className="relative block">
              <input ref={input} type={p.type === "password" && !show ? "password" : "text"} value={value}
                autoComplete={p.type === "password" ? "new-password" : "off"} onChange={(e) => setValue(e.target.value)}
                className={`w-full border rounded-md px-3 py-2 bg-surface ${p.type === "password" ? "pr-24" : ""} ${tooShort && value ? "border-critical" : "border-line"}`} />
              {p.type === "password" && (
                <button type="button" onClick={() => setShow((s) => !s)} className="absolute inset-y-0 right-0 px-3 text-xs text-navy-2 underline-offset-2 hover:underline">
                  {show ? t("hidePassword") : t("showPassword")}
                </button>
              )}
            </span>
            {(p.minLength ?? 1) > 1 && <span className={`block text-xs mt-1 ${tooShort && value ? "text-critical" : "text-muted"}`}>{t("minChars", { n: p.minLength })}</span>}
          </label>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className="btn btn-ghost" onClick={() => onClose(null)}>{t("cancel")}</button>
          <button className={`btn ${p.danger ? "btn-danger" : "btn-primary"}`} disabled={tooShort}>{p.confirmText ?? t("confirm")}</button>
        </div>
      </form>
    </div>
  );
}

export const useDialog = () => useContext(Ctx);
