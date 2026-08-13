import { useMemo, useState } from "react";
import type { Character, Plot } from "../api/types";
import { useRuntime } from "../api/runtime";
import { Icon } from "./Icon";

type ExportMode = "single" | "range" | "all";
type ExportKind = "plots" | "characters";

function safeFilename(value: string): string {
  return value.trim().replace(/[\\/:*?"<>|]+/g, "-").replace(/\s+/g, " ") || "未命名";
}

export function selectExportItems<T>(
  items: T[],
  mode: ExportMode,
  start: number,
  end: number,
): T[] {
  if (!items.length) return [];
  if (mode === "all") return items;
  const safeStart = Math.max(0, Math.min(start, items.length - 1));
  if (mode === "single") return [items[safeStart]];
  const safeEnd = Math.max(0, Math.min(end, items.length - 1));
  return items.slice(Math.min(safeStart, safeEnd), Math.max(safeStart, safeEnd) + 1);
}

export function plotMarkdown(plot: Plot): string {
  const heading = `# 第 ${plot.chapterNumber ?? plot.sequence} 章${plot.title.trim() ? ` · ${plot.title.trim()}` : ""}`;
  return `${heading}\n\n${(plot.body || "").trim()}\n`;
}

function personaSection(title: string, items: Array<{ key: string; value: string }> | undefined): string {
  if (!items?.length) return "";
  return `## ${title}\n\n${items.map((item) => `- ${item.key ? `${item.key}：` : ""}${item.value}`).join("\n")}\n\n`;
}

export function characterMarkdown(character: Character): string {
  const facts = Object.entries(character.facts || {});
  const sections = [
    `# ${character.name}\n\n`,
    character.intro?.trim() ? `## 人物简介\n\n${character.intro.trim()}\n\n` : "",
    character.destinyOutline?.trim() ? `## 人物大纲\n\n${character.destinyOutline.trim()}\n\n` : "",
    personaSection("核心人设", character.corePersona),
    personaSection("补充人设", character.supplementPersona),
    facts.length ? `## 人物档案\n\n${facts.map(([key, value]) => `- ${key}：${value}`).join("\n")}\n\n` : "",
  ];
  return sections.join("").trimEnd() + "\n";
}

function downloadMarkdown(filename: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type: "text/markdown;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function ExportGroup({ kind, onMessage }: { kind: ExportKind; onMessage: (value: string) => void }) {
  const { api, snapshot } = useRuntime();
  const items: Array<Plot | Character> = kind === "plots" ? snapshot.plots : snapshot.characters;
  const [mode, setMode] = useState<ExportMode>("single");
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(Math.max(0, items.length - 1));
  const [downloading, setDownloading] = useState(false);
  const selected = useMemo(() => selectExportItems(items, mode, start, end), [items, mode, start, end]);
  const label = kind === "plots" ? "剧情" : "人物简介";
  const optionLabel = (item: Plot | Character) => kind === "plots"
    ? `第 ${(item as Plot).chapterNumber ?? (item as Plot).sequence} 章 · ${(item as Plot).title}`
    : (item as Character).name;

  const download = async () => {
    if (!selected.length) return;
    setDownloading(true);
    onMessage(`正在整理${label}…`);
    try {
      const details = await Promise.all(selected.map((item) => api.detail<Plot | Character>(item.entityId)));
      const documents = details.map((detail) => kind === "plots"
        ? plotMarkdown(detail.data as Plot)
        : characterMarkdown(detail.data as Character));
      const single = mode === "single";
      const filename = single
        ? `${safeFilename(optionLabel(selected[0]))}.md`
        : `${snapshot.project.title}-${label}-${mode === "all" ? "全部" : `${start + 1}-${end + 1}`}.md`;
      downloadMarkdown(filename, documents.join("\n\n---\n\n"));
      onMessage(`已下载 ${selected.length} ${kind === "plots" ? "篇剧情" : "份人物简介"}`);
    } catch (error) {
      onMessage(error instanceof Error ? `下载失败：${error.message}` : "下载失败");
    } finally {
      setDownloading(false);
    }
  };

  return <section className="markdown-export-group">
    <header><span className="export-kind-icon"><Icon name={kind === "plots" ? "book" : "person"} /></span><div><h4>{label}</h4><small>导出完整 Markdown 内容</small></div></header>
    <div className="export-mode-choices" aria-label={`${label}下载范围`}>
      {(["single", "range", "all"] as ExportMode[]).map((value) => <button key={value} type="button" className={mode === value ? "is-active" : ""} aria-pressed={mode === value} onClick={() => setMode(value)}>{value === "single" ? "单项" : value === "range" ? "范围" : "全部"}</button>)}
    </div>
    {mode !== "all" && <div className="export-selectors">
      <label><span>{mode === "range" ? "从" : "选择"}</span><select value={start} onChange={(event) => setStart(Number(event.target.value))}>{items.map((item, index) => <option key={item.entityId} value={index}>{optionLabel(item)}</option>)}</select></label>
      {mode === "range" && <label><span>到</span><select value={end} onChange={(event) => setEnd(Number(event.target.value))}>{items.map((item, index) => <option key={item.entityId} value={index}>{optionLabel(item)}</option>)}</select></label>}
    </div>}
    <footer><small>{selected.length} 项内容</small><button type="button" className="export-download-button" disabled={!selected.length || downloading} onClick={() => void download()}><Icon name="save" />{downloading ? "正在生成…" : "下载 Markdown"}</button></footer>
  </section>;
}

export function MarkdownExportPanel({ onMessage }: { onMessage: (value: string) => void }) {
  return <section className="recovery-panel markdown-export-panel">
    <header><div><small>Markdown Export</small><h3>内容下载</h3></div><p>单项、范围或全部导出</p></header>
    <div className="markdown-export-groups">
      <ExportGroup kind="plots" onMessage={onMessage} />
      <ExportGroup kind="characters" onMessage={onMessage} />
    </div>
  </section>;
}
