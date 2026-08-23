import { describe, expect, it } from "vitest";
import type { Fragment } from "./api/types";
import {
  defaultFragmentBoardPositions,
  fragmentBoardEdges,
  fragmentBoardStorageKey,
  parseFragmentBoardLayout,
  reconcileFragmentBoardPositions,
  serializeFragmentBoardLayout,
} from "./fragmentBoard";

function fragment(
  id: string,
  options: Partial<Fragment> = {},
): Fragment {
  return {
    entityId: `fragment:${id}`,
    id,
    title: id,
    status: "灵感",
    accent: "#7d6bd6",
    tags: [],
    bodyPreview: "",
    references: [],
    revision: 1,
    extra: {},
    ...options,
  };
}

describe("fragment board layout", () => {
  it("is deterministic and keeps force-directed chapter nodes from overlapping", () => {
    const line = fragment("line", { fragmentType: "line" });
    const later = fragment("later", { parentFragmentId: line.entityId, chapterNumber: 9 });
    const earlier = fragment("earlier", { parentFragmentId: line.entityId, chapterNumber: 2 });
    const first = defaultFragmentBoardPositions([later, line, earlier]);
    const second = defaultFragmentBoardPositions([earlier, later, line]);

    expect([...first]).toEqual([...second]);
    expect(Math.hypot(
      first.get(earlier.entityId)!.x - first.get(later.entityId)!.x,
      first.get(earlier.entityId)!.y - first.get(later.entityId)!.y,
    )).toBeGreaterThan(160);
  });

  it("uses stored positions, fills a free point for a new node, and drops deleted ids", () => {
    const one = fragment("one");
    const two = fragment("two");
    const defaults = defaultFragmentBoardPositions([one, two]);
    const firstPoint = defaults.get(one.entityId)!;
    const stored = parseFragmentBoardLayout(JSON.stringify({
      version: 5,
      nodes: {
        [one.entityId]: firstPoint,
        "fragment:deleted": { x: 10, y: 10 },
      },
      viewport: { x: 12, y: 23, scale: 1.2 },
    }), new Set([one.entityId, two.entityId]));
    const reconciled = reconcileFragmentBoardPositions(defaults, stored);

    expect(reconciled.has("fragment:deleted")).toBe(false);
    expect(reconciled.get(one.entityId)).toEqual(firstPoint);
    expect(reconciled.get(two.entityId)).toBeDefined();
  });

  it("places a newly added chapter beside its parent's moved cluster", () => {
    const line = fragment("line", { fragmentType: "line" });
    const chapter = fragment("chapter", { parentFragmentId: line.entityId, chapterNumber: 1 });
    const defaults = defaultFragmentBoardPositions([line, chapter]);
    const defaultLine = defaults.get(line.entityId)!;
    const defaultChapter = defaults.get(chapter.entityId)!;
    const stored = parseFragmentBoardLayout(JSON.stringify({
      version: 5,
      nodes: { [line.entityId]: { x: defaultLine.x + 480, y: defaultLine.y + 210 } },
      viewport: { x: 0, y: 0, scale: 1 },
    }), new Set([line.entityId, chapter.entityId]));

    expect(reconcileFragmentBoardPositions(defaults, stored, [line, chapter]).get(chapter.entityId)).toEqual({
      x: defaultChapter.x + 480,
      y: defaultChapter.y + 210,
    });
  });

  it("round-trips versioned local state and safely rejects damaged data", () => {
    const positions = new Map([["fragment:one", { x: 120, y: 240 }]]);
    const serialized = serializeFragmentBoardLayout(positions, { x: -20, y: 40, scale: 9 });
    const parsed = parseFragmentBoardLayout(serialized, new Set(["fragment:one"]));

    expect(fragmentBoardStorageKey("/w/demo/", "novel")).toContain("novel");
    expect(parsed?.nodes["fragment:one"]).toEqual({ x: 120, y: 240 });
    expect(parsed?.viewport.scale).toBe(2.5);
    expect(parseFragmentBoardLayout("{bad json", new Set())).toBeNull();
    expect(parseFragmentBoardLayout(JSON.stringify({ version: 4 }), new Set())).toBeNull();
  });
});

describe("fragment board relationships", () => {
  it("merges structure, explicit reference, shared people, and shared tags per pair", () => {
    const line = fragment("line", {
      fragmentType: "line",
      tags: ["复仇"],
      references: ["character:shen"],
    });
    const chapter = fragment("chapter", {
      parentFragmentId: line.entityId,
      chapterNumber: 1,
      tags: ["复仇"],
      references: [line.entityId, "character:shen"],
    });
    const edges = fragmentBoardEdges(
      [line, chapter],
      [{ entityId: "character:shen", name: "沈清妙" }],
      line.entityId,
    );

    expect(edges).toHaveLength(1);
    expect(edges[0].kinds).toEqual(["structure", "reference", "person", "tag"]);
    expect(edges[0].labels).toEqual(expect.arrayContaining([
      "剧情线入口",
      "明确引用",
      "人物：沈清妙",
      "标签：复仇",
    ]));
    expect(edges[0].arrows).toContain("forward");
    expect(edges[0].focusOnly).toBe(false);
  });

  it("keeps focus-only relations hidden until one node is selected", () => {
    const one = fragment("one", { tags: ["线索"], references: ["character:a"] });
    const two = fragment("two", { tags: ["线索"], references: ["character:a"] });

    expect(fragmentBoardEdges([one, two], [{ entityId: "character:a", name: "阿芜" }], null)).toEqual([]);
    expect(fragmentBoardEdges([one, two], [{ entityId: "character:a", name: "阿芜" }], one.entityId)[0]).toMatchObject({
      kinds: ["person", "tag"],
      focusOnly: true,
    });
  });

  it("exposes one story-line entry and chains every chapter in reading order", () => {
    const line = fragment("line", { fragmentType: "line" });
    const third = fragment("third", { parentFragmentId: line.entityId, chapterNumber: 3 });
    const first = fragment("first", { parentFragmentId: line.entityId, chapterNumber: 1 });
    const second = fragment("second", { parentFragmentId: line.entityId, chapterNumber: 2 });
    const edges = fragmentBoardEdges([line, third, first, second], [], null)
      .filter((edge) => edge.kinds.includes("structure"));
    const pairs = edges.map((edge) => new Set([edge.fromId, edge.toId]));

    expect(edges).toHaveLength(3);
    expect(pairs.some((pair) => pair.has(line.entityId) && pair.has(first.entityId))).toBe(true);
    expect(pairs.some((pair) => pair.has(first.entityId) && pair.has(second.entityId))).toBe(true);
    expect(pairs.some((pair) => pair.has(second.entityId) && pair.has(third.entityId))).toBe(true);
    expect(pairs.some((pair) => pair.has(line.entityId) && pair.has(third.entityId))).toBe(false);
  });
});
