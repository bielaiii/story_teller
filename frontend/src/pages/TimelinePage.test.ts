import { describe, expect, it } from "vitest";
import type { TimelineLine, TimelineNode } from "../api/types";
import {
  buildTimelineGeometry,
  clampTimelineNodePosition,
  hasTimelineLineLabel,
  moveTimelineAssignment,
  normalizeTimelineLineBounds,
  timelineAutoScrollSpeed,
  timelineMinimapRatio,
  timelinePositionsFromSortKeys,
  timelineSortKeyFromPosition,
  visibleTimelineTrackIds,
} from "./TimelinePage";

function line(entityId: string, side: TimelineLine["side"], startPlotId: string | null = null, endPlotId: string | null = null): TimelineLine {
  return { entityId, id: entityId, name: entityId, color: entityId === "main" ? "#d65f8f" : "#3ba878", side, sortKey: entityId, startPlotId, endPlotId, revision: 1 };
}

describe("buildTimelineGeometry", () => {
  it("does not expose a label control for an unnamed line", () => {
    expect(hasTimelineLineLabel({ name: "" })).toBe(false);
    expect(hasTimelineLineLabel({ name: "   " })).toBe(false);
    expect(hasTimelineLineLabel({ name: "主线" })).toBe(true);
  });

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

  it("renders persisted continuous story spacing instead of snapping every plot to one fixed step", () => {
    const plotIds = ["plot:1", "plot:2", "plot:3"];
    const sortKeys = new Map([
      ["plot:1", "000000000001000000000000"],
      ["plot:2", "000000000001500000000000"],
      ["plot:3", "000000000003000000000000"],
    ]);
    const positions = timelinePositionsFromSortKeys(plotIds, sortKeys);
    const geometry = buildTimelineGeometry(
      800,
      plotIds,
      [line("main", "center")],
      plotIds.map((plotId) => ({ plotId, lineId: "main", storySortKey: sortKeys.get(plotId)! })),
      "main",
      positions,
    );

    expect((geometry.plotY.get("plot:2") || 0) - (geometry.plotY.get("plot:1") || 0)).toBe(58);
    expect((geometry.plotY.get("plot:3") || 0) - (geometry.plotY.get("plot:2") || 0)).toBe(174);
    expect(timelineSortKeyFromPosition(216, 10 ** 12)).toBe("000000000001500000000000");
  });

  it("clamps a freely spaced node between its current neighbors", () => {
    expect(clampTimelineNodePosition(100, 158, 390)).toBe(186);
    expect(clampTimelineNodePosition(500, 158, 390)).toBe(362);
    expect(clampTimelineNodePosition(275, 158, 390)).toBe(275);
  });
});

describe("timeline dragging", () => {
  const assignments = [
    { plotId: "plot:a", lineIds: ["main"], storySortKey: "001", storyPosition: 158, chapterNumber: 12 },
    { plotId: "plot:b", lineIds: ["main", "branch"], storySortKey: "002", storyPosition: 274, chapterNumber: 37 },
    { plotId: "plot:c", lineIds: ["main", "branch"], storySortKey: "003", storyPosition: 390, chapterNumber: 999 },
    { plotId: "plot:other", lineIds: ["other"], storySortKey: "004", storyPosition: 506, chapterNumber: 64 },
  ];

  it("crosses distant nodes through adjacent swaps without inventing chapter numbers", () => {
    const moved = moveTimelineAssignment(assignments, "main", "plot:a", "plot:c");
    const ordered = moved.assignments
      .filter((item) => item.lineIds.includes("main"))
      .sort((left, right) => left.storySortKey.localeCompare(right.storySortKey));

    expect(ordered.map((item) => [item.plotId, item.chapterNumber])).toEqual([
      ["plot:b", 12],
      ["plot:c", 37],
      ["plot:a", 999],
    ]);
    expect(ordered.map((item) => item.storyPosition)).toEqual([158, 274, 390]);
    expect(moved.assignments.find((item) => item.plotId === "plot:other")).toEqual(assignments[3]);
    expect(moved.swapPreview).toEqual({
      targetPlotId: "plot:c",
      fromChapterNumber: 37,
      toChapterNumber: 999,
    });
  });

  it("normalizes an affected branch to its earliest and latest remaining member", () => {
    const moved = moveTimelineAssignment(assignments, "main", "plot:a", "plot:c");
    const lines = [
      { entityId: "main", stableId: "main", persisted: true, name: "主线", color: "#111", side: "center" as const, startPlotId: null, endPlotId: null },
      { entityId: "branch", stableId: "branch", persisted: true, name: "支线", color: "#222", side: "left" as const, startPlotId: "plot:c", endPlotId: "plot:b" },
    ];

    const normalized = normalizeTimelineLineBounds(lines, moved.assignments, "main", moved.affectedLineIds);

    expect(normalized[1].startPlotId).toBe("plot:b");
    expect(normalized[1].endPlotId).toBe("plot:c");
  });

  it("accelerates edge scrolling and maps minimap movement across the full range", () => {
    expect(timelineAutoScrollSpeed(400, 100, 700, 0)).toBe(0);
    expect(timelineAutoScrollSpeed(695, 100, 700, 1600)).toBeGreaterThan(
      timelineAutoScrollSpeed(695, 100, 700, 0),
    );
    expect(timelineAutoScrollSpeed(105, 100, 700, 0)).toBeLessThan(0);
    expect(timelineMinimapRatio(350, 100, 500)).toBe(.5);
    expect(timelineMinimapRatio(900, 100, 500)).toBe(1);
  });
});
