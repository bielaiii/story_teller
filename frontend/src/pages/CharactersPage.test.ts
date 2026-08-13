import { describe, expect, it } from "vitest";
import type { Character } from "../api/types";
import {
  displayRole,
  graphVisibilityAfterRole,
  graphVisibilityAfterScope,
  orderCharactersForList,
  personaItemKey,
  relationshipImpressionFor,
  storedClassification,
} from "./CharactersPage";

function character(name: string, entityId: string): Character {
  return { name, entityId } as Character;
}

describe("orderCharactersForList", () => {
  it("pins the three central characters and preserves the order of everyone else", () => {
    const characters = [
      character("陆沉舟", "character:2"),
      character("姜昭妍", "character:8"),
      character("林越", "character:3"),
      character("黎清妍", "character:4"),
      character("沈清妙", "character:1"),
      character("刘浩", "character:9"),
    ];

    expect(orderCharactersForList(characters).map((item) => item.name)).toEqual([
      "沈清妙",
      "黎清妍",
      "姜昭妍",
      "陆沉舟",
      "林越",
      "刘浩",
    ]);
  });
});

describe("directional relationship impressions", () => {
  const relationship = {
    from: "character:vito",
    to: "character:selena",
    fromImpression: "认为女儿有商业天赋，但不该接触地下事务。",
    toImpression: "敬爱父亲，同时不认同他的犯罪方式。",
  };

  it("shows the impression owned by the currently viewed endpoint", () => {
    expect(relationshipImpressionFor(relationship, "character:vito")).toContain("商业天赋");
    expect(relationshipImpressionFor(relationship, "character:selena")).toContain("不认同");
    expect(relationshipImpressionFor(relationship, "character:other")).toBe("");
  });
});

describe("persona list identity", () => {
  it("keeps value-only rows unique and remounts them when the selected character changes", () => {
    expect(personaItemKey("character:widow", "core", 0)).not.toBe(personaItemKey("character:widow", "core", 1));
    expect(personaItemKey("character:widow", "core", 0)).not.toBe(personaItemKey("character:vito", "core", 0));
    expect(personaItemKey("character:widow", "core", 0)).not.toBe(personaItemKey("character:widow", "supplement", 0));
  });
});

describe("character role presentation", () => {
  it("combines the legacy role and side fields into one visible role", () => {
    expect(displayRole({ narrativeRole: "主角", side: "主角方" })).toBe("主角");
    expect(displayRole({ narrativeRole: "配角", side: "反派方" })).toBe("反派");
    expect(displayRole({ narrativeRole: "配角", side: "中立" })).toBe("中立");
    expect(displayRole({ narrativeRole: "配角", side: "主角方" })).toBe("配角");
  });

  it("converts the visible role back to compatible persisted fields", () => {
    expect(storedClassification("反派")).toEqual({ narrativeRole: "配角", side: "反派方" });
    expect(storedClassification("中立")).toEqual({ narrativeRole: "配角", side: "中立" });
  });

  it("applies graph defaults without preventing a later manual choice", () => {
    expect(graphVisibilityAfterRole(false, "主角")).toBe(true);
    expect(graphVisibilityAfterRole(false, "反派")).toBe(true);
    expect(graphVisibilityAfterRole(false, "中立")).toBe(true);
    expect(graphVisibilityAfterRole(false, "配角")).toBe(false);
    expect(graphVisibilityAfterScope(true, "一次性角色")).toBe(false);
    expect(graphVisibilityAfterScope(true, "待定角色")).toBe(false);
    expect(graphVisibilityAfterScope(true, "常驻人物")).toBe(true);
  });
});
