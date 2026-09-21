import { beforeEach, describe, expect, it } from "vitest";
import { browserDraftKey, clearBrowserDraft, restoreBrowserDraft } from "./browserDraft";

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

});
