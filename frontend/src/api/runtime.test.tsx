import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { RuntimeProvider, useProjectMutation, useRuntime } from "./runtime";
import { StoryApi } from "./client";
import type { ProjectSnapshot } from "./types";

const snapshot = (revision: number, title = "original") => ({
  project: { id: "demo", revision, title }, readonly: false,
  characters: [], plots: [], entries: [], fragments: [], relationships: [], chapters: [],
  timeline: { lines: [] }, graph: {},
}) as unknown as ProjectSnapshot;
function Probe() {
  const { snapshot } = useRuntime();
  const mutation = useProjectMutation();
  return <><span>{snapshot.project.revision}:{snapshot.project.title}</span>
    <input aria-label="draft" defaultValue="draft" />
    <button onClick={() => mutation.mutate({ path: "/plots", method: "POST", payload: {} })}>save</button></>;
}
function setup() {
  vi.spyOn(StoryApi.prototype, "meta").mockResolvedValue({ project: "demo", writable: true, features: [] } as never);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><RuntimeProvider><Probe /></RuntimeProvider></QueryClientProvider>);
  return client;
}
afterEach(() => { vi.restoreAllMocks(); focusManager.setFocused(undefined); });
it("fills an intermediate revision gap after saving without losing the editor", async () => {
  vi.spyOn(StoryApi.prototype, "snapshot").mockResolvedValueOnce(snapshot(0)).mockResolvedValue(snapshot(2, "other window"));
  vi.spyOn(StoryApi.prototype, "mutate").mockResolvedValue({ fromRevision: 1, projectRevision: 2, changed: {}, removed: {} } as never);
  setup();
  await screen.findByText("0:original");
  const input = screen.getByLabelText("draft");
  fireEvent.change(input, { target: { value: "unsaved words" } });
  fireEvent.click(screen.getByText("save"));
  await screen.findByText("2:other window");
  expect(screen.getByLabelText("draft")).toBe(input);
  expect(input).toHaveValue("unsaved words");
});
it("syncs on activation and rejects a snapshot arriving after a newer save", async () => {
  let resolve!: (value: ProjectSnapshot) => void;
  const read = vi.spyOn(StoryApi.prototype, "snapshot").mockResolvedValueOnce(snapshot(1))
    .mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  const client = setup();
  await screen.findByText("1:original");
  act(() => { focusManager.setFocused(false); focusManager.setFocused(true); });
  await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
  act(() => client.setQueryData(["snapshot", "demo"], snapshot(3, "newer")));
  await act(async () => resolve(snapshot(2, "late")));
  expect(await screen.findByText("3:newer")).toBeInTheDocument();
});
it("keeps the current surface and draft when activation sync fails", async () => {
  const read = vi.spyOn(StoryApi.prototype, "snapshot").mockResolvedValueOnce(snapshot(1))
    .mockRejectedValue(new Error("offline"));
  setup();
  await screen.findByText("1:original");
  const input = screen.getByLabelText("draft");
  fireEvent.change(input, { target: { value: "keep my draft" } });
  fireEvent(window, new Event("focus"));
  await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
  expect(screen.getByLabelText("draft")).toBe(input);
  expect(input).toHaveValue("keep my draft");
  expect(screen.getByText("1:original")).toBeInTheDocument();
});
it("uses the editor detail baseline and advances it after each successful save", async () => {
  vi.spyOn(StoryApi.prototype, "snapshot").mockResolvedValue(snapshot(4));
  const mutate = vi.spyOn(StoryApi.prototype, "mutate").mockResolvedValue({
    fromRevision: 4, projectRevision: 5, changed: { plots: [{ entityId: "plot:1", revision: 5 }] }, removed: {},
  } as never);
  function Editor() {
    const mutation = useProjectMutation();
    return <button onClick={() => mutation.mutate({ path: "/plots/plot:1", method: "PATCH", payload: {} })}>edit</button>;
  }
  vi.spyOn(StoryApi.prototype, "meta").mockResolvedValue({ project: "demo", writable: true, features: [] } as never);
  const client = new QueryClient();
  client.setQueryData(["entity", "demo", "plot:1"], { revision: 2 });
  render(<QueryClientProvider client={client}><RuntimeProvider><Editor /></RuntimeProvider></QueryClientProvider>);
  fireEvent.click(await screen.findByText("edit"));
  await waitFor(() => expect(mutate).toHaveBeenCalledWith("/plots/plot:1", "PATCH", { entityRevision: 2, baseRevision: 4 }));
  await waitFor(() => expect(client.getQueryData<ProjectSnapshot>(["snapshot", "demo"])?.project.revision).toBe(5));
  fireEvent.click(screen.getByText("edit"));
  await waitFor(() => expect(mutate).toHaveBeenLastCalledWith("/plots/plot:1", "PATCH", { entityRevision: 5, baseRevision: 5 }));
});
it("does not load a static snapshot when the local API fails at startup", async () => {
  const meta = vi.spyOn(StoryApi.prototype, "meta").mockRejectedValue(new Error("offline"));
  const fetch = vi.spyOn(window, "fetch");
  const read = vi.spyOn(StoryApi.prototype, "snapshot").mockResolvedValue(snapshot(2));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><RuntimeProvider><Probe /></RuntimeProvider></QueryClientProvider>);
  await screen.findByText("本地服务暂时不可用");
  expect(fetch).not.toHaveBeenCalled();
  meta.mockResolvedValue({ project: "demo", writable: true, features: [] } as never);
  fireEvent.click(screen.getByText("重新连接"));
  await screen.findByText("2:original");
  expect(read).toHaveBeenCalled();
});
it("uses the explicit static entry without probing the local API", async () => {
  const tag = document.createElement("meta");
  tag.name = "story-teller-mode"; tag.content = "static";
  document.head.append(tag);
  try {
    const meta = vi.spyOn(StoryApi.prototype, "meta");
    vi.spyOn(window, "fetch").mockResolvedValue(new Response(JSON.stringify(snapshot(1)), { headers: { "content-type": "application/json" } }));
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><RuntimeProvider><Probe /></RuntimeProvider></QueryClientProvider>);
    await screen.findByText("1:original");
    expect(meta).not.toHaveBeenCalled();
  } finally { tag.remove(); }
});
