import { lazy, Suspense, useDeferredValue } from "react";
import { useRuntime } from "./api/runtime";
import { GlobalSearch } from "./components/GlobalSearch";
import { Navigation } from "./components/Navigation";
import { useUiStore } from "./state/ui";

const pageLoaders = {
  graph: () => import("./pages/GraphPage"),
  story: () => import("./pages/StoryPage"),
  timeline: () => import("./pages/TimelinePage"),
  characters: () => import("./pages/CharactersPage"),
  entries: () => import("./pages/EntriesPage"),
  fragments: () => import("./pages/FragmentsPage"),
  checks: () => import("./pages/ChecksPage"),
};

const GraphPage = lazy(pageLoaders.graph);
const StoryPage = lazy(pageLoaders.story);
const TimelinePage = lazy(pageLoaders.timeline);
const CharactersPage = lazy(pageLoaders.characters);
const EntriesPage = lazy(pageLoaders.entries);
const FragmentsPage = lazy(pageLoaders.fragments);
const ChecksPage = lazy(pageLoaders.checks);

const pageComponents = {
  graph: GraphPage,
  story: StoryPage,
  timeline: TimelinePage,
  characters: CharactersPage,
  entries: EntriesPage,
  fragments: FragmentsPage,
  checks: ChecksPage,
};

export default function App() {
  const { snapshot, writable } = useRuntime();
  const requestedPage = useUiStore((state) => state.page);
  const page = useDeferredValue(requestedPage);
  const Page = pageComponents[page];
  return (
    <div className={`app-frame is-${page}-view`}>
      <header className="app-header">
        <div className="brand"><span className="brand-mark">S</span><div><small>{snapshot.project.eyebrow}</small><strong>{snapshot.project.title}</strong></div></div>
        <Navigation />
        <div className="header-actions"><span className={`mode-indicator${writable ? " is-writable" : ""}`}>{writable ? "本地编辑" : "只读快照"}</span><GlobalSearch /></div>
      </header>
      <main className="page-host">
        <Suspense fallback={null}><Page /></Suspense>
      </main>
    </div>
  );
}
