import { describe, expect, it } from "vitest";
import type { MutationDelta, ProjectSnapshot } from "./types";
import { applyDelta } from "./delta";

const snapshot = {
  project: { id: "demo", title: "测试", eyebrow: "Story", revision: 3, extra: {} },
  characters: [], entries: [], fragments: [], relationships: [], chapters: [],
  plots: [
    { entityId: "plot:1", id: "1", title: "一", sortKey: "10", sequence: 1 },
    { entityId: "plot:2", id: "2", title: "二", sortKey: "20", sequence: 2 },
    { entityId: "plot:3", id: "3", title: "三", sortKey: "30", sequence: 3 },
  ],
  timeline: { mainLineId: "line:main", lineSpacing: 72, topPadding: 64, sidePadding: 36, pixelsPerStoryUnit: 760, lines: [], nodes: [] },
  graph: { settings: {}, nodes: [], distances: [], clusters: [] },
} as unknown as ProjectSnapshot;

function delta(value: Partial<MutationDelta>): MutationDelta {
  return {
    ok: true, fromRevision: 3, projectRevision: 4, changed: {}, removed: {},
    operation: { id: 1, canUndo: true }, warnings: [], export: { status: "ready" },
    ...value,
  };
}

describe("applyDelta", () => {
  it("re-sorts and re-numbers plots after an in-place delete", () => {
    const next = applyDelta(snapshot, delta({ removed: { plots: ["plot:2"] } }));
    expect(next.plots.map((item) => [item.entityId, item.sequence])).toEqual([
      ["plot:1", 1], ["plot:3", 2],
    ]);
  });

  it("replaces structural timeline and graph models without replacing the page", () => {
    const timeline = { ...snapshot.timeline, lineSpacing: 96 };
    const graph = { ...snapshot.graph, settings: { node_spacing: 137 } };
    const next = applyDelta(snapshot, delta({ structures: { timeline, graph } }));
    expect(next.timeline).toBe(timeline);
    expect(next.graph).toBe(graph);
    expect(next.project.revision).toBe(4);
  });
});
