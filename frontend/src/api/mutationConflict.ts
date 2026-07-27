import type { ProjectSnapshot } from "./types";

export function mutationTargetId(path: string): string | null {
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "entities" && parts[1]) return decodeURIComponent(parts[1]);
  if (["characters", "plots", "entries", "fragments", "relationships"].includes(parts[0]) && parts[1]) {
    return decodeURIComponent(parts[1]);
  }
  return null;
}

export function entityRevision(snapshot: ProjectSnapshot, entityId: string): number | null {
  const collections = [
    snapshot.characters,
    snapshot.plots,
    snapshot.entries,
    snapshot.fragments,
    snapshot.relationships,
    snapshot.chapters,
    snapshot.timeline.lines,
  ] as Array<Array<{ entityId: string; revision: number }>>;
  for (const collection of collections) {
    const item = collection.find((candidate) => candidate.entityId === entityId);
    if (item) return item.revision;
  }
  return null;
}

export function canRetryAgainstLatest(
  path: string,
  submitted: ProjectSnapshot,
  latest: ProjectSnapshot,
): boolean {
  const targetId = mutationTargetId(path);
  if (!targetId) return false;
  const submittedRevision = entityRevision(submitted, targetId);
  return submittedRevision !== null && submittedRevision === entityRevision(latest, targetId);
}
