import { describe, expect, it } from "vitest";
import { plotChapterNumber, tagColor } from "./storyOptions";

describe("plot chapter numbers", () => {
  it("uses the chapter number in the title instead of the reading sequence", () => {
    expect(plotChapterNumber("第 17 章", 2)).toBe(17);
  });

  it("prefers the persisted chapter number over a title or reading fallback", () => {
    expect(plotChapterNumber("港口重逢", 2, 999)).toBe(999);
  });
});

describe("tag colors", () => {
  it("uses one stable color per label independently from a plot accent", () => {
    expect(tagColor("回归篇")).toBe("#c94f62");
    expect(tagColor("回归篇")).toBe(tagColor("回归篇"));
    expect(tagColor("回归篇")).not.toBe(tagColor("布局篇"));
  });
});
