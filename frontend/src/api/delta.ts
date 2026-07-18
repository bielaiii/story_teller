import type { MutationDelta, ProjectSnapshot } from "./types";

const bucketMap = {
  characters: "characters",
  plots: "plots",
  entries: "entries",
  fragments: "fragments",
  relationships: "relationships",
  chapters: "chapters",
} as const;

export function applyDelta(snapshot: ProjectSnapshot, delta: MutationDelta): ProjectSnapshot {
  const next: ProjectSnapshot = {
    ...snapshot,
    project: { ...snapshot.project, revision: delta.projectRevision },
  };
  for (const [bucket, target] of Object.entries(bucketMap) as Array<[keyof typeof bucketMap, (typeof bucketMap)[keyof typeof bucketMap]]>) {
    const existing = [...snapshot[target]] as Array<{ entityId: string }>;
    const removed = new Set(delta.removed[bucket] || []);
    const changed = (delta.changed[bucket] || []) as Array<{ entityId: string }>;
    const changedById = new Map(changed.map((item) => [item.entityId, item]));
    const values = existing
      .filter((item) => !removed.has(item.entityId))
      .map((item) => changedById.get(item.entityId) || item);
    for (const item of changed) {
      if (!existing.some((current) => current.entityId === item.entityId)) values.push(item);
    }
    (next[target] as unknown) = values;
  }
  next.characters.sort((left, right) => right.mainPlotImpact - left.mainPlotImpact || left.id.localeCompare(right.id));
  next.plots.sort((left, right) => left.sortKey.localeCompare(right.sortKey) || left.id.localeCompare(right.id));
  next.plots = next.plots.map((item, index) => ({ ...item, sequence: index + 1 }));
  next.entries.sort((left, right) => left.type.localeCompare(right.type, "zh-CN") || left.id.localeCompare(right.id));
  next.fragments.sort((left, right) => left.id.localeCompare(right.id));
  next.relationships.sort((left, right) => left.id.localeCompare(right.id));
  next.chapters.sort((left, right) => left.sortKey.localeCompare(right.sortKey));
  if (delta.structures?.timeline) {
    next.timeline = delta.structures.timeline;
  } else if (delta.changed.timelineLines || delta.removed.timelineLines) {
    const removed = new Set(delta.removed.timelineLines || []);
    const changed = (delta.changed.timelineLines || []) as unknown as ProjectSnapshot["timeline"]["lines"];
    const byId = new Map(changed.map((line) => [line.entityId, line]));
    next.timeline = {
      ...snapshot.timeline,
      lines: snapshot.timeline.lines
        .filter((line) => !removed.has(line.entityId))
        .map((line) => byId.get(line.entityId) || line),
    };
  }
  if (delta.structures?.graph) next.graph = delta.structures.graph;
  return next;
}
