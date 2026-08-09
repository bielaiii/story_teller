export const CONTENT_COLOR_PALETTE = [
  "#4f6fae", "#8c5fa8", "#b45f75", "#b06f42",
  "#5d8f7b", "#4f8796", "#786a9e", "#9a6b55",
  "#6d7f9c", "#9a5f83", "#567a63", "#8d7052",
] as const;

function mix(color: string, target: string, amount: number): string {
  const parse = (value: string) => [1, 3, 5].map((offset) => Number.parseInt(value.slice(offset, offset + 2), 16));
  const source = parse(color);
  const destination = parse(target);
  return `#${source.map((value, index) => Math.round(value + (destination[index] - value) * amount).toString(16).padStart(2, "0")).join("")}`;
}

export function randomContentColor(): string {
  const random = globalThis.crypto?.getRandomValues
    ? globalThis.crypto.getRandomValues(new Uint32Array(1))[0] / 4294967296
    : Math.random();
  return CONTENT_COLOR_PALETTE[Math.floor(random * CONTENT_COLOR_PALETTE.length)];
}

export function avatarGradient(color: string): string {
  const normalized = /^#[0-9a-f]{6}$/i.test(color) ? color.toLowerCase() : CONTENT_COLOR_PALETTE[0];
  return `linear-gradient(145deg, ${mix(normalized, "#ffffff", .2)} 0%, ${normalized} 56%, ${mix(normalized, "#202538", .16)} 100%)`;
}

export function avatarBackground(item: { color: string; gradient?: string }): string {
  return item.gradient?.trim() || avatarGradient(item.color);
}
