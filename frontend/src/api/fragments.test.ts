import { describe, expect, it, vi } from "vitest";
import { fragmentMutationClient } from "./fragments";
import type { ProjectMutationInput } from "./runtime";
import type { MutationDelta } from "./types";


const outcome: MutationDelta = {
  ok: true,
  fromRevision: 1,
  projectRevision: 2,
  changed: {},
  removed: {},
  operation: { id: 1, canUndo: true },
  warnings: [],
  export: { status: "ready", revision: 2 },
};

describe("fragmentMutationClient", () => {
  it("maps named generated-contract operations to the stable HTTP paths", async () => {
    const mutate = vi.fn(async (_input: ProjectMutationInput): Promise<MutationDelta> => outcome);
    const fragments = fragmentMutationClient(mutate);

    await fragments.create({ title: "新碎片" });
    await fragments.update("fragment:一/二", { body: "正文" });
    await fragments.importClipboard({ text: "# 导入" });
    await fragments.promote("fragment:一/二", { chapterNumber: 12 });
    await fragments.remove("fragment:一/二");

    expect(mutate.mock.calls.map(([input]) => input)).toEqual([
      { path: "/fragments", method: "POST", payload: { title: "新碎片" } },
      { path: "/fragments/fragment%3A%E4%B8%80%2F%E4%BA%8C", method: "PATCH", payload: { body: "正文" } },
      { path: "/fragments/import-clipboard", method: "POST", payload: { text: "# 导入" } },
      { path: "/fragments/fragment%3A%E4%B8%80%2F%E4%BA%8C/to-plot", method: "POST", payload: { chapterNumber: 12 } },
      { path: "/entities/fragment%3A%E4%B8%80%2F%E4%BA%8C", method: "DELETE", payload: {} },
    ]);
  });
});
