import type { Character, Fragment } from "./api/types";

export interface FragmentBoardPoint {
  x: number;
  y: number;
}

export interface FragmentBoardViewport extends FragmentBoardPoint {
  scale: number;
}

export interface FragmentBoardLayoutState {
  version: 7;
  nodes: Record<string, FragmentBoardPoint>;
  viewport: FragmentBoardViewport;
  frontId?: string;
}

export type FragmentBoardRelationKind = "structure" | "reference" | "person" | "tag";

export interface FragmentBoardEdge {
  id: string;
  fromId: string;
  toId: string;
  kinds: FragmentBoardRelationKind[];
  labels: string[];
  arrows: Array<"forward" | "reverse">;
  focusOnly: boolean;
}

// The DOM hit area remains comfortably clickable while the visible graph dot is
// intentionally much smaller, like an Obsidian graph node.
export const FRAGMENT_BOARD_NODE_WIDTH = 44;
export const FRAGMENT_BOARD_NODE_HEIGHT = 44;
export const FRAGMENT_BOARD_DEFAULT_VIEWPORT: FragmentBoardViewport = { x: 36, y: 36, scale: 1 };

function fragmentType(item: Fragment): "chapter" | "line" {
  return item.fragmentType === "line" || item.extra?.fragmentType === "line" ? "line" : "chapter";
}

function fragmentParent(item: Fragment): string | null {
  const value = item.parentFragmentId ?? item.extra?.parentFragmentId;
  return typeof value === "string" && value ? value : null;
}

function fragmentChapter(item: Fragment): number | null {
  const value = item.chapterNumber ?? item.extra?.chapterNumber;
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
}

