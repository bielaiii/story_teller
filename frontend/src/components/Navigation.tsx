import { startTransition, useState } from "react";
import { preloadPage } from "../pageLoaders";
import type { PageId } from "../state/ui";
import { useUiStore } from "../state/ui";

const pages: Array<[PageId, string]> = [
  ["story", "剧情"], ["graph", "图谱"], ["timeline", "时间线"],
    ["characters", "人物"], ["entries", "设定"], ["fragments", "碎片"],
];

export function Navigation() {
  const page = useUiStore((state) => state.page);
  const navigate = useUiStore((state) => state.navigate);
  const [pendingPage, setPendingPage] = useState<PageId | null>(null);
  const openPage = async (id: PageId) => {
    if (id === page || pendingPage) return;
    setPendingPage(id);
    try {
      await preloadPage(id);
      startTransition(() => navigate(id));
    } finally {
      setPendingPage(null);
    }
  };
  return (
    <nav className="main-nav" aria-label="页面切换">
      {pages.map(([id, label]) => (
        <button key={id} className={page === id ? "is-active" : ""} aria-current={page === id ? "page" : undefined} aria-busy={pendingPage === id || undefined} onPointerEnter={() => void preloadPage(id)} onFocus={() => void preloadPage(id)} onClick={() => void openPage(id)}>{label}</button>
      ))}
    </nav>
  );
}
