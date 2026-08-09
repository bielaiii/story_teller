import type { Relationship } from "./types";

export function relationshipHasDistinctImpressions(
  relationship: Pick<Relationship, "fromImpression" | "toImpression">,
): boolean {
  const from = relationship.fromImpression?.trim() || "";
  const to = relationship.toImpression?.trim() || "";
  return Boolean(from && to && from !== to);
}

export function effectiveGraphLineMode(
  relationship: Pick<Relationship, "graphLineMode" | "fromImpression" | "toImpression">,
): "single" | "double" {
  return relationship.graphLineMode === "double" || relationshipHasDistinctImpressions(relationship)
    ? "double"
    : "single";
}
