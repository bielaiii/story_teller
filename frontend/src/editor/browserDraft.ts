import { useEffect, useRef, useState } from "react";
import { changedFields } from "../api/partialUpdate";
import type { MutationDelta } from "../api/types";

interface StoredBrowserDraft<T> {
  version: 1 | 2;
  entityRevision?: number | null;
  baseline?: T | null;
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
    return (stored?.version === 1 || stored?.version === 2) && stored.value !== undefined ? stored.value : fallback;
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

/** A recovered draft retains the version it was actually edited against. */
export function useBrowserDraftSession<T>(key: string, draft: T, baseline: string, generation = 0) {
  const [session, setSession] = useState<{
    key: string; generation: number; revision: number | null; baseline: T | null; latest: T;
    latestRevision: number | null; conflict: boolean;
  } | null>(null);
  const [storageError, setStorageError] = useState(false);
  const [persistedValue, setPersistedValue] = useState("");
  const active = useRef(session);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const update = (next: NonNullable<typeof session>) => {
    active.current = next;
    setSession(next);
  };
  const restore = (fallback: T, revision: number | null): T => {
    // Background detail refreshes must never replace an active editor.
    if (active.current?.key === key && active.current.generation === generation) {
      const current = active.current;
      if (revision !== null && (current.latestRevision === null || revision > current.latestRevision)) {
        update({ ...current, latest: fallback, latestRevision: revision,
          baseline: current.revision === revision ? fallback : current.baseline,
          conflict: current.revision !== revision });
      }
      return draftRef.current;
    }
    let stored: StoredBrowserDraft<T> | null = null;
    try {
      const raw = window.localStorage.getItem(key);
      if (raw) stored = JSON.parse(raw);
      if (!stored || ![1, 2].includes(stored.version) || stored.value === undefined) stored = null;
    } catch { setStorageError(true); }
    const known = stored?.version === 2 && stored.baseline != null
      && (stored.entityRevision === null || (Number.isInteger(stored.entityRevision) && Number(stored.entityRevision) >= 0));
    const conflict = Boolean(stored && revision !== null && (!known || stored.entityRevision !== revision));
    update({ key, generation, revision: stored ? (known ? stored.entityRevision! : null) : revision,
      baseline: stored ? (known ? stored.baseline! : null) : fallback,
      latest: fallback, latestRevision: revision, conflict });
    draftRef.current = stored ? stored.value : fallback;
    return draftRef.current;
  };
  useEffect(() => {
    if (!session || session.key !== key || session.generation !== generation || !baseline) return;
    try {
      if (!session.conflict && JSON.stringify(draft) === baseline) {
        window.localStorage.removeItem(key);
      } else {
        window.localStorage.setItem(key, JSON.stringify({
          version: 2, updatedAt: Date.now(), value: draft,
          entityRevision: session.revision, baseline: session.baseline,
        }));
      }
      setPersistedValue(JSON.stringify(draft));
      setStorageError(false);
    } catch { setStorageError(true); }
  }, [key, draft, baseline, session, generation]);
  return {
    restore,
    storageError,
    statusText: storageError ? "草稿暂存失败，请保留当前页面"
      : persistedValue === JSON.stringify(draft) ? "未保存修改已暂存在浏览器" : "正在暂存修改…",
    conflict: session?.key === key && session.generation === generation && session.conflict ? session : null,
    revisionPayload(): { entityRevision?: number } {
      const current = active.current;
      if (!current || current.key !== key || current.generation !== generation) throw new Error("正在读取编辑基线，请稍后保存");
      if (current.conflict) throw new Error("草稿基于旧版本，请先对比并确认恢复内容");
      return current.revision === null ? {} : { entityRevision: current.revision };
    },
    changedPayload(payload: Record<string, unknown>, transform: (value: T) => Record<string, unknown> = value => value as Record<string, unknown>) {
      const current = active.current;
      if (!current || current.revision === null || current.baseline === null) return payload;
      return changedFields(payload, transform(current.baseline));
    },
    acceptLatest() {
      const current = active.current;
      if (current) update({ ...current, revision: current.latestRevision, baseline: current.latest, conflict: false });
    },
    saved(delta: MutationDelta, entityId: string) {
      const current = active.current;
      if (!current || current.key !== key || current.generation !== generation) return;
      const changed = Object.values(delta.changed).flat().find(item => item?.entityId === entityId);
      const revision = typeof changed?.revision === "number" ? changed.revision : current.revision;
      update({ ...current, revision, latestRevision: revision,
        baseline: draftRef.current, latest: draftRef.current, conflict: false });
    },
  };
}
