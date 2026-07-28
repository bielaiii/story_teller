export function compactStoryPreview(source: string): string {
  const blocks = source
    .replace(/\r\n?/g, "\n")
    .split(/\n\s*\n+/)
    .map((block) => block.trim())
    .filter((block) => block && !/^(?:-{3,}|\*{3,}|_{3,})$/.test(block));
  const selected: string[] = [];
  let layoutCost = 0;

  for (const block of blocks) {
    const lines = block.split("\n");
    const inconvenient = (
      /^```/.test(block)
      || lines.filter((line) => /^\s*\|.*\|\s*$/.test(line)).length >= 2
      || /^!\[[^\]]*\]\([^)]*\)$/.test(block)
    );
    if (inconvenient) continue;
    const visible = block
      .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/^[\s>#*+\-\d.)]+/gm, "")
      .replace(/[*_`~]/g, "")
      .replace(/\s+/g, "")
      .length;
    const blockCost = visible + (lines.length - 1) * 24;
    if (!visible || blockCost > 110 || layoutCost + blockCost > 105) continue;
    selected.push(block);
    layoutCost += blockCost;
    if (selected.length === 3) break;
  }

  return selected.join("\n\n") || "_正文较长，点击卡片阅读完整内容。_";
}
