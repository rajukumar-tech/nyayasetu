"use client";

import { createContext, useContext, type ReactNode } from "react";
import { api, clearSession, type User } from "./api";
import { useLocal, writeLocal } from "./store";

type SessionUser = User & { session_audit_id?: number | null };

const Ctx = createContext<{ user: SessionUser | null; ready: boolean; login: (e: string, p: string) => Promise<User>; logout: () => Promise<void> }>({
  user: null, ready: false, login: async () => { throw new Error("no provider"); }, logout: async () => {},
});

export function homeFor(role: User["role"]): string {
  return { legal_aid_lawyer: "/lawyer", jail_staff: "/jail", dlsa_admin: "/dlsa", reviewer: "/reviewer", system_admin: "/admin" }[role];
}

function parse(raw: string | null | undefined): SessionUser | null {
  if (!raw) return null;
  try { return JSON.parse(raw) as SessionUser; } catch { return null; }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const rawUser = useLocal("nyaya_user");
  const token = useLocal("nyaya_token");
  const ready = rawUser !== undefined;
  const user = token ? parse(rawUser) : null;
  const login = async (email: string, password: string) => {
    const r = await api<{ access_token: string; user: SessionUser }>("/api/auth/login", {
      method: "POST", body: JSON.stringify({ email, password }),
    });
    writeLocal("nyaya_token", r.access_token);
    writeLocal("nyaya_user", JSON.stringify(r.user));
    return r.user;
  };
  const logout = async () => {
    // the server revokes this token, so it cannot be reused even if it was copied somewhere
    try { await api("/api/auth/logout", { method: "POST" }); } catch {}
    clearSession(null);
  };
  return <Ctx.Provider value={{ user, ready, login, logout }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
