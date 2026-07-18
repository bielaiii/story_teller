import { afterEach, describe, expect, it, vi } from "vitest";
import { projectFromLocation, StoryApi } from "./client";

afterEach(() => {
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
});
