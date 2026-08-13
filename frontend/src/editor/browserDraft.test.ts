import { beforeEach, describe, expect, it } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { browserDraftKey, clearBrowserDraft, restoreBrowserDraft, useBrowserDraft } from "./browserDraft";

describe("browser drafts", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState({}, "", "/");
  });

  it("separates same-named projects in different content workspaces", () => {
    window.history.replaceState({}, "", "/w/workspace-alpha/?project=demo");
    const alpha = browserDraftKey("demo", "plot", "plot:1");
    window.history.replaceState({}, "", "/w/workspace-beta/?project=demo");
    const beta = browserDraftKey("demo", "plot", "plot:1");
    expect(alpha).not.toBe(beta);
  });

  it("restores a saved editor value", () => {
    const key = browserDraftKey("demo", "character", "new");
    window.localStorage.setItem(key, JSON.stringify({
      version: 1,
      updatedAt: 1,
      value: { name: "浏览器里的名字" },
    }));

    expect(restoreBrowserDraft(key, { name: "" })).toEqual({ name: "浏览器里的名字" });
  });

  it("ignores malformed storage and clears drafts explicitly", () => {
    const key = browserDraftKey("demo", "plot", "plot:1");
    window.localStorage.setItem(key, "{");
    expect(restoreBrowserDraft(key, { body: "服务器正文" })).toEqual({ body: "服务器正文" });

    clearBrowserDraft(key);
    expect(window.localStorage.getItem(key)).toBeNull();
  });

  it("keeps dirty values and removes them after the saved baseline catches up", async () => {
    const key = browserDraftKey("demo", "entry", "entry:1");
    const { rerender } = renderHook(
      ({ draft, baseline }) => useBrowserDraft(key, draft, baseline),
      {
        initialProps: {
          draft: { body: "浏览器草稿" },
          baseline: JSON.stringify({ body: "服务器正文" }),
        },
      },
    );
    await waitFor(() => expect(restoreBrowserDraft(key, { body: "" })).toEqual({ body: "浏览器草稿" }));

    rerender({
      draft: { body: "浏览器草稿" },
      baseline: JSON.stringify({ body: "浏览器草稿" }),
    });
    await waitFor(() => expect(window.localStorage.getItem(key)).toBeNull());
  });
});
