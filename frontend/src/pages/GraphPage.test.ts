import { describe, expect, it } from "vitest";
import type { Character, GraphData } from "../api/types";
import { advanceFollowerSpring, graphLayout, quadraticPoint } from "./GraphPage";

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
  it("moves relationship particles along the same quadratic curve as the edge", () => {
    expect(quadraticPoint({ x: 0, y: 0 }, { x: 50, y: 100 }, { x: 100, y: 0 }, .5)).toEqual({ x: 50, y: 50 });
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

  it("keeps follower return slow, non-bouncy, and stable across frame rates", () => {
    const simulate = (framesPerSecond: number, seconds: number) => {
      let point = { x: 0, y: 0 };
      let velocity = { x: 0, y: 0 };
      let maximum = point.x;
      for (let frame = 0; frame < framesPerSecond * seconds; frame += 1) {
        const next = advanceFollowerSpring(point, velocity, { x: 100, y: 0 }, 1 / framesPerSecond, false);
        point = next.point;
        velocity = next.velocity;
        maximum = Math.max(maximum, point.x);
      }
      return { point, maximum };
    };

    const lowRate = simulate(20, 1);
    const highRate = simulate(60, 1);
    expect(Math.abs(lowRate.point.x - highRate.point.x)).toBeLessThan(4);
    expect(highRate.point.x).toBeGreaterThan(45);
    expect(highRate.point.x).toBeLessThan(55);
    expect(simulate(60, 6).maximum).toBeLessThanOrEqual(100);
  });
});
