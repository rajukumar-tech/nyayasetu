"use client";

import { createContext, useContext, type ReactNode } from "react";
import { api, type User } from "./api";
import { useLocal, writeLocal } from "./store";

const Ctx = createContext<{ user: User | null; ready: boolean; login: (e: string, p: string) => Promise<User>; logout: () => void }>({
  user: null, ready: false, login: async () => { throw new Error("no provider"); }, logout: () => {},
});

export function homeFor(role: User["role"]): string {
  return { legal_aid_lawyer: "/lawyer", jail_staff: "/jail", dlsa_admin: "/dlsa", reviewer: "/reviewer", system_admin: "/admin" }[role];
}

function parse(raw: string | null | undefined): User | null {
  if (!raw) return null;
  try { return JSON.parse(raw) as User; } catch { return null; }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const rawUser = useLocal("nyaya_user");
  const token = useLocal("nyaya_token");
  const ready = rawUser !== undefined;
  const user = token ? parse(rawUser) : null;
  const login = async (email: string, password: string) => {
    const r = await api<{ access_token: string; user: User }>("/api/auth/login", {
      method: "POST", body: JSON.stringify({ email, password }),
    });
    writeLocal("nyaya_token", r.access_token);
    writeLocal("nyaya_user", JSON.stringify(r.user));
    return r.user;
  };
  const logout = () => {
    writeLocal("nyaya_token", null);
    writeLocal("nyaya_user", null);
  };
  return <Ctx.Provider value={{ user, ready, login, logout }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
