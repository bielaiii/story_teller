/** Build a partial command from the fields actually owned and changed by a form. */
export function changedFields(payload: Record<string, unknown>, baseline: Record<string, unknown>): Record<string, unknown> {
  const result = Object.fromEntries(Object.entries(payload).filter(([key, value]) =>
    key === "entityRevision" || JSON.stringify(value) !== JSON.stringify(baseline[key])));
  const position = ["storyPositionMode", "storyAnchorPlotId", "storySortKey"];
  if (position.some(key => key in result)) {
    for (const key of position) if (key in payload) result[key] = payload[key];
  }
  if (!("chapterNumber" in result)) delete result.shiftFollowing;
  return result;
}
