import { describe, expect, it } from "vitest";
import type { ProjectSnapshot } from "./types";
import { canRetryAgainstLatest, mutationTargetId } from "./mutationConflict";

function snapshot(projectRevision: number, characterRevision: number, plotRevision: number): ProjectSnapshot {
  return {
    project: { id: "demo", title: "Demo", eyebrow: "", revision: projectRevision, extra: {} },
    characters: [{ entityId: "character:1", revision: characterRevision } as never],
    plots: [{ entityId: "plot:1", revision: plotRevision } as never],
    entries: [],
    fragments: [],
    relationships: [],
    chapters: [],
    timeline: { mainLineId: "", lineSpacing: 72, topPadding: 64, sidePadding: 36, pixelsPerStoryUnit: 1, lines: [], nodes: [] },
    graph: { settings: {}, nodes: [], distances: [], clusters: [] },
  };
}

describe("non-overlapping mutation conflicts", () => {
  it("retries a plot save when only a character changed", () => {
    const submitted = snapshot(90, 3, 5);
    const latest = snapshot(91, 4, 5);
    expect(canRetryAgainstLatest("/plots/plot%3A1", submitted, latest)).toBe(true);
  });

  it("does not retry when the same plot changed", () => {
    const submitted = snapshot(90, 3, 5);
    const latest = snapshot(91, 3, 6);
    expect(canRetryAgainstLatest("/plots/plot%3A1", submitted, latest)).toBe(false);
  });

  it("extracts stable ids from entity mutation paths", () => {
    expect(mutationTargetId("/characters/character%3A1")).toBe("character:1");
  });
});
