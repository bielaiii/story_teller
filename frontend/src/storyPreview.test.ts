import { describe, expect, it } from "vitest";
import { compactStoryPreview } from "./storyPreview";

describe("compactStoryPreview", () => {
  it("skips an inconvenient table and uses later readable prose", () => {
    const result = compactStoryPreview("| 人物 | 状态 |\n| --- | --- |\n| 沈清妙 | 在场 |\n\n她推开门，确认走廊无人。");
    expect(result).toBe("她推开门，确认走廊无人。");
  });

  it("skips an oversized first block and keeps looking forward", () => {
    const result = compactStoryPreview(`${"很长的段落".repeat(40)}\n\n后续可读文字。`);
    expect(result).toBe("后续可读文字。");
  });
});
