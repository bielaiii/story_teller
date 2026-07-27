import { beforeEach, describe, expect, it, vi } from "vitest";

describe("story reading location", () => {
  beforeEach(() => {
    vi.resetModules();
    window.history.replaceState({}, "", "/#/story/plot%3A39");
  });

  it("restores the same plot by stable id after a page refresh", async () => {
    const { useUiStore } = await import("./ui");

    expect(useUiStore.getState().page).toBe("story");
    expect(useUiStore.getState().selectedPlotId).toBe("plot:39");

    useUiStore.getState().selectPlot("plot:39");
    expect(window.location.hash).toBe("#/story/plot%3A39");
  });
});
