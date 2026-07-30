import { afterEach, describe, expect, it, vi } from "vitest";
import { projectFromLocation, StoryApi } from "./client";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

describe("StoryApi project negotiation", () => {
  it("adopts the server default project when the URL omits project", async () => {
    window.history.replaceState({}, "", "/");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      apiVersion: 1,
      schemaVersion: 3,
      writable: true,
      project: "fuchouji",
      projectRevision: 6,
      features: [],
      mutationToken: "token",
      error: "",
      routes: {},
    }), { status: 200, headers: { "content-type": "application/json" } })));

    const api = new StoryApi(projectFromLocation());
    const meta = await api.meta();

    expect(meta.project).toBe("fuchouji");
    expect(api.project).toBe("fuchouji");
  });

  it("does not silently accept a static HTML fallback as API metadata", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<!doctype html>", {
      status: 200,
      headers: { "content-type": "text/html" },
    })));
    await expect(new StoryApi("").meta()).rejects.toThrow("没有可用的本地 Story Teller API");
  });

  it("refreshes the write token after a local service restart", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        apiVersion: 1,
        schemaVersion: 3,
        writable: true,
        project: "demo",
        projectRevision: 6,
        features: [],
        mutationToken: "old-token",
        error: "",
        routes: {},
      }), { status: 200, headers: { "content-type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        detail: "写入授权已失效，请刷新本地服务能力",
      }), { status: 403, headers: { "content-type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        apiVersion: 1,
        schemaVersion: 3,
        writable: true,
        project: "demo",
        projectRevision: 6,
        features: [],
        mutationToken: "new-token",
        error: "",
        routes: {},
      }), { status: 200, headers: { "content-type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        projectRevision: 7,
        changed: {},
        deleted: [],
        warnings: [],
      }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    const api = new StoryApi("demo");
    await api.meta();

    await api.mutate("/characters/character%3A1", "PATCH", { baseRevision: 6 });

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect((fetchMock.mock.calls[3][1] as RequestInit).headers).toMatchObject({
      "X-Story-Teller-Token": "new-token",
    });
  });

  it("refreshes the write token while saving a merge decision", async () => {
    const emptyMerge = { required: false, session: null, items: [] };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        apiVersion: 1,
        schemaVersion: 4,
        writable: true,
        contentWritable: false,
        mergeRequired: true,
        project: "demo",
        projectRevision: 6,
        features: ["git-database-merge-v1"],
        mutationToken: "old-token",
        error: "",
        routes: { mergeConflicts: true },
      }), { status: 200, headers: { "content-type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        detail: "写入授权已失效，请刷新本地服务能力",
      }), { status: 403, headers: { "content-type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        apiVersion: 1,
        schemaVersion: 4,
        writable: true,
        contentWritable: false,
        mergeRequired: true,
        project: "demo",
        projectRevision: 6,
        features: ["git-database-merge-v1"],
        mutationToken: "new-token",
        error: "",
        routes: { mergeConflicts: true },
      }), { status: 200, headers: { "content-type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(emptyMerge), {
        status: 200,
        headers: { "content-type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);
    const api = new StoryApi("demo");
    await api.meta();

    await api.resolveMergeConflict("conflict-1", {
      summary: { choice: "theirs" },
    });

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect((fetchMock.mock.calls[3][1] as RequestInit).headers).toMatchObject({
      "X-Story-Teller-Token": "new-token",
    });
  });

  it("polls until the restarted local service becomes writable", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        apiVersion: 1,
        schemaVersion: 3,
        writable: true,
        project: "demo",
        projectRevision: 6,
        features: [],
        mutationToken: "recovered-token",
        error: "",
        routes: {},
      }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    const api = new StoryApi("demo");

    const recovered = api.waitForRecovery(10);
    await vi.advanceTimersByTimeAsync(10);
    await recovered;

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
