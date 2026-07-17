import { useDeferredValue, useMemo, useState } from "react";
import { pinyin } from "pinyin-pro";
import { useRuntime } from "../api/runtime";
import { useUiStore } from "../state/ui";
import { Icon } from "./Icon";

function searchable(value: string) {
  return `${value} ${pinyin(value, { toneType: "none" })} ${pinyin(value, { pattern: "first", toneType: "none", type: "array" }).join("")}`.toLowerCase();
}

export function GlobalSearch() {
  const { snapshot } = useRuntime();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query.trim().toLowerCase());
  const navigate = useUiStore((state) => state.navigate);
  const selectCharacter = useUiStore((state) => state.selectCharacter);
  const selectPlot = useUiStore((state) => state.selectPlot);
  const selectEntry = useUiStore((state) => state.selectEntry);
  const results = useMemo(() => {
    if (!deferred) return [];
    const candidates = [
      ...snapshot.characters.map((item) => ({ id: item.entityId, label: item.name, detail: `人物 · ${item.characterScope}`, page: "characters" as const, search: [item.name, ...item.aliases].join(" ") })),
      ...snapshot.plots.map((item) => ({ id: item.entityId, label: item.title, detail: `剧情 · 第 ${item.sequence} 篇`, page: "story" as const, search: `${item.title} ${item.summary} ${item.bodyPreview}` })),
      ...snapshot.entries.map((item) => ({ id: item.entityId, label: item.name, detail: `设定 · ${item.type}`, page: "entries" as const, search: [item.name, ...item.aliases, ...item.tags].join(" ") })),
      ...snapshot.fragments.map((item) => ({ id: item.entityId, label: item.title, detail: "灵感碎片", page: "fragments" as const, search: `${item.title} ${item.bodyPreview}` })),
    ];
    return candidates.filter((item) => searchable(item.search).includes(deferred)).slice(0, 12);
  }, [deferred, snapshot]);
  const choose = (item: (typeof results)[number]) => {
    navigate(item.page);
    if (item.page === "characters") selectCharacter(item.id);
    if (item.page === "story") selectPlot(item.id);
    if (item.page === "entries") selectEntry(item.id);
    setOpen(false);
    setQuery("");
  };
  return (
    <div className={`global-command${open ? " is-open" : ""}`}>
      <button className="icon-button" aria-label="全局搜索" title="搜索（⌘/Ctrl+K）" onClick={() => setOpen((value) => !value)}><Icon name="search" /></button>
      {open && <div className="command-panel">
        <label><Icon name="search" /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索人物、剧情、设定和正文" /></label>
        <div className="command-results">
          {results.map((item) => <button key={item.id} onClick={() => choose(item)}><strong>{item.label}</strong><small>{item.detail}</small></button>)}
          {deferred && !results.length && <p>没有找到匹配内容</p>}
        </div>
      </div>}
    </div>
  );
}
