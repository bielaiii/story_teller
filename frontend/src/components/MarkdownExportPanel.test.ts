import { describe, expect, it } from "vitest";
import type { Character, Plot } from "../api/types";
import {
  characterMarkdown,
  plotMarkdown,
  selectExportItems,
} from "./MarkdownExportPanel";

describe("Markdown exports", () => {
  it("selects one item, an inclusive range, or everything in display order", () => {
    const items = ["a", "b", "c", "d"];
    expect(selectExportItems(items, "single", 2, 0)).toEqual(["c"]);
    expect(selectExportItems(items, "range", 3, 1)).toEqual(["b", "c", "d"]);
    expect(selectExportItems(items, "all", 0, 0)).toEqual(items);
  });

  it("exports a plot with its chapter heading and complete body", () => {
    const markdown = plotMarkdown({
      sequence: 12,
      title: "回到金海",
      body: "第一行。\n\n第二行。",
    } as Plot);
    expect(markdown).toContain("# 第 12 章 · 回到金海");
    expect(markdown).toContain("第一行。\n\n第二行。");
  });

  it("exports the available character introduction and profile sections", () => {
    const markdown = characterMarkdown({
      name: "沈清妙",
      intro: "人物简介正文。",
      destinyOutline: "人物命运。",
      corePersona: [{ key: "要点 1", value: "冷静" }],
      supplementPersona: [],
      facts: { 身份: "调查者" },
    } as unknown as Character);
    expect(markdown).toContain("# 沈清妙");
    expect(markdown).toContain("## 人物简介\n\n人物简介正文。");
    expect(markdown).toContain("- 冷静");
    expect(markdown).toContain("- 身份：调查者");
  });
});
