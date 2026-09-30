"use client";

import type { ReactNode } from "react";
import { DialogProvider } from "@/components/Dialog";
import { AuthProvider } from "@/lib/auth";
import { I18nProvider } from "@/lib/i18n";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <I18nProvider>
      <AuthProvider><DialogProvider>{children}</DialogProvider></AuthProvider>
    </I18nProvider>
  );
}
