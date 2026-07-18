import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { useRuntime } from "../api/runtime";
import { preloadPage } from "../pageLoaders";
import { useUiStore } from "../state/ui";
import { Icon } from "./Icon";

type PhoneticSearch = (value: string) => string;
let phoneticSearchPromise: Promise<PhoneticSearch> | null = null;

function loadPhoneticSearch() {
  phoneticSearchPromise ||= import("pinyin-pro").then(({ pinyin }) => (value: string) => (
    `${pinyin(value, { toneType: "none" })} ${pinyin(value, { pattern: "first", toneType: "none", type: "array" }).join("")}`.toLowerCase()
  ));
  return phoneticSearchPromise;
}

function searchable(value: string, phoneticSearch: PhoneticSearch | null) {
  return `${value.toLowerCase()} ${phoneticSearch?.(value) || ""}`;
}

export function GlobalSearch() {
  const { snapshot } = useRuntime();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [phoneticSearch, setPhoneticSearch] = useState<PhoneticSearch | null>(null);
  const deferred = useDeferredValue(query.trim().toLowerCase());
  const navigate = useUiStore((state) => state.navigate);
  const selectCharacter = useUiStore((state) => state.selectCharacter);
  const selectPlot = useUiStore((state) => state.selectPlot);
  const selectEntry = useUiStore((state) => state.selectEntry);
  const results = useMemo(() => {
    if (!deferred) return [];
    const candidates = [
      ...snapshot.characters.map((item) => ({ id: item.entityId, label: item.name, detail: `人物 · ${item.characterScope} · ID ${item.id}`, page: "characters" as const, search: [item.name, item.id, ...item.aliases].join(" ") })),
      ...snapshot.plots.map((item) => ({ id: item.entityId, label: item.title, detail: `剧情 · 第 ${item.sequence} 篇`, page: "story" as const, search: `${item.title} ${item.summary} ${item.bodyPreview}` })),
      ...snapshot.entries.map((item) => ({ id: item.entityId, label: item.name, detail: `设定 · ${item.type}`, page: "entries" as const, search: [item.name, ...item.aliases, ...item.tags].join(" ") })),
      ...snapshot.fragments.map((item) => ({ id: item.entityId, label: item.title, detail: "灵感碎片", page: "fragments" as const, search: `${item.title} ${item.bodyPreview}` })),
    ];
    return candidates.filter((item) => searchable(item.search, phoneticSearch).includes(deferred)).slice(0, 12);
  }, [deferred, phoneticSearch, snapshot]);
  useEffect(() => {
    if (!open || phoneticSearch) return;
    let active = true;
    void loadPhoneticSearch().then((search) => { if (active) setPhoneticSearch(() => search); });
    return () => { active = false; };
  }, [open, phoneticSearch]);
  const choose = async (item: (typeof results)[number]) => {
    await preloadPage(item.page);
    navigate(item.page);
    if (item.page === "characters") selectCharacter(item.id);
    if (item.page === "story") selectPlot(item.id);
    if (item.page === "entries") selectEntry(item.id);
    setOpen(false);
    setQuery("");
  };
  return (
    <div className={`global-command${open ? " is-open" : ""}`}>
      <button className="icon-button" aria-label="全局搜索" title="搜索（⌘/Ctrl+K）" onPointerEnter={() => void loadPhoneticSearch()} onFocus={() => void loadPhoneticSearch()} onClick={() => setOpen((value) => !value)}><Icon name="search" /></button>
      {open && <div className="command-panel">
        <label><Icon name="search" /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索人物、剧情、设定和正文" /></label>
        <div className="command-results">
          {results.map((item) => <button key={`${item.page}:${item.id}`} onClick={() => void choose(item)}><strong>{item.label}</strong><small>{item.detail}</small></button>)}
          {deferred && !results.length && <p>没有找到匹配内容</p>}
        </div>
      </div>}
    </div>
  );
}
