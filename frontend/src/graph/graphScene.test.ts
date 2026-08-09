import { describe, expect, it } from "vitest";
import type { Character, Entry, Relationship } from "../api/types";
import { createGraphScene, graphMotionProgress, graphScenePoint, hitTestGraphNode, organizationRingColors, organizationRingGeometry, organizationRingLabel } from "./graphScene";

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
    color: "#4f6fae",
    gradient: "",
    group: "",
    graphVisible: true,
    revision: 1,
    introPreview: "",
    extra: {},
  };
}

const organization = {
  entityId: "entry:family",
  id: "entry:family",
  name: "卡斯特罗家族",
  type: "组织",
  accent: "#8c5fa8",
  members: [{ characterId: "a", role: "家主", status: "" }, { characterId: "b", role: "女儿", status: "" }],
} as Entry;

describe("GraphScene", () => {
  it("projects relationships and organizations into one coordinate scene", () => {
    const characters = [character("a"), character("b")];
    const points = new Map([["a", { x: 120, y: 180 }], ["b", { x: 360, y: 180 }]]);
    const relationship = { entityId: "relationship:a__b", from: "a", to: "b", graphScope: "core", label: "家人" } as Relationship;
    const scene = createGraphScene(800, 600, { x: 0, y: 0, scale: 1 }, characters, points, [relationship], [organization], null);

    expect(scene.nodes.map((node) => node.point)).toEqual([{ x: 120, y: 180 }, { x: 360, y: 180 }]);
    expect(scene.relationships).toEqual([relationship]);
    expect(scene.nodes[0].organizationRings).toEqual([expect.objectContaining({
      organizationId: "entry:family",
      organizationName: "卡斯特罗家族",
      role: "家主",
      color: "#8c5fa8",
      radiusIndex: 0,
    })]);
    expect(scene.nodes[1].organizationRings[0].role).toBe("女儿");
  });

  it("keeps organization rings stable and caps visible rings with an explicit overflow label", () => {
    const characters = [character("a")];
    const organizations = ["family", "gang", "company", "club"].map((id, index) => ({
      ...organization,
      entityId: `entry:${id}`,
      id: `entry:${id}`,
      name: id,
      accent: ["#8c5fa8", "#b45f75", "#5d8f7b", "#b06f42"][index],
      members: [{ characterId: "a", role: `身份${index + 1}`, status: "" }],
    } as Entry));
    const scene = createGraphScene(800, 600, { x: 0, y: 0, scale: 1 }, characters, new Map([["a", { x: 120, y: 180 }]]), [], organizations, null);

    expect(scene.nodes[0].organizationRings).toHaveLength(3);
    expect(scene.nodes[0].organizationOverflow).toBe(1);
    expect(scene.nodes[0].organizationRings.map((ring) => ring.radiusIndex)).toEqual([0, 1, 2]);
    expect(organizationRingLabel({ name: "卡斯特罗家族" }, { role: "家主" })).toBe("卡斯特罗家族 · 家主");
    expect(organizationRingLabel({ name: "卡斯特罗家族" }, { role: "" })).toBe("卡斯特罗家族");
    expect(organizationRingGeometry(2).radius).toBeGreaterThan(organizationRingGeometry(1).radius);
    expect(organizationRingGeometry(0)).toEqual({ radius: 49 });
    expect(organizationRingGeometry(1)).toEqual({ radius: 66 });
  });

  it("assigns distinct stable ring colors when organizations share the same accent", () => {
    const organizations = [
      { entityId: "entry:family", accent: "#8c5fa8" },
      { entityId: "entry:gang", accent: "#8c5fa8" },
    ];
    const first = organizationRingColors(organizations);
    const second = organizationRingColors([...organizations].reverse());

    expect(new Set(first.values()).size).toBe(2);
    expect([...first]).toEqual([...second]);
  });

  it("uses the same viewport conversion for hit testing and pointer coordinates", () => {
    const characters = [character("a")];
    const scene = createGraphScene(800, 600, { x: 40, y: 30, scale: 2 }, characters, new Map([["a", { x: 100, y: 120 }]]), [], [], null);
    const bounds = { left: 10, top: 20 } as DOMRect;
    const screenPoint = { clientX: 250, clientY: 290 };
    const worldPoint = graphScenePoint(scene, screenPoint.clientX, screenPoint.clientY, bounds);

    expect(worldPoint).toEqual({ x: 100, y: 120 });
    expect(hitTestGraphNode(scene, worldPoint)?.character.entityId).toBe("a");
  });

  it("moves lightweight particles forward or backward along one repeatable cycle", () => {
    expect(graphMotionProgress(600)).toBeCloseTo(.25);
    expect(graphMotionProgress(600, 0, true)).toBeCloseTo(.75);
    expect(graphMotionProgress(3000)).toBeCloseTo(.25);
  });
});
