import { useSyncExternalStore } from "react";

/** A localStorage-backed value readable during render (hydration-safe via server snapshot). */
const listeners = new Set<() => void>();

function subscribe(cb: () => void) {
  listeners.add(cb);
  const onStorage = () => cb();
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", onStorage);
  };
}

export function readLocal(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeLocal(key: string, value: string | null) {
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {}
  listeners.forEach((l) => l());
}

/** Returns undefined on the server / before hydration, then the stored string (or null). */
export function useLocal(key: string): string | null | undefined {
  return useSyncExternalStore(subscribe, () => readLocal(key), () => undefined);
}
