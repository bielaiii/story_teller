import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
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

export function searchMatchContext(source: string, query: string, radius = 54): string {
  const plain = source
    .replace(/!\[[^\]]*]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)]\([^)]*\)/g, "$1")
    .replace(/[`*_>#|~-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!plain) return "";
  const matchAt = plain.toLocaleLowerCase().indexOf(query.toLocaleLowerCase());
  if (matchAt < 0) return plain.length > radius * 2 ? `${plain.slice(0, radius * 2).trim()}…` : plain;
  const start = Math.max(0, matchAt - radius);
  const end = Math.min(plain.length, matchAt + query.length + radius);
  return `${start ? "…" : ""}${plain.slice(start, end).trim()}${end < plain.length ? "…" : ""}`;
}

function SearchSnippet({ source, query }: { source: string; query: string }) {
  const context = searchMatchContext(source, query);
  if (!context) return null;
  const matchAt = context.toLocaleLowerCase().indexOf(query.toLocaleLowerCase());
  if (matchAt < 0) return <p>{context}</p>;
  return <p>
    {context.slice(0, matchAt)}
    <mark>{context.slice(matchAt, matchAt + query.length)}</mark>
    {context.slice(matchAt + query.length)}
  </p>;
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
  const selectFragment = useUiStore((state) => state.selectFragment);
  const results = useMemo(() => {
    if (!deferred) return [];
    const candidates = [
      ...snapshot.characters.map((item) => ({ id: item.entityId, label: item.name, detail: `人物 · ${item.characterScope} · ID ${item.id}`, page: "characters" as const, search: [item.name, item.id, ...item.aliases, item.introPreview].join(" "), preview: item.introPreview })),
      ...snapshot.plots.map((item) => ({ id: item.entityId, label: item.title, detail: `剧情 · 第 ${item.chapterNumber ?? item.sequence} 篇`, page: "story" as const, search: `${item.title} ${item.summary} ${item.bodyPreview}`, preview: `${item.summary}\n${item.bodyPreview}` })),
      ...snapshot.entries.map((item) => ({ id: item.entityId, label: item.name, detail: `设定 · ${item.type}`, page: "entries" as const, search: [item.name, ...item.aliases, ...item.tags, item.bodyPreview].join(" "), preview: item.bodyPreview })),
      ...snapshot.fragments.map((item) => ({ id: item.entityId, label: item.title, detail: "灵感碎片", page: "fragments" as const, search: `${item.title} ${item.bodyPreview}`, preview: item.bodyPreview })),
    ];
    return candidates.filter((item) => searchable(item.search, phoneticSearch).includes(deferred)).slice(0, 12);
  }, [deferred, phoneticSearch, snapshot]);
  useEffect(() => {
    if (!open || phoneticSearch) return;
    let active = true;
    void loadPhoneticSearch().then((search) => { if (active) setPhoneticSearch(() => search); });
    return () => { active = false; };
  }, [open, phoneticSearch]);
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        setQuery("");
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open]);
  const choose = async (item: (typeof results)[number]) => {
    await preloadPage(item.page);
    navigate(item.page);
    if (item.page === "characters") selectCharacter(item.id);
    if (item.page === "story") selectPlot(item.id);
    if (item.page === "entries") selectEntry(item.id);
    if (item.page === "fragments") selectFragment(item.id);
    setOpen(false);
    setQuery("");
  };
  return (
    <div className={`global-command${open ? " is-open" : ""}`}>
      <button className="icon-button" aria-label="全局搜索" title="搜索（⌘/Ctrl+K）" onPointerEnter={() => void loadPhoneticSearch()} onFocus={() => void loadPhoneticSearch()} onClick={() => setOpen((value) => !value)}><Icon name="search" /></button>
      {open && createPortal(<><button className="command-panel-scrim" type="button" aria-label="关闭全局搜索" onClick={() => { setOpen(false); setQuery(""); }} /><section className="command-panel" role="dialog" aria-modal="true" aria-label="全局搜索">
        <header><label><Icon name="search" /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索人物、剧情、设定和正文" /></label><button className="icon-button" type="button" aria-label="关闭全局搜索" onClick={() => { setOpen(false); setQuery(""); }}><Icon name="close" /></button></header>
        <div className="command-results">
          {results.map((item) => <button key={`${item.page}:${item.id}`} onClick={() => void choose(item)}><span><strong>{item.label}</strong><SearchSnippet source={item.preview} query={deferred} /></span><small>{item.detail}</small></button>)}
          {deferred && !results.length && <p>没有找到匹配内容</p>}
        </div>
      </section></>, document.body)}
    </div>
  );
}