function fragmentOrder(item: Fragment): number {
  const value = item.fragmentOrder ?? item.extra?.fragmentOrder;
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function stableEntitySort(left: Fragment, right: Fragment): number {
  return left.id.localeCompare(right.id, undefined, { numeric: true })
    || left.entityId.localeCompare(right.entityId, undefined, { numeric: true });
}

function stableHash(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function isDistinctiveFragmentAffinity(groupSize: number, fragmentCount: number): boolean {
  if (groupSize < 2) return false;
  // In a small board every shared person can still be useful. Once the project
  // grows, a person present in nearly half the fragments behaves like a common
  // word: it describes the whole novel rather than a meaningful local cluster.
  if (fragmentCount >= 8 && groupSize >= 6 && groupSize / fragmentCount >= .45) return false;
  return true;
}

export function defaultFragmentBoardPositions(items: Fragment[]): Map<string, FragmentBoardPoint> {
  if (!items.length) return new Map();
  const ordered = [...items].sort(stableEntitySort);
  const indexById = new Map(ordered.map((item, index) => [item.entityId, index]));
  const lines = items.filter((item) => fragmentType(item) === "line").sort(stableEntitySort);
  const lineIds = new Set(lines.map((item) => item.entityId));
  const children = new Map<string, Fragment[]>();
  for (const item of items) {
    const parent = fragmentParent(item);
    if (!parent || !lineIds.has(parent) || fragmentType(item) !== "chapter") continue;
    children.set(parent, [...(children.get(parent) || []), item]);
  }
  for (const values of children.values()) {
    values.sort((left, right) =>
      (fragmentChapter(left) ?? Number.MAX_SAFE_INTEGER) - (fragmentChapter(right) ?? Number.MAX_SAFE_INTEGER)
      || fragmentOrder(left) - fragmentOrder(right)
      || stableEntitySort(left, right)
    );
  }
  const springs: Array<{ left: number; right: number; length: number; strength: number }> = [];
  const springKeys = new Set<string>();
  const addSpring = (leftId: string, rightId: string, length: number, strength: number) => {
    const left = indexById.get(leftId);
    const right = indexById.get(rightId);
    if (left === undefined || right === undefined || left === right) return;
    const key = left < right ? `${left}|${right}` : `${right}|${left}`;
    if (springKeys.has(key)) return;
    springKeys.add(key);
    springs.push({ left, right, length, strength });
  };
  for (const line of lines) {
    const lineChildren = children.get(line.entityId) || [];
    if (lineChildren[0]) addSpring(line.entityId, lineChildren[0].entityId, 108, .024);
    for (let index = 1; index < lineChildren.length; index += 1) {
      addSpring(lineChildren[index - 1].entityId, lineChildren[index].entityId, 98, .027);
    }
  }
  for (const item of ordered) {
    for (const reference of item.references || []) {
      if (indexById.has(reference)) addSpring(item.entityId, reference, 154, .011);
    }
  }

  // Fragments rarely link directly to one another. Shared people and tags are
  // therefore used as weak springs so the default layout forms useful clusters
  // instead of an arbitrary cloud. Connecting neighbours rather than creating a
  // full clique keeps large projects legible and the layout cost bounded.
  const affinityGroups = new Map<string, Fragment[]>();
  for (const item of ordered) {
    const keys = [
      ...(item.references || []).filter((reference) => !indexById.has(reference)).map((reference) => `reference:${reference}`),
      ...item.tags.map((tag) => `tag:${tag}`),
    ];
    for (const key of new Set(keys)) affinityGroups.set(key, [...(affinityGroups.get(key) || []), item]);
  }
  for (const [key, group] of affinityGroups) {
    const related = [...group].sort(stableEntitySort);
    if (key.startsWith("reference:") && !isDistinctiveFragmentAffinity(related.length, items.length)) continue;
    for (let index = 1; index < related.length; index += 1) {
      addSpring(
        related[index - 1].entityId,
        related[index].entityId,
        key.startsWith("tag:") ? 148 : 124,
        key.startsWith("tag:") ? .007 : .011,
      );
    }
  }

  const degrees = new Array(ordered.length).fill(0);
  springs.forEach((spring) => { degrees[spring.left] += 1; degrees[spring.right] += 1; });
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  const center = { x: 760, y: 560 };
  const points = ordered.map((item, index) => {
    const hash = stableHash(item.entityId);
    const angle = index * goldenAngle + (hash % 1000) / 1000 * .72;
    const baseRadius = 76 + Math.sqrt(index + 1) * 66;
    const radius = fragmentType(item) === "line" ? baseRadius * .52 : baseRadius;
    return {
      x: center.x + Math.cos(angle) * radius,
      y: center.y + Math.sin(angle) * radius * .76,
      vx: 0,
      vy: 0,
    };
  });

  for (let iteration = 0; iteration < 260; iteration += 1) {
    const forces = ordered.map(() => ({ x: 0, y: 0 }));
    for (let left = 0; left < points.length; left += 1) {
      for (let right = left + 1; right < points.length; right += 1) {
        const deltaX = points[right].x - points[left].x;
        const deltaY = points[right].y - points[left].y;
        const distance = Math.max(8, Math.hypot(deltaX, deltaY));
        const unitX = deltaX / distance;
        const unitY = deltaY / distance;
        const collision = Math.max(0, 48 - distance) * .22;
        const repulsion = 2900 / (distance * distance) + collision;
        forces[left].x -= unitX * repulsion;
        forces[left].y -= unitY * repulsion;
        forces[right].x += unitX * repulsion;
        forces[right].y += unitY * repulsion;
      }
    }
    for (const spring of springs) {
      const left = points[spring.left];
      const right = points[spring.right];
      const deltaX = right.x - left.x;
      const deltaY = right.y - left.y;
      const distance = Math.max(1, Math.hypot(deltaX, deltaY));
      const pull = (distance - spring.length) * spring.strength;
      const forceX = deltaX / distance * pull;
      const forceY = deltaY / distance * pull;
      forces[spring.left].x += forceX;
      forces[spring.left].y += forceY;
      forces[spring.right].x -= forceX;
      forces[spring.right].y -= forceY;
    }
    points.forEach((point, index) => {
      const gravity = degrees[index] ? .0032 : .0012;
      forces[index].x += (center.x - point.x) * gravity;
      forces[index].y += (center.y - point.y) * gravity;
      point.vx = (point.vx + forces[index].x) * .76;
      point.vy = (point.vy + forces[index].y) * .76;
      const speed = Math.max(1, Math.hypot(point.vx, point.vy));
      const limit = Math.max(2.2, 13 * (1 - iteration / 300));
      if (speed > limit) {
        point.vx = point.vx / speed * limit;
        point.vy = point.vy / speed * limit;
      }
      point.x += point.vx;
      point.y += point.vy;
    });
  }

  const minX = Math.min(...points.map((point) => point.x));
  const minY = Math.min(...points.map((point) => point.y));
  return new Map(ordered.map((item, index) => [item.entityId, {
    x: Math.round((points[index].x - minX + 72) * 10) / 10,
    y: Math.round((points[index].y - minY + 72) * 10) / 10,
  }]));
}

interface MutableEdge {
  fromId: string;
  toId: string;
  kinds: Set<FragmentBoardRelationKind>;
  labels: Set<string>;
  arrows: Set<"forward" | "reverse">;
}

function pair(left: string, right: string): [string, string] {
  return left.localeCompare(right) <= 0 ? [left, right] : [right, left];
}

export function fragmentBoardEdges(
  fragments: Fragment[],
  characters: Array<Pick<Character, "entityId" | "name">>,
  selectedId: string | null,
): FragmentBoardEdge[] {
  const fragmentsById = new Map(fragments.map((item) => [item.entityId, item]));
  const characterNames = new Map(characters.map((item) => [item.entityId, item.name]));
  const edges = new Map<string, MutableEdge>();
  const add = (
    source: string,
    target: string,
    kind: FragmentBoardRelationKind,
    labels: string[],
    directed = false,
  ) => {
    if (source === target || !fragmentsById.has(source) || !fragmentsById.has(target)) return;
    const [fromId, toId] = pair(source, target);
    const id = `${fromId}|${toId}`;
    const edge = edges.get(id) || {
      fromId,
      toId,
      kinds: new Set<FragmentBoardRelationKind>(),
      labels: new Set<string>(),
      arrows: new Set<"forward" | "reverse">(),
    };
    edge.kinds.add(kind);
    labels.filter(Boolean).forEach((label) => edge.labels.add(label));
    if (directed) edge.arrows.add(source === fromId ? "forward" : "reverse");
    edges.set(id, edge);
  };

  const lines = fragments.filter((fragment) => fragmentType(fragment) === "line").sort(stableEntitySort);
  for (const line of lines) {
    const chapters = fragments.filter((fragment) =>
      fragmentType(fragment) === "chapter" && fragmentParent(fragment) === line.entityId
    ).sort((left, right) =>
      (fragmentChapter(left) ?? Number.MAX_SAFE_INTEGER) - (fragmentChapter(right) ?? Number.MAX_SAFE_INTEGER)
      || fragmentOrder(left) - fragmentOrder(right)
      || stableEntitySort(left, right)
    );
    if (chapters[0]) add(line.entityId, chapters[0].entityId, "structure", ["剧情线入口"]);
    for (let index = 1; index < chapters.length; index += 1) {
      add(chapters[index - 1].entityId, chapters[index].entityId, "structure", ["章节顺序"]);
    }
  }

  for (const fragment of fragments) {
    for (const reference of fragment.references || []) {
      if (fragmentsById.has(reference)) add(fragment.entityId, reference, "reference", ["明确引用"], true);
    }
  }

  const connectAffinityGroup = (
    group: Fragment[],
    kind: "person" | "tag",
    label: string,
  ) => {
    const ordered = [...group].sort(stableEntitySort);
    for (let index = 1; index < ordered.length; index += 1) {
      add(ordered[index - 1].entityId, ordered[index].entityId, kind, [label]);
    }
    // A second sparse strand gives large clusters the woven, connected feel of
    // a knowledge graph without exploding into every possible pair.
    if (ordered.length >= 5) {
      for (let index = 2; index < ordered.length; index += 2) {
        add(ordered[index - 2].entityId, ordered[index].entityId, kind, [label]);
      }
    }
  };

  const distinctiveCharacterIds = new Set<string>();
  for (const [characterId, characterName] of characterNames) {
    const group = fragments.filter((fragment) => (fragment.references || []).includes(characterId));
    if (!isDistinctiveFragmentAffinity(group.length, fragments.length)) continue;
    distinctiveCharacterIds.add(characterId);
    connectAffinityGroup(group, "person", `人物：${characterName}`);
  }
  const allTags = [...new Set(fragments.flatMap((fragment) => fragment.tags))].sort();
  for (const tag of allTags) {
    const group = fragments.filter((fragment) => fragment.tags.includes(tag));
    if (group.length > 1) connectAffinityGroup(group, "tag", `标签：${tag}`);
  }

  const selected = selectedId ? fragmentsById.get(selectedId) : undefined;
  if (selected) {
    const selectedPeople = new Set((selected.references || []).filter((id) => distinctiveCharacterIds.has(id)));
    const selectedTags = new Set(selected.tags);
    for (const candidate of fragments) {
      if (candidate.entityId === selected.entityId) continue;
      const sharedPeople = [...new Set((candidate.references || []).filter((id) => selectedPeople.has(id)))]
        .map((id) => characterNames.get(id) || id);
      const sharedTags = [...new Set(candidate.tags.filter((tag) => selectedTags.has(tag)))];
      if (sharedPeople.length) {
        add(selected.entityId, candidate.entityId, "person", [`人物：${sharedPeople.join("、")}`]);
      }
      if (sharedTags.length) {
        add(selected.entityId, candidate.entityId, "tag", [`标签：${sharedTags.join("、")}`]);
      }
    }
  }

  const kindOrder: FragmentBoardRelationKind[] = ["structure", "reference", "person", "tag"];
  return [...edges].sort(([left], [right]) => left.localeCompare(right)).map(([id, edge]) => ({
    id,
    fromId: edge.fromId,
    toId: edge.toId,
    kinds: kindOrder.filter((kind) => edge.kinds.has(kind)),
    labels: [...edge.labels],
    arrows: [...edge.arrows],
    focusOnly: !edge.kinds.has("structure") && !edge.kinds.has("reference"),
  }));
}

function finite(value: unknown, fallback: number): number {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function cleanPoint(value: unknown): FragmentBoardPoint | null {
  if (!value || typeof value !== "object") return null;
  const point = value as Partial<FragmentBoardPoint>;
  const x = finite(point.x, Number.NaN);
  const y = finite(point.y, Number.NaN);
  if (!Number.isFinite(x) || !Number.isFinite(y) || Math.abs(x) > 1_000_000 || Math.abs(y) > 1_000_000) return null;
  return { x, y };
}

export function fragmentBoardStorageKey(pathname: string, project: string): string {
  return `story-teller:fragment-board:v7:${encodeURIComponent(pathname)}:${encodeURIComponent(project)}`;
}

export function parseFragmentBoardLayout(raw: string | null, validIds: Set<string>): FragmentBoardLayoutState | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<FragmentBoardLayoutState>;
    if (value.version !== 7 || !value.nodes || typeof value.nodes !== "object") return null;
    const nodes: Record<string, FragmentBoardPoint> = {};
    for (const [id, point] of Object.entries(value.nodes)) {
      const clean = validIds.has(id) ? cleanPoint(point) : null;
      if (clean) nodes[id] = clean;
    }
    const rawViewport = value.viewport;
    const viewport = rawViewport && typeof rawViewport === "object" ? {
      x: finite(rawViewport.x, FRAGMENT_BOARD_DEFAULT_VIEWPORT.x),
      y: finite(rawViewport.y, FRAGMENT_BOARD_DEFAULT_VIEWPORT.y),
      scale: Math.max(.18, Math.min(2.5, finite(rawViewport.scale, FRAGMENT_BOARD_DEFAULT_VIEWPORT.scale))),
    } : { ...FRAGMENT_BOARD_DEFAULT_VIEWPORT };
    const frontId = typeof value.frontId === "string" && validIds.has(value.frontId)
      ? value.frontId
      : undefined;
    return { version: 7, nodes, viewport, frontId };
  } catch {
    return null;
  }
}

export function reconcileFragmentBoardPositions(
  defaults: Map<string, FragmentBoardPoint>,
  stored: FragmentBoardLayoutState | null,
  items: Fragment[] = [],
): Map<string, FragmentBoardPoint> {
  const result = new Map<string, FragmentBoardPoint>();
  const itemsById = new Map(items.map((item) => [item.entityId, item]));
  for (const [id] of defaults) {
    const point = stored?.nodes[id];
    if (point) result.set(id, point);
  }
  for (const [id, defaultPoint] of defaults) {
    if (result.has(id)) continue;
    let point = { ...defaultPoint };
    const item = itemsById.get(id);
    const parentId = item ? fragmentParent(item) : null;
    const parentPoint = parentId ? result.get(parentId) : null;
    const defaultParentPoint = parentId ? defaults.get(parentId) : null;
    if (parentPoint && defaultParentPoint) {
      point = {
        x: point.x + parentPoint.x - defaultParentPoint.x,
        y: point.y + parentPoint.y - defaultParentPoint.y,
      };
    }
    while ([...result.values()].some((occupied) =>
      Math.abs(occupied.x - point.x) < FRAGMENT_BOARD_NODE_WIDTH + 20
      && Math.abs(occupied.y - point.y) < FRAGMENT_BOARD_NODE_HEIGHT + 20
    )) {
      point = { x: point.x + FRAGMENT_BOARD_NODE_WIDTH + 34, y: point.y };
    }
    result.set(id, point);
  }
  return result;
}

export function serializeFragmentBoardLayout(
  positions: Map<string, FragmentBoardPoint>,
  viewport: FragmentBoardViewport,
  frontId?: string | null,
): string {
  return JSON.stringify({
    version: 7,
    nodes: Object.fromEntries([...positions].sort(([left], [right]) => left.localeCompare(right))),
    viewport: {
      x: finite(viewport.x, FRAGMENT_BOARD_DEFAULT_VIEWPORT.x),
      y: finite(viewport.y, FRAGMENT_BOARD_DEFAULT_VIEWPORT.y),
      scale: Math.max(.18, Math.min(2.5, finite(viewport.scale, FRAGMENT_BOARD_DEFAULT_VIEWPORT.scale))),
    },
    ...(frontId && positions.has(frontId) ? { frontId } : {}),
  } satisfies FragmentBoardLayoutState);
}

export function fragmentBoardBounds(positions: Map<string, FragmentBoardPoint>) {
  if (!positions.size) return { minX: 0, minY: 0, maxX: FRAGMENT_BOARD_NODE_WIDTH, maxY: FRAGMENT_BOARD_NODE_HEIGHT };
  const points = [...positions.values()];
  return {
    minX: Math.min(...points.map((point) => point.x)),
    minY: Math.min(...points.map((point) => point.y)),
    maxX: Math.max(...points.map((point) => point.x + FRAGMENT_BOARD_NODE_WIDTH)),
    maxY: Math.max(...points.map((point) => point.y + FRAGMENT_BOARD_NODE_HEIGHT)),
  };
}
