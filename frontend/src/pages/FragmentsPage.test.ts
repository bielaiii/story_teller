import { describe, expect, it } from "vitest";
import type { Fragment } from "../api/types";
import {
  fragmentChapterNumberOf,
  fragmentDownloadFilename,
  fragmentDownloadMarkdown,
  fragmentDisplayTitle,
  fragmentLinePreviewOf,
  fragmentParentOf,
  fragmentPlotChapterPlanOf,
  fragmentTypeOf,
  fragmentWorkspaceLineId,
  groupFragments,
  readClipboardText,
} from "./FragmentsPage";

function item(
  entityId: string,
  fragmentType?: "chapter" | "line",
  parentFragmentId: string | null = null,
  fragmentOrder = 0,
  chapterNumber: number | null = null,
): Fragment {
  return {
    entityId,
    id: entityId.split(":")[1],
    title: entityId,
    status: "",
    accent: "#7d6bd6",
    tags: [],
    bodyPreview: "",
    revision: 1,
    fragmentType,
    parentFragmentId,
    fragmentOrder,
    chapterNumber,
    extra: {},
  };
}

describe("fragment story-line grouping", () => {
  it("builds a safe Markdown download for one fragment card", () => {
    const chapter = {
      ...item("fragment:chapter", "chapter", "fragment:line", 0, 7),
      title: "第 7 章：潮汐记录 / 初稿",
      tags: ["悬疑", "线索"],
    };

    expect(fragmentDownloadFilename(chapter)).toBe("潮汐记录 _ 初稿.md");
    expect(fragmentDownloadMarkdown(chapter, "正文内容")).toBe(
      "# 潮汐记录 / 初稿\n章节：第 7 章\n标签：悬疑、线索\n\n正文内容\n",
    );
  });

  it("packages every chapter under a story line into one Markdown download", () => {
    const line = item("fragment:line", "line");
    const chapters = [
      { item: item("fragment:1", "chapter", line.entityId, 0, 1), body: "第一章正文" },
      { item: item("fragment:3", "chapter", line.entityId, 1, 3), body: "第三章正文" },
    ];

    expect(fragmentDownloadMarkdown(line, "", chapters)).toBe(
      "# fragment:line\n\n## 所属篇章\n### 第 1 章 · fragment:1\n第一章正文\n\n### 第 3 章 · fragment:3\n第三章正文\n",
    );
  });

  it("keeps lines and standalone chapters at the top level and orders children", () => {
    const line = item("fragment:line", "line");
    const second = item("fragment:2", "chapter", line.entityId, 2);
    const first = item("fragment:1", "chapter", line.entityId, 1);
    const standalone = item("fragment:solo", "chapter");

    const grouped = groupFragments([second, standalone, line, first]);

    expect(grouped.topLevel.map((value) => value.entityId)).toEqual([
      standalone.entityId,
      line.entityId,
    ]);
    expect(grouped.children.get(line.entityId)?.map((value) => value.entityId)).toEqual([
      first.entityId,
      second.entityId,
    ]);
  });

  it("treats legacy and orphaned fragments as readable standalone chapters", () => {
    const legacy = item("fragment:legacy");
    const orphan = item("fragment:orphan", "chapter", "fragment:missing");
    const extraOnly = {
      ...item("fragment:extra"),
      fragmentType: undefined,
      parentFragmentId: undefined,
      extra: { fragmentType: "line", parentFragmentId: null },
    };

    const grouped = groupFragments([legacy, orphan, extraOnly]);

    expect(grouped.topLevel).toHaveLength(3);
    expect(fragmentTypeOf(legacy)).toBe("chapter");
    expect(fragmentParentOf(orphan)).toBe("fragment:missing");
    expect(fragmentTypeOf(extraOnly)).toBe("line");
  });

  it("opens both a line and one of its chapters in the same line workspace", () => {
    const line = item("fragment:line", "line");
    const chapter = item("fragment:chapter", "chapter", line.entityId, 1);

    expect(fragmentWorkspaceLineId([line, chapter], line.entityId)).toBe(line.entityId);
    expect(fragmentWorkspaceLineId([line, chapter], chapter.entityId)).toBe(line.entityId);
    expect(fragmentWorkspaceLineId([line, chapter], "new", line.entityId)).toBe(line.entityId);
  });

  it("sorts by independent chapter numbers while allowing gaps", () => {
    const line = item("fragment:line", "line");
    const later = item("fragment:later", "chapter", line.entityId, 0, 25);
    const earlier = item("fragment:earlier", "chapter", line.entityId, 1, 3);

    const grouped = groupFragments([line, later, earlier]);

    expect(grouped.children.get(line.entityId)?.map((value) => value.entityId)).toEqual([
      earlier.entityId,
      later.entityId,
    ]);
    expect(fragmentChapterNumberOf(later)).toBe(25);
  });

  it("reads legacy chapter prefixes without keeping them in the editable title", () => {
    const legacy = {
      ...item("fragment:legacy", "chapter", "fragment:line", 7),
      title: "第 18 章：旧标题",
      chapterNumber: undefined,
    };

    expect(fragmentChapterNumberOf(legacy)).toBe(18);
    expect(fragmentDisplayTitle(legacy)).toBe("旧标题");
  });

  it("uses the first chapter as the story-line card preview", () => {
    const line = item("fragment:line", "line");
    const first = { ...item("fragment:first", "chapter", line.entityId, 0, 1), bodyPreview: "第一章剧情" };
    const second = { ...item("fragment:second", "chapter", line.entityId, 1, 2), bodyPreview: "第二章剧情" };

    expect(fragmentLinePreviewOf(line, [first, second])).toBe("第一章剧情");
    expect(fragmentLinePreviewOf(line, [])).toBe("第一章还没有正文");
  });

  it("keeps valid formal plot chapter planning while ignoring malformed values", () => {
    const line = {
      ...item("fragment:line", "line"),
      extra: {
        plotChapterPlan: {
          "fragment:1": 24,
          "fragment:2": 31,
          "fragment:invalid": 0,
          "fragment:text": "42",
        },
      },
    };

    expect(fragmentPlotChapterPlanOf(line)).toEqual({
      "fragment:1": 24,
      "fragment:2": 31,
    });
  });
});

describe("clipboard access fallback", () => {
  it("returns clipboard text when direct access is available", async () => {
    await expect(readClipboardText(async () => "第一章：抵达")).resolves.toBe("第一章：抵达");
  });

  it("requests manual paste when clipboard access is missing or denied", async () => {
    await expect(readClipboardText(undefined)).resolves.toBeNull();
    await expect(readClipboardText(async () => {
      throw new DOMException("denied", "NotAllowedError");
    })).resolves.toBeNull();
  });
});
