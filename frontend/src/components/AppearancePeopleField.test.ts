import { describe, expect, it } from "vitest";
import type { Character } from "../api/types";
import { detectedCharacterIds, missingAppearanceNames } from "./AppearancePeopleField";

function character(entityId: string, name: string, aliases: string[] = []): Character {
  return {
    entityId,
    id: entityId,
    name,
    aliases,
    markers: [],
    facts: {},
    supplements: [],
    narrativeRole: "配角",
    characterScope: "常驻人物",
    side: "中立",
    mainPlotImpact: 0,
    color: "#3f7fc1",
    gradient: "",
    group: "",
    graphVisible: true,
    revision: 1,
    introPreview: "",
    extra: {},
  };
}

describe("appearance people", () => {
  it("detects known names and aliases in the current text", () => {
    const characters = [
      character("character:1", "沈清妙", ["清妙"]),
      character("character:2", "黎清妍"),
    ];
    expect(detectedCharacterIds(characters, "清妙把文件交给黎清妍。")).toEqual([
      "character:1",
      "character:2",
    ]);
  });

  it("requires an explicit id when a matched term belongs to duplicate people", () => {
    const characters = [
      character("character:1", "周明"),
      character("character:2", "周明"),
    ];
    expect(detectedCharacterIds(characters, "周明来到门口。")).toEqual([]);
    expect(detectedCharacterIds(characters, "周明来到门口。", ["character:2"])).toEqual([
      "character:2",
    ]);
  });

  it("reports manually entered names that are no longer in the text", () => {
    expect(missingAppearanceNames(["顾闻川", "周既明"], "顾闻川推开门。")).toEqual(["周既明"]);
  });
});
