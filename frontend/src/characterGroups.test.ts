import { describe, expect, it } from "vitest";
import { groupCharactersBySideAndTags, type CharacterListItem } from "./characterGroups";

function character(
  entityId: string,
  name: string,
  side: CharacterListItem["side"],
  markers: string[],
): CharacterListItem {
  return { entityId, name, side, markers };
}

describe("character groups", () => {
  it("orders sides and nests characters through every tag level", () => {
    const result = groupCharactersBySideAndTags([
      character("neutral", "中立者", "中立", ["津海", "商界"]),
      character("villain-b", "乙反派", "反派方", ["津海", "商界", "核心", "长期"]),
      character("hero", "正派", "主角方", ["津海", "警界"]),
      character("villain-a", "甲反派", "反派方", ["津海", "商界", "外围"]),
    ]);

    expect(result.map((group) => group.label)).toEqual(["正派", "反派", "中立"]);
    const villainRoot = result[1].groups[0];
    expect(villainRoot.label).toBe("津海");
    expect(villainRoot.children[0].label).toBe("商界");
    expect(villainRoot.children[0].children.map((group) => group.label)).toEqual(["核心", "外围"]);
    expect(villainRoot.children[0].children[0].children[0].label).toBe("长期");
  });

  it("puts characters without tags in an explicit fallback group", () => {
    const result = groupCharactersBySideAndTags([
      character("untagged", "无标签人物", "主角方", []),
    ]);

    expect(result[0].groups[0].label).toBe("未标记");
    expect(result[0].groups[0].characters[0].name).toBe("无标签人物");
  });
});
