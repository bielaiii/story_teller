import { describe, expect, it } from "vitest";
import type { TimelineLine } from "../api/types";
import { storyFilterLines } from "./StoryPage";

function line(entityId: string, name: string): TimelineLine {
  return {
    entityId,
    id: entityId,
    name,
    color: "#3f7fc1",
    side: entityId === "timeline:primary" ? "center" : "right",
    sortKey: entityId,
    startPlotId: null,
    endPlotId: null,
    revision: 1,
  };
}

describe("storyFilterLines", () => {
  it("keeps the virtual main filter as the only main-line option", () => {
    const lines = [
      line("timeline:primary", "主线"),
      line("timeline:branch", "支线"),
    ];

    expect(storyFilterLines(lines, "timeline:primary").map((item) => item.name)).toEqual(["支线"]);
  });

  it("uses the main-line identity instead of assuming its display name", () => {
    const lines = [
      line("timeline:primary", "核心故事"),
      line("timeline:branch", "主线"),
    ];

    expect(storyFilterLines(lines, "timeline:primary").map((item) => item.entityId)).toEqual([
      "timeline:branch",
    ]);
  });
});
