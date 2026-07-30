import { lazy, Suspense } from "react";
import { useRuntime } from "./api/runtime";
import { GlobalSearch } from "./components/GlobalSearch";
import { MergeConflictGate } from "./components/MergeConflictGate";
import { Navigation } from "./components/Navigation";
import { TransientNotice } from "./components/TransientNotice";
import { pageLoaders } from "./pageLoaders";
import { useUiStore } from "./state/ui";

const GraphPage = lazy(pageLoaders.graph);
const StoryPage = lazy(pageLoaders.story);
const TimelinePage = lazy(pageLoaders.timeline);
const CharactersPage = lazy(pageLoaders.characters);
const EntriesPage = lazy(pageLoaders.entries);
const FragmentsPage = lazy(pageLoaders.fragments);
const ManagementPage = lazy(pageLoaders.management);

const pageComponents = {
  graph: GraphPage,
  story: StoryPage,
  timeline: TimelinePage,
  characters: CharactersPage,
  entries: EntriesPage,
  fragments: FragmentsPage,
  management: ManagementPage,
};

export default function App() {
  const { snapshot, writable } = useRuntime();
  const page = useUiStore((state) => state.page);
  const Page = pageComponents[page];
  return (
    <div className={`app-frame is-${page}-view`}>
      <header className="app-header">
        <div className="brand"><span className="brand-mark">S</span><div><small>{snapshot.project.eyebrow}</small><strong>{snapshot.project.title}</strong></div></div>
        <Navigation />
        <div className="header-actions"><span className={`mode-indicator${writable ? " is-writable" : ""}`}>{writable ? "本地编辑" : "只读快照"}</span><GlobalSearch /></div>
      </header>
      <main className="page-host">
        <Suspense fallback={<div className="page-preparing" role="status"><span className="loading-mark" /><p>正在打开页面…</p></div>}><Page /></Suspense>
      </main>
      <TransientNotice />
      <MergeConflictGate />
    </div>
  );
}
