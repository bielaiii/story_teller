import { describe, expect, it } from "vitest";
import { previewBlockHiddenStates } from "./CompleteBlockPreview";

describe("preview block fitting", () => {
  it("keeps the first oversized block visible so quote and code previews are not blank", () => {
    expect(previewBlockHiddenStates([260, 310], 200)).toEqual([false, true]);
  });

  it("hides later blocks after the first overflow", () => {
    expect(previewBlockHiddenStates([100, 220, 180], 200)).toEqual([false, true, true]);
  });
});
