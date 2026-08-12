import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RagUpdatePanel } from "./RagUpdatePanel";

const mocks = vi.hoisted(() => ({ rebuildRag: vi.fn() }));

vi.mock("../api/runtime", () => ({
  useRuntime: () => ({
    api: { rebuildRag: mocks.rebuildRag },
    meta: {
      features: ["rag-rebuild-v1"],
      routes: { ragRebuild: true },
    },
    writable: true,
  }),
}));

describe("RagUpdatePanel", () => {
  afterEach(() => {
    cleanup();
    mocks.rebuildRag.mockReset();
  });

  it("rebuilds the RAG index and reports the indexed content", async () => {
    mocks.rebuildRag.mockResolvedValue({
      path: "rag.db",
      sourceRevision: 17,
      documents: 42,
      chunks: 108,
      embeddingStatus: "ready",
      embeddingError: "",
      status: { project: "demo", exists: true, fresh: true },
    });
    const onMessage = vi.fn();
    render(<RagUpdatePanel onMessage={onMessage} />);

    fireEvent.click(screen.getByRole("button", { name: "更新 RAG" }));
    await waitFor(() => expect(mocks.rebuildRag).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText(/版本 17/)).toBeVisible());
    expect(screen.getByText("已同步")).toBeVisible();
    expect(onMessage).toHaveBeenLastCalledWith("RAG 已更新：42 个文档，108 个文本块");
  });
});
