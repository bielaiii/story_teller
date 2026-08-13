export const PLOT_STATUS_OPTIONS = ["素材", "草稿", "待串联", "已接入", "已完成"] as const;

export function plotChapterNumber(title: string, fallback: number, explicit?: number | null): number {
  if (typeof explicit === "number" && Number.isFinite(explicit)) return explicit;
  const match = /^第\s*(\d+)\s*章$/.exec(title.trim());
  return match ? Number(match[1]) : fallback;
}

export function plotChapterTitle(number: number): string {
  return `第 ${number} 章`;
}

export function plotStatusOptions(current: string): string[] {
  const values = [...PLOT_STATUS_OPTIONS] as string[];
  if (current && !values.includes(current)) values.unshift(current);
  return values;
}

const TAG_COLORS = [
  "#c94f62", "#3979b8", "#2b8a72", "#8a64b8", "#b06b2d", "#3f7f91", "#a65386",
];

const NAMED_TAG_COLORS: Record<string, string> = {
  回归篇: "#c94f62",
};

export function tagColor(label: string): string {
  if (NAMED_TAG_COLORS[label]) return NAMED_TAG_COLORS[label];
  let hash = 0;
  for (const character of label) hash = ((hash * 31) + character.codePointAt(0)!) >>> 0;
  return TAG_COLORS[hash % TAG_COLORS.length];
}

export function tagStyle(label: string) {
  const color = tagColor(label);
  return {
    borderColor: `color-mix(in srgb, ${color} 42%, transparent)`,
    color,
    backgroundColor: `color-mix(in srgb, ${color} 10%, white)`,
  };
}
