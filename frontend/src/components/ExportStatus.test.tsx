import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StoryApi } from "../api/client";
import { ExportStatus } from "./ExportStatus";

afterEach(cleanup);

describe("ExportStatus", () => {
  function setup(enabled = true) {
    const exportStatus = vi.fn().mockResolvedValue({ status: "pending" });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}>
      <ExportStatus api={{ exportStatus } as unknown as StoryApi} project="demo" enabled={enabled} />
    </QueryClientProvider>);
    return { exportStatus, client };
  }

  it("shows pending until exported and stops polling after completion", async () => {
    const { exportStatus, client } = setup();
    expect(await screen.findByRole("status")).toHaveTextContent("正文已保存，正在更新导出");
    exportStatus.mockResolvedValue({ status: "ready" });
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument(), { timeout: 2500 });
    const calls = exportStatus.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 1100));
    expect(exportStatus).toHaveBeenCalledTimes(calls);
    client.clear();
  });

  it("keeps export failure distinct from a failed save and refreshes on the next save", async () => {
    const { exportStatus, client } = setup();
    await screen.findByRole("status");
    exportStatus.mockResolvedValue({ status: "failed", lastError: "disk full" });
    await act(() => client.invalidateQueries({ queryKey: ["exports", "demo"] }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("正文已保存，导出失败：disk full"));
    exportStatus.mockResolvedValue({ status: "ready" });
    await act(() => client.invalidateQueries({ queryKey: ["exports", "demo"] }));
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    client.clear();
  });

  it("does not poll in static mode or on older services", () => {
    const { exportStatus, client } = setup(false);
    expect(exportStatus).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    client.clear();
  });
});
