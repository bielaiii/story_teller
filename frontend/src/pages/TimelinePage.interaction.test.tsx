import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ProjectSnapshot } from "../api/types";
import { useUiStore } from "../state/ui";
import TimelinePage, { positionTimelinePlotCard } from "./TimelinePage";

const mocks = vi.hoisted(() => ({
  mutateAsync: vi.fn(),
}));

const snapshot: ProjectSnapshot = {
  project: { id: "demo", title: "测试项目", eyebrow: "", revision: 7, extra: {} },
  characters: [],
  plots: [
    {
      entityId: "plot:a", id: "a", title: "第 12 章", chapterNumber: 12, sortKey: "001",
      sequence: 1, summary: "甲", bodyPreview: "甲", status: "草稿", accent: "#c94f62",
      key: false, climax: false, tags: [], people: [], entries: [], stories: [], revision: 1, extra: {},
    },
    {
      entityId: "plot:b", id: "b", title: "第 37 章", chapterNumber: 37, sortKey: "002",
      sequence: 2, summary: "乙", bodyPreview: "乙", status: "草稿", accent: "#3979b8",
      key: false, climax: false, tags: [], people: [], entries: [], stories: [], revision: 1, extra: {},
    },
    {
      entityId: "plot:c", id: "c", title: "第 999 章", chapterNumber: 999, sortKey: "003",
      sequence: 3, summary: "丙", bodyPreview: "丙", status: "草稿", accent: "#2b8a72",
      key: false, climax: false, tags: [], people: [], entries: [], stories: [], revision: 1, extra: {},
    },
  ],
  entries: [],
  fragments: [],
  relationships: [],
  chapters: [],
  timeline: {
    mainLineId: "line:main",
    lineSpacing: 72,
    topPadding: 64,
    sidePadding: 36,
    pixelsPerStoryUnit: 760,
    lines: [{
      entityId: "line:main", id: "main", name: "主线", color: "#c94f62", side: "center",
      sortKey: "001", startPlotId: null, endPlotId: null, revision: 1,
    }],
    nodes: [
      { plotId: "plot:a", lineId: "line:main", storySortKey: "000000000001000000000000" },
      { plotId: "plot:b", lineId: "line:main", storySortKey: "000000000002000000000000" },
      { plotId: "plot:c", lineId: "line:main", storySortKey: "000000000003000000000000" },
    ],
  },
  graph: { settings: {}, nodes: [], distances: [], clusters: [] },
};

vi.mock("../api/runtime", () => ({
  useRuntime: () => ({
    api: { detail: vi.fn() },
    project: "demo",
    snapshot,
    writable: true,
    meta: {
      apiVersion: 1,
      schemaVersion: 3,
      writable: true,
      project: "demo",
      projectRevision: 7,
      features: ["timeline-drag-chapter-swap-v1"],
      mutationToken: "token",
      error: "",
      routes: { timelineChapterSwap: true },
    },
  }),
  useProjectMutation: () => ({
    isPending: false,
    mutateAsync: mocks.mutateAsync,
  }),
}));

function renderTimeline() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <TimelinePage />
    </QueryClientProvider>,
  );
}

describe("timeline plot card placement", () => {
  it("places the card on the less crowded side near the selected node", () => {
    expect(positionTimelinePlotCard(
      { x: 640, y: 440 },
      [{ x: 510, y: 360 }, { x: 540, y: 480 }, { x: 760, y: 900 }],
      { width: 1280, height: 800 },
      { width: 330, height: 320 },
    )).toEqual({ left: 662, top: 280, side: "right" });

    expect(positionTimelinePlotCard(
      { x: 640, y: 440 },
      [{ x: 760, y: 360 }, { x: 790, y: 480 }, { x: 510, y: 900 }],
      { width: 1280, height: 800 },
      { width: 330, height: 320 },
    )).toEqual({ left: 288, top: 280, side: "left" });
  });

  it("uses the side that fits and keeps the card inside the viewport", () => {
    expect(positionTimelinePlotCard(
      { x: 1100, y: 90 },
      [{ x: 900, y: 100 }, { x: 920, y: 180 }],
      { width: 1280, height: 800 },
      { width: 330, height: 320 },
    )).toEqual({ left: 748, top: 68, side: "left" });
  });
});

