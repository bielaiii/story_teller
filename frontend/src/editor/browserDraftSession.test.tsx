import { StrictMode, useEffect, useState } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useBrowserDraftSession } from "./browserDraft";

const key = "draft-test";
function useEditor(revision = 4) {
  const [draft, setDraft] = useState({ body: "" });
  const [baseline, setBaseline] = useState("");
  const session = useBrowserDraftSession(key, draft, baseline);
  useEffect(() => {
    const latest = { body: "latest" };
    setDraft(session.restore(latest, revision));
    setBaseline(JSON.stringify(latest));
  }, [revision]);
  return { session, draft, setDraft, setBaseline };
}
beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());
it("keeps the real baseline across recovery, StrictMode and repeated reloads", async () => {
  localStorage.setItem(key, JSON.stringify({ version: 2, value: { body: "old draft" }, baseline: { body: "original" }, entityRevision: 2 }));
  const first = renderHook(() => useEditor(), { wrapper: StrictMode });
  expect(first.result.current.draft.body).toBe("old draft");
  expect(first.result.current.session.conflict?.baseline?.body).toBe("original");
  expect(() => first.result.current.session.revisionPayload()).toThrow("对比");
  await waitFor(() => expect(JSON.parse(localStorage.getItem(key)!).entityRevision).toBe(2));
  first.unmount();
  const second = renderHook(() => useEditor());
  expect(second.result.current.session.conflict).toBeTruthy();
  act(() => second.result.current.session.acceptLatest());
  expect(second.result.current.session.revisionPayload()).toEqual({ entityRevision: 4 });
});
it("requires comparison for legacy drafts even after they are persisted again", () => {
  localStorage.setItem(key, JSON.stringify({ version: 1, value: { body: "legacy" } }));
  const first = renderHook(() => useEditor());
  expect(first.result.current.session.conflict).toBeTruthy();
  first.unmount();
  const second = renderHook(() => useEditor());
  expect(second.result.current.session.conflict).toBeTruthy();
  expect(second.result.current.draft.body).toBe("legacy");
});
it("keeps active edits and advances the baseline only after a successful save", () => {
  const { result, rerender } = renderHook(({ revision }) => useEditor(revision), { initialProps: { revision: 4 } });
  act(() => result.current.setDraft({ body: "editing" }));
  rerender({ revision: 5 });
  expect(result.current.draft.body).toBe("editing");
  expect(() => result.current.session.revisionPayload()).toThrow("对比");
  expect(result.current.session.conflict?.latestRevision).toBe(5);
  act(() => result.current.session.acceptLatest());
  expect(result.current.session.revisionPayload()).toEqual({ entityRevision: 5 });
  act(() => {
    result.current.session.saved({ changed: { plots: [{ entityId: "plot:1", revision: 8 }] } } as never, "plot:1");
    result.current.setBaseline(JSON.stringify({ body: "editing" }));
  });
  expect(result.current.session.revisionPayload()).toEqual({ entityRevision: 8 });
  expect(localStorage.getItem(key)).toBeNull();
  rerender({ revision: 6 });
  expect(result.current.session.conflict).toBeNull();
  expect(result.current.session.revisionPayload()).toEqual({ entityRevision: 8 });
});
it("reports failed persistence without losing the active draft", () => {
  vi.spyOn(window.localStorage, "setItem").mockImplementation(() => { throw new Error("quota"); });
  const { result } = renderHook(() => useEditor());
  act(() => result.current.setDraft({ body: "not on disk" }));
  expect(result.current.session.storageError).toBe(true);
  expect(result.current.draft.body).toBe("not on disk");
});
