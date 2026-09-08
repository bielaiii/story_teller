import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MergeConflictState } from "../api/types";
import { useRuntime } from "../api/runtime";
import { MergeConflictGate } from "./MergeConflictGate";

vi.mock("../api/runtime", () => ({ useRuntime: vi.fn() }));

const openState: MergeConflictState = {
  required: true,
  session: {
    id: "session-1",
    sourcePath: "content/demo/story.db",
    createdAt: 1,
    baseRevision: 4,
    oursRevision: 5,
    theirsRevision: 5,
    conflictCount: 1,
    resolvedFields: 0,
    totalFields: 1,
  },
  items: [{
    id: "conflict-1",
    title: "剧情 · 第一幕",
    table: "plots",
    entityId: "plot:1",
    status: "open",
    fields: [{
      name: "summary",
      label: "摘要",
      kind: "text",
      base: "共同版本",
      ours: "当前电脑版本",
      theirs: "远程版本",
      resolution: null,
      manualAllowed: true,
    }],
  }],
};

const resolvedState: MergeConflictState = {
  ...openState,
  session: { ...openState.session!, resolvedFields: 1 },
  items: [{
    ...openState.items[0],
    status: "resolved",
    fields: [{
      ...openState.items[0].fields[0],
      resolution: { choice: "theirs" },
    }],
  }],
};

describe("MergeConflictGate", () => {
  const mergeConflicts = vi.fn();
  const resolveMergeConflict = vi.fn();
  const finalizeMerge = vi.fn();
  const previewMerge = vi.fn();

  beforeEach(() => {
    mergeConflicts.mockReset().mockResolvedValue(openState);
    previewMerge.mockReset().mockResolvedValue({ token: "preview-1", copies: [{ entityId: "plot:1", newEntityId: "plot:new", title: "第一幕（远程版本）", kind: "plot" }], chapters: [{ entityId: "plot:new", title: "第一幕（远程版本）", before: null, after: 2 }] });
    resolveMergeConflict.mockReset().mockResolvedValue(resolvedState);
    finalizeMerge.mockReset().mockResolvedValue({
      ok: true,
      fromRevision: 5,
      projectRevision: 6,
      changed: {},
      removed: {},
      structures: {},
      operation: { id: 10, canUndo: true },
      warnings: [],
      export: { status: "ready", revision: 6 },
    });
    vi.mocked(useRuntime).mockReturnValue({
      project: "demo",
      api: { mergeConflicts, resolveMergeConflict, finalizeMerge, previewMerge } as never,
      meta: {
        apiVersion: 1,
        schemaVersion: 4,
        writable: true,
        contentWritable: false,
        mergeRequired: true,
        project: "demo",
        projectRevision: 5,
        features: ["git-database-merge-v1"],
        mutationToken: "token",
        error: "",
        routes: { mergeConflicts: true },
      },
      snapshot: {
        project: { id: "demo", title: "Demo", eyebrow: "", revision: 5, extra: {} },
        characters: [],
        plots: [],
        entries: [],
        fragments: [],
        relationships: [],
        chapters: [],
        timeline: {
          mainLineId: "", lineSpacing: 72, topPadding: 64, sidePadding: 36,
          pixelsPerStoryUnit: 760, lines: [], nodes: [],
        },
        graph: { settings: {}, nodes: [], distances: [], clusters: [] },
      },
      writable: false,
    });
  });

  afterEach(() => cleanup());

  it("blocks dismissal, saves a clear version choice, then finalizes", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MergeConflictGate />
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("alertdialog", { name: "完成内容合并后继续写作" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "关闭" })).not.toBeInTheDocument();
    expect(screen.getByText("当前电脑版本")).toBeInTheDocument();
    expect(screen.getByText("远程版本")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /采用远程更新/ }));
    fireEvent.click(screen.getByRole("button", { name: "保存这项选择" }));

    await waitFor(() => expect(resolveMergeConflict).toHaveBeenCalledWith(
      "conflict-1",
      { summary: { choice: "theirs" } },
    ));
    const finish = await screen.findByRole("button", { name: "完成合并，进入工作台" });
    expect(finish).toBeEnabled();
    fireEvent.click(finish);

    await waitFor(() => expect(finalizeMerge).toHaveBeenCalledWith("session-1"));
  });

  it("keeps two versions only when the server supports it and requires a preview", async () => {
    const bothOpen = { ...openState, items: [{ ...openState.items[0], keepBothAllowed: true, keepBothKind: "plot" }] };
    const bothSaved: MergeConflictState = { ...bothOpen, session: { ...bothOpen.session!, resolvedFields: 1 }, items: [{ ...bothOpen.items[0], status: "resolved", fields: [{ ...bothOpen.items[0].fields[0], resolution: { choice: "both" } }] }] };
    mergeConflicts.mockResolvedValue(bothOpen);
    resolveMergeConflict.mockResolvedValue(bothSaved);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MergeConflictGate /></QueryClientProvider>);
    fireEvent.click(await screen.findByRole("button", { name: /两个都保留/ }));
    fireEvent.click(screen.getByRole("button", { name: "保存这项选择" }));
    await waitFor(() => expect(resolveMergeConflict).toHaveBeenCalledWith("conflict-1", { summary: { choice: "both" } }));
    const finish = screen.getByRole("button", { name: "完成合并，进入工作台" });
    expect(finish).toBeDisabled();
    fireEvent.click(await screen.findByRole("button", { name: "预览合并结果" }));
    expect(await screen.findByRole("table")).toHaveTextContent("合并后章号");
    expect(finish).toBeEnabled();
    fireEvent.click(finish);
    await waitFor(() => expect(finalizeMerge).toHaveBeenCalledWith("session-1", "preview-1"));
  });

  it("does not expose keep-both against an older server", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MergeConflictGate /></QueryClientProvider>);
    await screen.findByRole("alertdialog");
    expect(screen.queryByRole("button", { name: /两个都保留/ })).not.toBeInTheDocument();
  });

  it("allows an overlapping text field to be manually combined", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MergeConflictGate />
      </QueryClientProvider>,
    );
    await screen.findByRole("alertdialog", { name: "完成内容合并后继续写作" });
    fireEvent.click(screen.getByRole("button", { name: /自己合并/ }));
    const editor = screen.getByRole("textbox", { name: "手动合并摘要" });
    fireEvent.change(editor, { target: { value: "保留当前重点，也加入远程重点" } });
    fireEvent.click(screen.getByRole("button", { name: "保存这项选择" }));

    await waitFor(() => expect(resolveMergeConflict).toHaveBeenCalledWith(
      "conflict-1",
      { summary: { choice: "manual", value: "保留当前重点，也加入远程重点" } },
    ));
  });
});
