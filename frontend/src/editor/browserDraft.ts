import { useEffect } from "react";

interface StoredBrowserDraft<T> {
  version: 1;
  updatedAt: number;
  value: T;
}

const PREFIX = "story-teller:browser-draft";

export function browserDraftKey(project: string, kind: string, entityId: string): string {
  const workspace = window.location.pathname.match(/^\/w\/([^/]+)(?:\/|$)/)?.[1] || "direct";
  return `${PREFIX}:${workspace}:${encodeURIComponent(project)}:${kind}:${encodeURIComponent(entityId)}`;
}

export function restoreBrowserDraft<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    const stored = JSON.parse(raw) as StoredBrowserDraft<T>;
    return stored?.version === 1 && stored.value !== undefined ? stored.value : fallback;
  } catch {
    return fallback;
  }
}

export function clearBrowserDraft(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // The editor remains usable when browser storage is unavailable.
  }
}

export function useBrowserDraft<T>(key: string, draft: T, baseline: string): void {
  useEffect(() => {
    if (!baseline) return;
    if (JSON.stringify(draft) === baseline) {
      clearBrowserDraft(key);
      return;
    }
    try {
      const stored: StoredBrowserDraft<T> = {
        version: 1,
        updatedAt: Date.now(),
        value: draft,
      };
      window.localStorage.setItem(key, JSON.stringify(stored));
    } catch {
      // Saving to SQLite still works if localStorage is disabled or full.
    }
  }, [baseline, draft, key]);
}
