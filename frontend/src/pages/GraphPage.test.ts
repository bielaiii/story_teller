import { describe, expect, it } from "vitest";
import type { Character, GraphData, Relationship } from "../api/types";
import { effectiveGraphLineMode } from "../api/relationshipPresentation";
import { graphDragPoint, graphLayout, graphMotionFrameInterval, graphMotionIsActive, graphRelationshipLabels, graphRelationshipsForFocus, quadraticPoint, relationshipCurveLanes } from "./GraphPage";

function character(id: string): Character {
  return {
    entityId: id,
    id,
    name: id,
    aliases: [],
    markers: [],
    facts: {},
    supplements: [],
    narrativeRole: "配角",
    characterScope: "常驻人物",
    side: "中立",
    mainPlotImpact: 50,
    color: "#3f7fc1",
    gradient: "",
    group: "",
    graphVisible: true,
    revision: 1,
    introPreview: "",
    extra: {},
  };
}

describe("graphLayout", () => {
  it("runs motion only inside a short activity window and respects reduced motion", () => {
    expect(graphMotionIsActive(900, 1000)).toBe(true);
    expect(graphMotionIsActive(1000, 1000)).toBe(false);
    expect(graphMotionIsActive(900, 1000, true)).toBe(false);
    expect(graphMotionFrameInterval("idle")).toBeCloseTo(83.33, 1);
    expect(graphMotionFrameInterval("active")).toBeCloseTo(33.33, 1);
  });

  it("keeps core relations visible and reveals basic relations only for the focused person", () => {
    const relationships = [
      { entityId: "core", from: "a", to: "b", graphScope: "core" },
      { entityId: "family", from: "a", to: "c", graphScope: "focus" },
      { entityId: "impression", from: "a", to: "d", graphScope: "hidden" },
    ] as Relationship[];
    expect(graphRelationshipsForFocus(relationships, null).map((item) => item.entityId)).toEqual(["core"]);
    expect(graphRelationshipsForFocus(relationships, "a").map((item) => item.entityId)).toEqual(["core", "family"]);
    expect(graphRelationshipsForFocus(relationships, "d").map((item) => item.entityId)).toEqual(["core"]);
  });

  it("moves relationship particles along the same quadratic curve as the edge", () => {
    expect(quadraticPoint({ x: 0, y: 0 }, { x: 50, y: 100 }, { x: 100, y: 0 }, .5)).toEqual({ x: 50, y: 50 });
  });

  it("renders shared relationships as one lane and differing viewpoints as two directional lanes", () => {
    const from = { x: 0, y: 0 };
    const to = { x: 100, y: 0 };
    const shared = relationshipCurveLanes(from, to, "single");
    const directional = relationshipCurveLanes(from, to, "double");

    expect(shared).toHaveLength(1);
    expect(shared[0].direction).toBe("shared");
    expect(directional.map((lane) => lane.direction)).toEqual(["forward", "reverse"]);
    expect(directional[0].control.y).toBeGreaterThan(0);
    expect(directional[1].control.y).toBeLessThan(0);
  });

  it("uses one shared name for a single line and endpoint roles for double lines", () => {
    expect(graphRelationshipLabels({ label: "互相试探", type: "盟友", graphLineMode: "single" } as Relationship)).toEqual(["互相试探"]);
    expect(graphRelationshipLabels({ label: "家庭关系", type: "亲属", fromRole: "父亲", toRole: "女儿", graphLineMode: "double" } as Relationship)).toEqual(["父亲", "女儿"]);
    expect(graphRelationshipLabels({ fromImpression: "认可对方，但不愿完全信任。", toImpression: "觉得对方过于危险，必须保持距离。", fromRole: "盟友", toRole: "盟友", graphLineMode: "double" } as Relationship)).toEqual(["认可对方，但不愿完全信任。", "觉得对方过于危险，必须保持距离。"]);
    expect(graphRelationshipLabels({ fromImpression: "只有一方留下印象", label: "互相试探", graphLineMode: "double" } as Relationship)).toEqual(["只有一方留下印象", "互相试探"]);
    expect(graphRelationshipLabels({ fromImpression: "宠溺", toImpression: "依赖", fromRole: "家主", toRole: "女儿", graphLineMode: "double" } as Relationship, false)).toEqual(["家主", "女儿"]);
    expect(graphRelationshipLabels({ graphLineMode: "double" } as Relationship)).toEqual(["关系", "关系"]);
    expect(graphRelationshipLabels({ fromImpression: "", toImpression: "", label: "", type: "" } as Relationship)).toEqual([]);
    expect(graphRelationshipLabels({ label: "", type: "盟友", graphLineMode: "single" } as Relationship)).toEqual(["盟友"]);
    expect(effectiveGraphLineMode({ graphLineMode: "single", fromImpression: "宠溺", toImpression: "依赖" })).toBe("double");
  });

  it("treats migrated 0–100 saved positions as viewport percentages", () => {
    const characters = [character("character:1"), character("character:2"), character("character:3")];
    const graph: GraphData = {
      settings: { node_spacing: 120 },
      nodes: characters.map((item, index) => ({
        character_id: item.entityId,
        orbit_of: null,
        orbit_distance: null,
        orbit_angle: null,
        strength: null,
        anchor_x: [10, 50, 90][index],
        anchor_y: 50,
      })),
      distances: [],
      clusters: [{ id: "legacy", label: "旧版", centerX: 50, centerY: 50, radius: 200, strength: 1, members: characters.map((item) => item.entityId) }],
    };

    const points = graphLayout(1000, 800, characters, graph, []);
    expect(points.get("character:1")).toEqual({ x: 100, y: 400 });
    expect(points.get("character:2")).toEqual({ x: 500, y: 400 });
    expect(points.get("character:3")).toEqual({ x: 900, y: 400 });
  });

  it("uses the explicit graph choice even for one-time characters", () => {
    const visibleOneOff = { ...character("character:one-off"), characterScope: "一次性角色" as const };
    const hiddenRegular = { ...character("character:hidden"), graphVisible: false };
    const points = graphLayout(800, 600, [visibleOneOff, hiddenRegular], {
      settings: {},
      nodes: [],
      distances: [],
      clusters: [],
    }, []);

    expect(points.has(visibleOneOff.entityId)).toBe(true);
    expect(points.has(hiddenRegular.entityId)).toBe(false);
  });

  it("uses the visible panned viewport as the node drag boundary", () => {
    expect(graphDragPoint(
      { x: 1400, y: 400 },
      1280,
      800,
      { x: -300, y: 0, scale: 1 },
    )).toEqual({ x: 1400, y: 400 });
    expect(graphDragPoint(
      { x: 1700, y: 400 },
      1280,
      800,
      { x: -300, y: 0, scale: 1 },
    ).x).toBe(1516);
  });

  it("preserves an explicitly dragged point outside the initial layout width", () => {
    const person = character("character:vera");
    const points = graphLayout(1000, 700, [person], {
      settings: {},
      nodes: [{
        character_id: person.entityId,
        orbit_of: null,
        orbit_distance: null,
        orbit_angle: null,
        strength: null,
        anchor_x: 1300,
        anchor_y: 350,
      }],
      distances: [],
      clusters: [],
    }, []);

    expect(points.get(person.entityId)).toEqual({ x: 1300, y: 350 });
  });

});
