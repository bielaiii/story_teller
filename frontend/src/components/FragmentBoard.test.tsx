import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Character, Fragment, ProjectSnapshot } from "../api/types";
import { fragmentBoardStorageKey } from "../fragmentBoard";
import { FragmentBoard } from "./FragmentBoard";

const mocks = vi.hoisted(() => ({ detail: vi.fn() }));

function fragment(id: string, options: Partial<Fragment> = {}): Fragment {
  return {
    entityId: `fragment:${id}`,
    id,
    title: id,
    status: "灵感",
    accent: "#7d6bd6",
    tags: [],
    bodyPreview: `${id}摘要`,
    references: [],
    revision: 1,
    extra: {},
    ...options,
  };
}

const character: Character = {
  entityId: "character:shen",
  id: "shen",
  name: "沈清妙",
  aliases: [],
  markers: [],
  facts: {},
  supplements: [],
  narrativeRole: "主角",
  characterScope: "主线人物",
  side: "主角方",
  mainPlotImpact: 100,
  color: "#d65f8f",
  gradient: "",
  group: "",
  graphVisible: true,
  revision: 1,
  introPreview: "",
  extra: {},
};

const line = fragment("复仇线", {
  fragmentType: "line",
  tags: ["复仇"],
  references: [character.entityId],
});
const chapter = fragment("第 1 章：回归", {
  title: "第 1 章：回归",
  parentFragmentId: line.entityId,
  chapterNumber: 1,
  tags: ["复仇"],
  references: [character.entityId],
});
const standalone = fragment("午后", { tags: ["日常"] });

const snapshot: ProjectSnapshot = {
  project: { id: "demo", title: "测试项目", eyebrow: "", revision: 7, extra: {} },
  characters: [character],
  plots: [],
  entries: [],
  fragments: [line, chapter, standalone],
  relationships: [],
  chapters: [],
  timeline: { mainLineId: "", lineSpacing: 72, topPadding: 64, sidePadding: 36, pixelsPerStoryUnit: 760, lines: [], nodes: [] },
  graph: { settings: {}, nodes: [], distances: [], clusters: [] },
};

vi.mock("../api/runtime", () => ({
  useRuntime: () => ({
    api: { detail: mocks.detail },
    project: "demo",
    snapshot,
    writable: true,
  }),
}));

function renderBoard(props: Partial<React.ComponentProps<typeof FragmentBoard>> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <FragmentBoard
        fragments={snapshot.fragments}
        selectedTags={["复仇"]}
        allTags={["复仇", "日常"]}
        onEdit={vi.fn()}
        onImmersive={vi.fn()}
        {...props}
      />
    </QueryClientProvider>,
  );
}

describe("FragmentBoard", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mocks.detail.mockReset();
    mocks.detail.mockImplementation(async (id: string) => ({
      data: { ...snapshot.fragments.find((item) => item.entityId === id)!, body: `# 完整正文\n${id}` },
    }));
    Object.defineProperty(HTMLElement.prototype, "setPointerCapture", { configurable: true, value: vi.fn() });
    Object.defineProperty(HTMLElement.prototype, "hasPointerCapture", { configurable: true, value: vi.fn(() => false) });
    Object.defineProperty(HTMLElement.prototype, "releasePointerCapture", { configurable: true, value: vi.fn() });
    Object.defineProperty(HTMLElement.prototype, "scrollTo", { configurable: true, value: vi.fn() });
    Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
      configurable: true,
      value: vi.fn(() => ({
        setTransform: vi.fn(),
        clearRect: vi.fn(),
        setLineDash: vi.fn(),
        beginPath: vi.fn(),
        moveTo: vi.fn(),
        quadraticCurveTo: vi.fn(),
        stroke: vi.fn(),
      })),
    });
  });

  it("renders every fragment and dims rather than removes tag-filtered nodes", () => {
    const { container } = renderBoard();

    expect(screen.getByRole("button", { name: "阅读复仇线" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "阅读回归" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "阅读午后" })).toHaveClass("is-tag-dimmed");
    expect(container.querySelectorAll(".fragment-board-node")).toHaveLength(3);
    expect(container.querySelector(".fragment-board-links")).toBeInTheDocument();
    expect(container.querySelectorAll(".fragment-board-node-dot")).toHaveLength(3);
  });

  it("opens full Markdown in the side reader and reveals all focus relationships", async () => {
    renderBoard();
    fireEvent.click(screen.getByRole("button", { name: "阅读复仇线" }));

    expect(await screen.findByRole("complementary", { name: "阅读复仇线" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "完整正文" })).toBeInTheDocument();
    expect(screen.getAllByText("人物：沈清妙").length).toBeGreaterThan(0);
    expect(screen.getAllByText("标签：复仇").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "沉浸阅读" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "编辑复仇线" })).toBeInTheDocument();
  });

  it("distinguishes dragging from reading and saves the moved point locally", async () => {
    renderBoard();
    const node = screen.getByRole("button", { name: "阅读午后" });
    const beforeLeft = Number((node as HTMLElement).style.left.replace("px", ""));

    fireEvent.pointerDown(node, { pointerId: 4, button: 0, clientX: 200, clientY: 200 });
    fireEvent.pointerMove(node, { pointerId: 4, clientX: 280, clientY: 250 });
    fireEvent.pointerUp(node, { pointerId: 4, clientX: 280, clientY: 250 });
    fireEvent.click(node);

    expect(Number((node as HTMLElement).style.left.replace("px", ""))).toBeGreaterThan(beforeLeft);
    expect(screen.queryByRole("complementary", { name: "阅读午后" })).toBeNull();
    await waitFor(() => {
      const raw = window.localStorage.getItem(fragmentBoardStorageKey(window.location.pathname, "demo"));
      expect(raw).toContain(standalone.entityId);
    });
  });

  it("resets only the local layout after confirmation", async () => {
    renderBoard();
    const node = screen.getByRole("button", { name: "阅读午后" });
    fireEvent.pointerDown(node, { pointerId: 5, button: 0, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(node, { pointerId: 5, clientX: 190, clientY: 160 });
    fireEvent.pointerUp(node, { pointerId: 5, clientX: 190, clientY: 160 });

    fireEvent.click(screen.getByRole("button", { name: "重新整理画布" }));
    fireEvent.click(screen.getByRole("button", { name: "重新整理" }));

    expect(screen.queryByRole("alertdialog")).toBeNull();
    await waitFor(() => expect(window.localStorage.getItem(fragmentBoardStorageKey(window.location.pathname, "demo"))).not.toBeNull());
  });
});
