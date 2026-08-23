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

describe("fragment dual-view route", () => {
  beforeEach(() => {
    vi.resetModules();
    window.history.replaceState({}, "", "/w/demo/?project=novel#/fragments/board");
  });

  it("restores the board sub-route and switches back to the card route", async () => {
    const { useUiStore } = await import("./ui");

    expect(useUiStore.getState().page).toBe("fragments");
    expect(useUiStore.getState().fragmentView).toBe("board");

    useUiStore.getState().setFragmentView("cards");
    expect(window.location.hash).toBe("#/fragments");
    expect(useUiStore.getState().fragmentView).toBe("cards");
  });
});
