import { describe, expect, it } from "vitest";
import { tagColor } from "./storyOptions";

describe("tag colors", () => {
  it("uses one stable color per label independently from a plot accent", () => {
    expect(tagColor("回归篇")).toBe("#c94f62");
    expect(tagColor("回归篇")).toBe(tagColor("回归篇"));
    expect(tagColor("回归篇")).not.toBe(tagColor("布局篇"));
  });
});
