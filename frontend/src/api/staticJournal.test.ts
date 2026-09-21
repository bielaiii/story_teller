import { afterEach, expect, it, vi } from "vitest";
import { loadStaticSnapshot } from "./client";
const basePath = `export-data/${"a".repeat(64)}.json`;
const patchPath = `export-data/${"b".repeat(64)}.json`;
const base = { project: { id: "demo", revision: 1 }, readonly: true, plots: [{ entityId: "plot:1", body: "original", stories: ["legacy"] }],
  characters: [], entries: [], fragments: [], relationships: [], chapters: [], timeline: {}, graph: {} };
const manifest = { format: "story-teller-export-journal", version: 1, kind: "static", project: { id: "demo", revision: 2 }, base: basePath, patches: [patchPath] };
const patch = { fromRevision: 1, project: "demo", static: { summary: { ...base, project: manifest.project,
  plots: [{ entityId: "plot:1", stories: [] }] }, details: { "plot:1": { body: "saved" } }, overrides: {} } };
function mock(entries: unknown[]) {
  const fetch = vi.fn();
  for (const entry of entries) fetch.mockResolvedValueOnce(new Response(JSON.stringify(entry), { headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
afterEach(() => vi.unstubAllGlobals());
it("reconstructs the current readonly document without replacing unchanged detail fields", async () => {
  const fetch = mock([manifest, base, patch]);
  const result = await loadStaticSnapshot();
  expect(result.plots[0]).toMatchObject({ body: "saved", stories: ["legacy"] });
  expect(result.readonly).toBe(true);
  expect(fetch).toHaveBeenCalledTimes(3);
});
it("rejects an incomplete history instead of presenting stale content", async () => {
  mock([manifest, base, { ...patch, fromRevision: 0 }]);
  await expect(loadStaticSnapshot()).rejects.toThrow("不连续");
});
it("rejects paths outside generated data", async () => {
  const fetch = mock([{ ...manifest, base: "https://example.org/private" }]);
  await expect(loadStaticSnapshot()).rejects.toThrow("路径无效");
  expect(fetch.mock.calls.some(([url]) => String(url).includes("example.org"))).toBe(false);
});
