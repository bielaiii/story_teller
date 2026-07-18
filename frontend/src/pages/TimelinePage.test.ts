import { describe, expect, it } from "vitest";
import type { TimelineLine, TimelineNode } from "../api/types";
import { buildTimelineGeometry, visibleTimelineTrackIds } from "./TimelinePage";

function line(entityId: string, side: TimelineLine["side"], startPlotId: string | null = null, endPlotId: string | null = null): TimelineLine {
  return { entityId, id: entityId, name: entityId, color: entityId === "main" ? "#d65f8f" : "#3ba878", side, sortKey: entityId, startPlotId, endPlotId, revision: 1 };
}

describe("buildTimelineGeometry", () => {
  it("keeps the main origin visible and gives branches complete rounded-transition geometry", () => {
    const lines = [line("main", "center"), line("branch", "left", "plot:2", "plot:4")];
    const nodes: TimelineNode[] = [
      { plotId: "plot:1", lineId: "main", storySortKey: "1" },
      { plotId: "plot:2", lineId: "main", storySortKey: "2" },
      { plotId: "plot:2", lineId: "branch", storySortKey: "2" },
      { plotId: "plot:4", lineId: "branch", storySortKey: "4" },
      { plotId: "plot:4", lineId: "main", storySortKey: "4" },
    ];

    const geometry = buildTimelineGeometry(1200, ["plot:1", "plot:2", "plot:3", "plot:4"], lines, nodes, "main");
    const main = geometry.tracks.find((track) => track.id === "main")!;
    const branch = geometry.tracks.find((track) => track.id === "branch")!;

    expect(main.startY).toBeGreaterThan(70);
    expect(main.x).toBe(600);
    expect(branch.startY).toBe(geometry.plotY.get("plot:2"));
    expect(branch.endY).toBe(geometry.plotY.get("plot:4"));
    expect(branch.startSourceX).toBe(main.x);
    expect(branch.endTargetX).toBe(main.x);
    expect(branch.x).toBeLessThan(main.x);
  });

  it("only includes tracks whose segment crosses the current viewport", () => {
    const plotIds = Array.from({ length: 10 }, (_, index) => `plot:${index + 1}`);
    const lines = [line("main", "center"), line("late-branch", "right", "plot:8", "plot:9")];
    const nodes: TimelineNode[] = [
      ...plotIds.map((plotId, index) => ({ plotId, lineId: "main", storySortKey: String(index + 1) })),
      { plotId: "plot:8", lineId: "late-branch", storySortKey: "8" },
      { plotId: "plot:9", lineId: "late-branch", storySortKey: "9" },
    ];
    const geometry = buildTimelineGeometry(1200, plotIds, lines, nodes, "main");

    expect([...visibleTimelineTrackIds(geometry, 0, 520)]).toEqual(["main"]);
    expect([...visibleTimelineTrackIds(geometry, 860, 1220)]).toEqual(["main", "late-branch"]);
  });
});
