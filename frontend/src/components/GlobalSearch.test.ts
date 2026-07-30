import { describe, expect, it } from "vitest";
import { searchMatchContext } from "./GlobalSearch";

describe("searchMatchContext", () => {
  it("shows the matching text instead of only the beginning of a long article", () => {
    const source = `${"前置内容".repeat(40)}沈清妙在仓库门口停下。${"后续内容".repeat(40)}`;
    const result = searchMatchContext(source, "沈清妙", 12);

    expect(result).toContain("沈清妙在仓库门口停下");
    expect(result.startsWith("…")).toBe(true);
    expect(result.endsWith("…")).toBe(true);
  });

  it("removes common Markdown decoration from the preview", () => {
    expect(searchMatchContext("## 标题\n\n**黎清妍**打开了[档案](https://example.com)。", "黎清妍"))
      .toBe("标题 黎清妍 打开了档案。");
  });
});
