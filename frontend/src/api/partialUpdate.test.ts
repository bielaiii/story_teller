import { expect, it } from "vitest";
import { changedFields } from "./partialUpdate";

it("sends a title change without unchanged body and collections", () => {
  const baseline = { title: "old", body: "long body", tags: ["a"], chapterNumber: 1 };
  expect(changedFields({ ...baseline, title: "new", entityRevision: 5, shiftFollowing: false }, baseline))
    .toEqual({ title: "new", entityRevision: 5 });
});
it("sends only the changed body and preserves explicit clearing", () => {
  expect(changedFields({ title: "same", body: "", tags: [], entityRevision: 5 }, { title: "same", body: "old", tags: ["a"] }))
    .toEqual({ body: "", tags: [], entityRevision: 5 });
});
it("keeps dependent story-position fields and chapter conflict policy together", () => {
  expect(changedFields({ storyPositionMode: "before", storyAnchorPlotId: "plot:2", chapterNumber: 2, shiftFollowing: true },
    { storyPositionMode: "before", storyAnchorPlotId: "plot:1", chapterNumber: 1 })).toEqual({
      storyPositionMode: "before", storyAnchorPlotId: "plot:2", chapterNumber: 2, shiftFollowing: true,
    });
});
