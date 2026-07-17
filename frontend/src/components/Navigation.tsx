import { startTransition } from "react";
import type { PageId } from "../state/ui";
import { useUiStore } from "../state/ui";

const pages: Array<[PageId, string]> = [
  ["story", "剧情"], ["graph", "图谱"], ["timeline", "时间线"],
  ["characters", "人物"], ["entries", "设定"], ["fragments", "碎片"], ["checks", "检查"],
];

const preloaders: Record<PageId, () => Promise<unknown>> = {
  story: () => import("../pages/StoryPage"),
  graph: () => import("../pages/GraphPage"),
  timeline: () => import("../pages/TimelinePage"),
  characters: () => import("../pages/CharactersPage"),
  entries: () => import("../pages/EntriesPage"),
  fragments: () => import("../pages/FragmentsPage"),
  checks: () => import("../pages/ChecksPage"),
};

export function Navigation() {
  const page = useUiStore((state) => state.page);
  const navigate = useUiStore((state) => state.navigate);
  return (
    <nav className="main-nav" aria-label="页面切换">
      {pages.map(([id, label]) => (
        <button key={id} className={page === id ? "is-active" : ""} aria-current={page === id ? "page" : undefined} onPointerEnter={() => void preloaders[id]()} onFocus={() => void preloaders[id]()} onClick={() => startTransition(() => navigate(id))}>{label}</button>
      ))}
    </nav>
  );
}
