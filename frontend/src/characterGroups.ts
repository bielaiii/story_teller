import type { Character } from "./api/types";

export type CharacterListItem = Pick<Character, "entityId" | "name" | "markers" | "side">;

export interface CharacterTagGroup<T extends CharacterListItem = CharacterListItem> {
  label: string;
  depth: number;
  characters: T[];
  children: CharacterTagGroup<T>[];
}

export interface CharacterSideGroup<T extends CharacterListItem = CharacterListItem> {
  side: Character["side"];
  label: string;
  groups: CharacterTagGroup<T>[];
}

const sideOrder: Array<{ side: Character["side"]; label: string }> = [
  { side: "主角方", label: "正派" },
  { side: "反派方", label: "反派" },
  { side: "中立", label: "中立" },
];

interface MutableTagGroup<T> {
  label: string;
  depth: number;
  characters: T[];
  children: Map<string, MutableTagGroup<T>>;
}

function freezeGroup<T extends CharacterListItem>(group: MutableTagGroup<T>): CharacterTagGroup<T> {
  return {
    label: group.label,
    depth: group.depth,
    characters: group.characters.sort((left, right) => left.name.localeCompare(right.name, "zh-CN")),
    children: [...group.children.values()]
      .sort((left, right) => left.label.localeCompare(right.label, "zh-CN"))
      .map(freezeGroup),
  };
}

export function groupCharactersBySideAndTags<T extends CharacterListItem>(characters: T[]): CharacterSideGroup<T>[] {
  return sideOrder.flatMap(({ side, label }) => {
    const roots = new Map<string, MutableTagGroup<T>>();
    for (const character of characters.filter((item) => item.side === side)) {
      const tags = [...new Set(character.markers.map((tag) => tag.trim()).filter(Boolean))];
      const path = tags.length ? tags : ["未标记"];
      let level = roots;
      for (const [index, tag] of path.entries()) {
        let group = level.get(tag);
        if (!group) {
          group = { label: tag, depth: index, characters: [], children: new Map() };
          level.set(tag, group);
        }
        if (index === path.length - 1) group.characters.push(character);
        level = group.children;
      }
    }
    if (!roots.size) return [];
    return [{
      side,
      label,
      groups: [...roots.values()]
        .sort((left, right) => left.label.localeCompare(right.label, "zh-CN"))
        .map(freezeGroup),
    }];
  });
}