describe("TimelinePage drag interaction", () => {
  afterEach(cleanup);
  afterEach(() => vi.useRealTimers());

  beforeEach(() => {
    mocks.mutateAsync.mockReset();
    mocks.mutateAsync.mockResolvedValue({ warnings: [] });
    useUiStore.getState().setTimelineFocus(null);
    Object.defineProperty(navigator, "platform", { configurable: true, value: "Win32" });
    Object.defineProperty(navigator, "userAgent", { configurable: true, value: "Timeline test browser" });
    Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
      configurable: true,
      value: () => null,
    });
    Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
      configurable: true,
      value: () => undefined,
    });
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value(options: ScrollToOptions) {
        if (typeof options.top === "number") this.scrollTop = options.top;
      },
    });
    Object.defineProperty(window, "scrollTo", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("keeps the timeline legend in place while a plot preview card is open", () => {
    renderTimeline();

    fireEvent.click(screen.getByRole("button", { name: "查看剧情：第 12 章" }));

    const card = document.querySelector(".timeline-plot-card") as HTMLElement;
    const actions = card.querySelector(".timeline-plot-card-actions");
    const headingCopy = card.querySelector(".timeline-plot-card-header > div:first-child")!;
    expect(card).toBeInTheDocument();
    expect(headingCopy.children[0]).toBe(screen.getByRole("heading", { name: "第 12 章" }));
    expect(headingCopy.children[1]).toHaveTextContent("剧情节点 · 故事 1 · 阅读 1");
    expect(actions).toContainElement(screen.getByRole("button", { name: "进入完整文章" }));
    expect(actions).toContainElement(screen.getByRole("button", { name: "关闭剧情卡片" }));
    expect(actions?.children).toHaveLength(2);
    expect(screen.getByRole("complementary", { name: "时间线图示" })).not.toHaveClass("has-plot-card");

    fireEvent.click(screen.getByRole("button", { name: "关闭剧情卡片" }));
    expect(document.querySelector(".timeline-plot-card")).not.toBeInTheDocument();
  });

  it("steps through plots with the wheel after selecting a timeline node", () => {
    renderTimeline();
    const canvas = document.querySelector(".timeline-canvas-new") as HTMLElement;

    fireEvent.click(screen.getByRole("button", { name: "查看剧情：第 12 章" }));
    const preview = document.querySelector(".timeline-plot-preview") as HTMLElement;
    preview.scrollTop = 72;
    fireEvent.wheel(canvas, { deltaY: 120 });

    expect(screen.getByRole("heading", { name: "第 37 章" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查看剧情：第 37 章" })).toHaveAttribute("aria-pressed", "true");
    expect(preview.scrollTop).toBe(0);
    expect(window.scrollTo).toHaveBeenCalledWith(expect.objectContaining({ behavior: "smooth" }));

    fireEvent.wheel(canvas, { deltaY: -120 });
    expect(screen.getByRole("heading", { name: "第 12 章" })).toBeInTheDocument();
  });

  it("keeps ordinary canvas scrolling on macOS", () => {
    Object.defineProperty(navigator, "platform", { configurable: true, value: "MacIntel" });
    renderTimeline();
    const canvas = document.querySelector(".timeline-canvas-new") as HTMLElement;

    fireEvent.click(screen.getByRole("button", { name: "查看剧情：第 12 章" }));
    fireEvent.wheel(canvas, { deltaY: 120 });

    expect(screen.getByRole("heading", { name: "第 12 章" })).toBeInTheDocument();
    expect(window.scrollTo).not.toHaveBeenCalled();
  });

  it("scrolls preview content instead of changing plots while the pointer is over the card", () => {
    renderTimeline();
    fireEvent.click(screen.getByRole("button", { name: "查看剧情：第 12 章" }));
    const card = document.querySelector(".timeline-plot-card") as HTMLElement;
    const preview = card.querySelector(".timeline-plot-preview") as HTMLElement;

    fireEvent.wheel(card, { deltaY: 84 });

    expect(preview.scrollTop).toBe(84);
    expect(screen.getByRole("heading", { name: "第 12 章" })).toBeInTheDocument();
    expect(window.scrollTo).not.toHaveBeenCalled();
  });

  it("restores with Escape, then saves a continuous position without changing order or chapter numbers", async () => {
    renderTimeline();
    fireEvent.click(screen.getByRole("button", { name: "编辑时间线" }));
    const dialog = screen.getByRole("dialog", { name: "编辑时间线" });
    const firstNode = within(dialog).getByRole("button", { name: /第12章/ });

    fireEvent.pointerDown(firstNode, { pointerId: 1, button: 0, clientX: 360, clientY: 158 });
    fireEvent.pointerMove(firstNode, { pointerId: 1, clientX: 360, clientY: 220 });
    expect(within(dialog).getByRole("heading", { name: /第 12 章/ })).toBeInTheDocument();
    expect(screen.getByText("自由调整节点间距")).toBeInTheDocument();
    expect(firstNode).toHaveStyle({ top: "220px" });
    expect(document.querySelector(".timeline-drag-minimap")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(within(dialog).getByRole("heading", { name: /第 12 章/ })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /第12章/ })).toHaveStyle({ top: "158px" });
    expect(document.querySelector(".timeline-drag-minimap")).not.toBeInTheDocument();

    const restoredNode = within(dialog).getByRole("button", { name: /第12章/ });
    fireEvent.pointerDown(restoredNode, { pointerId: 2, button: 0, clientX: 360, clientY: 158 });
    fireEvent.pointerMove(restoredNode, { pointerId: 2, clientX: 360, clientY: 220 });
    fireEvent.pointerUp(restoredNode, { pointerId: 2, clientX: 360, clientY: 220 });

    expect(within(dialog).getByRole("heading", { name: /第 12 章/ })).toBeInTheDocument();
    expect(mocks.mutateAsync).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "保存时间线" }));

    await waitFor(() => expect(mocks.mutateAsync).toHaveBeenCalledTimes(1));
    const request = mocks.mutateAsync.mock.calls[0][0];
    expect(request.path).toBe("/timeline");
    expect(request.payload.chapterNumbers).toBeUndefined();
    const savedKeys = request.payload.assignments.map((item: { storySortKey: string }) => Number(item.storySortKey));
    expect(savedKeys[0]).toBeGreaterThan(10 ** 12);
    expect(savedKeys[0]).toBeLessThan(savedKeys[1]);
    expect(savedKeys[1]).toBeLessThan(savedKeys[2]);
  });

  it("pushes every crossed node and submits the synchronized chapter order", async () => {
    renderTimeline();
    fireEvent.click(screen.getByRole("button", { name: "编辑时间线" }));
    const dialog = screen.getByRole("dialog", { name: "编辑时间线" });
    const firstNode = within(dialog).getByRole("button", { name: /第12章/ });

    fireEvent.pointerDown(firstNode, { pointerId: 9, button: 0, clientX: 360, clientY: 158 });
    fireEvent.pointerMove(firstNode, { pointerId: 9, clientX: 360, clientY: 390 });

    expect(screen.getByText("已推动沿途节点 · 保存后同步篇次")).toBeInTheDocument();
    expect(firstNode).toHaveStyle({ top: "390px" });
    expect(within(dialog).getByRole("button", { name: /第12章/ })).toHaveStyle({ top: "158px" });
    expect(within(dialog).getByRole("button", { name: /第37章/ })).toHaveStyle({ top: "274px" });

    fireEvent.pointerUp(firstNode, { pointerId: 9, clientX: 360, clientY: 390 });
    fireEvent.click(within(dialog).getByRole("button", { name: "保存时间线" }));

    await waitFor(() => expect(mocks.mutateAsync).toHaveBeenCalledTimes(1));
    const request = mocks.mutateAsync.mock.calls[0][0];
    expect(request.payload.chapterNumbers).toEqual([
      { plotId: "plot:a", chapterNumber: 999 },
      { plotId: "plot:b", chapterNumber: 12 },
      { plotId: "plot:c", chapterNumber: 37 },
    ]);
    const orderedPlotIds = [...request.payload.assignments]
      .sort((left, right) => left.storySortKey.localeCompare(right.storySortKey))
      .map((item) => item.plotId);
    expect(orderedPlotIds).toEqual(["plot:b", "plot:c", "plot:a"]);
  });

  it("keeps a dragged branch node on its branch track without an insertion line", () => {
    snapshot.timeline.lines.push({
      entityId: "line:branch", id: "branch", name: "支线", color: "#2b8a72", side: "right",
      sortKey: "002", startPlotId: "plot:a", endPlotId: "plot:c", revision: 1,
    });
    snapshot.timeline.nodes.push({
      plotId: "plot:a", lineId: "line:branch", storySortKey: "000000000001000000000000",
    });
    try {
      renderTimeline();
      fireEvent.click(screen.getByRole("button", { name: "编辑时间线" }));
      const branchNode = document.querySelector(
        '.timeline-editor-track-node[data-plot-id="plot:a"][data-line-id="line:branch"]',
      ) as HTMLElement;

      expect(branchNode).toHaveStyle({ left: "442px", top: "158px" });
      fireEvent.pointerDown(branchNode, { pointerId: 10, button: 0, clientX: 442, clientY: 158 });
      fireEvent.pointerMove(branchNode, { pointerId: 10, clientX: 442, clientY: 220 });

      expect(branchNode).toHaveClass("is-dragging");
      expect(branchNode).toHaveStyle({ left: "442px", top: "220px" });
      expect(document.querySelector(".timeline-drag-insertion")).not.toBeInTheDocument();
      fireEvent.pointerUp(branchNode, { pointerId: 10, clientX: 442, clientY: 220 });
    } finally {
      snapshot.timeline.nodes.pop();
      snapshot.timeline.lines.pop();
    }
  });

  it("uses the temporary minimap to jump across content outside the visible preview", () => {
    renderTimeline();
    fireEvent.click(screen.getByRole("button", { name: "编辑时间线" }));
    const dialog = screen.getByRole("dialog", { name: "编辑时间线" });
    const firstNode = within(dialog).getByRole("button", { name: /第12章/ });

    fireEvent.pointerDown(firstNode, { pointerId: 3, button: 0, clientX: 360, clientY: 158 });
    const minimap = document.querySelector(".timeline-drag-minimap") as HTMLElement;
    const scroller = document.querySelector(".timeline-editor-visual-scroll") as HTMLElement;
    vi.spyOn(minimap, "getBoundingClientRect").mockReturnValue({
      x: 680, y: 100, left: 680, right: 708, top: 100, bottom: 600,
      width: 28, height: 500, toJSON: () => ({}),
    });
    Object.defineProperty(scroller, "scrollHeight", { configurable: true, value: 1200 });
    Object.defineProperty(scroller, "clientHeight", { configurable: true, value: 300 });

    fireEvent.pointerMove(firstNode, { pointerId: 3, clientX: 694, clientY: 590 });

    expect(scroller.scrollTop).toBeGreaterThan(850);
    expect(within(dialog).getByRole("heading", { name: /第 999 章/ })).toBeInTheDocument();
    expect(Number(firstNode.style.top.replace("px", ""))).toBeGreaterThan(390);
    fireEvent.pointerUp(firstNode, { pointerId: 3, clientX: 694, clientY: 590 });
    expect(document.querySelector(".timeline-drag-minimap")).not.toBeInTheDocument();
  });

  it("keeps pointer capture active while the preview auto-scrolls near an edge", () => {
    vi.useFakeTimers();
    renderTimeline();
    fireEvent.click(screen.getByRole("button", { name: "编辑时间线" }));
    const dialog = screen.getByRole("dialog", { name: "编辑时间线" });
    const firstNode = within(dialog).getByRole("button", { name: /第12章/ });
    const scroller = document.querySelector(".timeline-editor-visual-scroll") as HTMLElement;
    vi.spyOn(scroller, "getBoundingClientRect").mockReturnValue({
      x: 0, y: 100, left: 0, right: 720, top: 100, bottom: 400,
      width: 720, height: 300, toJSON: () => ({}),
    });
    Object.defineProperty(scroller, "scrollHeight", { configurable: true, value: 2400 });
    Object.defineProperty(scroller, "clientHeight", { configurable: true, value: 300 });

    fireEvent.pointerDown(firstNode, { pointerId: 4, button: 0, clientX: 360, clientY: 158 });
    fireEvent.pointerMove(firstNode, { pointerId: 4, clientX: 360, clientY: 430 });
    act(() => vi.advanceTimersByTime(800));

    expect(scroller.scrollTop).toBeGreaterThan(0);
    expect(document.querySelector(".timeline-drag-ghost")).toBeInTheDocument();
    fireEvent.pointerUp(firstNode, { pointerId: 4, clientX: 360, clientY: 430 });
    expect(document.querySelector(".timeline-drag-ghost")).not.toBeInTheDocument();
  });
});
