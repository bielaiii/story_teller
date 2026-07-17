import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { PickedReference } from "../editor/MarkdownEditor";
import { MarkdownEditor } from "../editor/MarkdownEditor";
import { useEditorSaveShortcut } from "../editor/useEditorSaveShortcut";
import { useProjectMutation, useRuntime } from "../api/runtime";
import type { EntityDetail, Plot } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { FilterChips } from "../components/FilterChips";
import { Icon } from "../components/Icon";
import { StoryStructureEditor } from "../components/StoryStructureEditor";
import { RenderedMarkdown } from "../components/RenderedMarkdown";
import { StoryReader } from "../components/StoryReader";
import { Pagination } from "../components/Pagination";
import { useUiStore } from "../state/ui";

interface PlotDraft {
  title: string;
  chapterId: string;
  summary: string;
  body: string;
  status: string;
  accent: string;
  tags: string[];
  people: string[];
  entries: string[];
  lanes: string[];
  references: string[];
  key: boolean;
  climax: boolean;
}

const emptyDraft: PlotDraft = {
  title: "", chapterId: "", summary: "", body: "", status: "草稿", accent: "#3f7fc1",
  tags: [], people: [], entries: [], lanes: [], references: [], key: false, climax: false,
};

function draftFrom(plot: Plot): PlotDraft {
  return {
    title: plot.title, chapterId: plot.chapterId, summary: plot.summary, body: plot.body || "",
    status: plot.status, accent: plot.accent, tags: [...plot.tags], people: [...plot.people],
    entries: [...plot.entries], lanes: [...plot.lanes],
    references: [...new Set([...(plot.references || []), ...plot.people, ...plot.entries])],
    key: plot.key, climax: plot.climax,
  };
}

function compactStoryPreview(source: string) {
  const blocks = source
    .replace(/\r\n?/g, "\n")
    .split(/\n\s*\n+/)
    .map((block) => block.trim())
    .filter((block) => block && !/^(?:-{3,}|\*{3,}|_{3,})$/.test(block));
  const selected: string[] = [];
  let layoutCost = 0;

  for (const block of blocks) {
    const visible = block
      .replace(/^```[^\n]*|```$/gm, "")
      .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/^[\s>#*+\-\d.)]+/gm, "")
      .replace(/[*_`~]/g, "")
      .replace(/\s+/g, "")
      .length;
    const blockCost = visible + (block.match(/\n/g)?.length || 0) * 24;
    if (!visible || blockCost > 110 || layoutCost + blockCost > 105) continue;
    selected.push(block);
    layoutCost += blockCost;
    if (selected.length === 3) break;
  }

  return selected.join("\n\n") || "_正文较长，点击卡片阅读完整内容。_";
}

function PlotCard({ plot, chapterLabel, onOpen }: { plot: Plot; chapterLabel: string; onOpen: () => void }) {
  const importance = plot.climax ? "高潮" : plot.key ? "重点" : "";
  const preview = compactStoryPreview(plot.summary || plot.body || plot.bodyPreview || "_还没有正文。_");
  return <article className={`plot-card${importance ? " is-important" : ""}`} style={{ "--accent": plot.accent } as React.CSSProperties} onClick={onOpen}>
    {importance && <span className={`plot-card-ribbon${plot.climax ? " is-climax" : ""}`} aria-label={`${importance}剧情`}>{importance}</span>}
    <div className="plot-card-index">{String(plot.sequence).padStart(2, "0")}</div>
    <div className="card-meta">
      <span className="plot-card-meta-item" aria-label={`篇章 ${chapterLabel}`} title={`篇章：${chapterLabel}`}><Icon name="book" /><strong>{chapterLabel}</strong></span>
      <span className="plot-card-meta-item" aria-label={`状态 ${plot.status || "未标记"}`} title={`状态：${plot.status || "未标记"}`}><Icon name="filter" /><strong>{plot.status || "未标记"}</strong></span>
    </div>
    <div className="plot-card-copy"><h2>{plot.title}</h2><RenderedMarkdown source={preview} className="plot-card-preview content-card-preview" /></div>
    <div className="metadata-tags">{plot.tags.map((tag) => <span key={tag} style={{ borderColor: plot.accent, color: plot.accent }}>{tag}</span>)}</div>
    <button className="card-arrow" aria-label={`阅读${plot.title}`}><Icon name="arrow" /></button>
  </article>;
}

function PlotEditor({ plotId, onClose }: { plotId: string | "new"; onClose: () => void }) {
  const { api, project, snapshot, writable } = useRuntime();
  const mutation = useProjectMutation();
  const queryClient = useQueryClient();
  const [currentId, setCurrentId] = useState<string | "new">(plotId);
  const [initialChapterId] = useState(() => snapshot.chapters[0]?.entityId || "");
  const detail = useQuery({
    queryKey: ["entity", project, currentId],
    queryFn: () => api.detail<Plot>(currentId),
    enabled: currentId !== "new",
  });
  const [draft, setDraft] = useState<PlotDraft>({ ...emptyDraft, chapterId: initialChapterId });
  const [baseline, setBaseline] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (currentId === "new") {
      const next = { ...emptyDraft, chapterId: initialChapterId };
      setDraft(next); setBaseline(JSON.stringify(next));
    } else if (detail.data?.data) {
      const next = draftFrom(detail.data.data);
      setDraft(next); setBaseline(JSON.stringify(next));
    }
  }, [currentId, detail.data, initialChapterId]);

  const dirty = Boolean(baseline && JSON.stringify(draft) !== baseline);
  const close = () => dirty ? setConfirmClose(true) : onClose();
  const change = <K extends keyof PlotDraft>(key: K, value: PlotDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const addReference = (reference: PickedReference) => {
    const key = reference.kind === "character" ? "people" : "entries";
    setDraft((current) => ({
      ...current,
      [key]: current[key].includes(reference.entityId) ? current[key] : [...current[key], reference.entityId],
      references: current.references.includes(reference.entityId)
        ? current.references
        : [...current.references, reference.entityId],
    }));
  };
  const save = async () => {
    if (!writable || mutation.isPending) return;
    setMessage("");
    try {
      const payload = { ...draft } as unknown as Record<string, unknown>;
      const result = await mutation.mutateAsync({
        path: currentId === "new" ? "/plots" : `/plots/${encodeURIComponent(currentId)}`,
        method: currentId === "new" ? "POST" : "PATCH",
        payload,
      });
      if (currentId === "new") {
        const created = result.changed.plots?.find((item) => !snapshot.plots.some((existing) => existing.entityId === item.entityId));
        if (created?.entityId) setCurrentId(String(created.entityId));
      } else {
        queryClient.setQueryData<EntityDetail<Plot>>(["entity", project, currentId], (current) => current ? {
          ...current,
          title: draft.title,
          data: { ...current.data, ...draft },
        } : current);
      }
      setBaseline(JSON.stringify(draft));
      setMessage(result.warnings[0] || "已保存");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    }
  };
  const remove = async () => {
    if (currentId === "new") return;
    try {
      await mutation.mutateAsync({ path: `/entities/${encodeURIComponent(currentId)}`, method: "DELETE", payload: {} });
      onClose();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
    }
  };
  useEditorSaveShortcut(save);
  if (plotId !== "new" && detail.isPending) return <div className="dialog-backdrop"><div className="editor-dialog loading-dialog">正在读取正文…</div></div>;
  return (
    <div className="dialog-backdrop editor-backdrop" role="presentation">
      <section className="editor-dialog" role="dialog" aria-modal="true" aria-label={currentId === "new" ? "写新剧情" : `编辑${draft.title}`}>
        <header className="dialog-header">
          <div><small>{currentId === "new" ? "New Story" : "Story Editor"}</small><h2>{currentId === "new" ? "写新剧情" : draft.title || "编辑剧情"}</h2></div>
          <div className="dialog-actions">
            {currentId !== "new" && writable && <button className="icon-button is-danger" aria-label="删除剧情" title="删除剧情" onClick={() => setDeleteConfirm(true)}><Icon name="trash" /></button>}
            <button className="icon-button" aria-label="关闭" title="关闭" onClick={close}><Icon name="close" /></button>
          </div>
        </header>
        <button className="settings-toggle" type="button" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((value) => !value)}><Icon name="settings" /><span>剧情设置</span><small>{settingsOpen ? "收起" : "展开"}</small></button>
        {settingsOpen && <div className="editor-settings">
          <label className="wide"><span>标题</span><input value={draft.title} onChange={(event) => change("title", event.target.value)} /></label>
          <label><span>篇章</span><select value={draft.chapterId} onChange={(event) => change("chapterId", event.target.value)}>{snapshot.chapters.map((item) => <option key={item.entityId} value={item.entityId}>{item.label}</option>)}</select></label>
          <label><span>状态</span><input value={draft.status} onChange={(event) => change("status", event.target.value)} /></label>
          <label><span>强调色</span><input type="color" value={draft.accent} onChange={(event) => change("accent", event.target.value)} /></label>
          <label className="wide"><span>摘要</span><input value={draft.summary} onChange={(event) => change("summary", event.target.value)} /></label>
          <label className="wide"><span>标签（逗号分隔）</span><input value={draft.tags.join("，")} onChange={(event) => change("tags", event.target.value.split(/[，,]/).map((item) => item.trim()).filter(Boolean))} /></label>
          <label className="check"><input type="checkbox" checked={draft.key} onChange={(event) => change("key", event.target.checked)} />关键剧情</label>
          <label className="check"><input type="checkbox" checked={draft.climax} onChange={(event) => change("climax", event.target.checked)} />高潮剧情</label>
        </div>}
        <MarkdownEditor value={draft.body} onChange={(body) => change("body", body)} onSave={save} characters={snapshot.characters} entries={snapshot.entries} sourceEntityId={currentId === "new" ? undefined : currentId} onReference={addReference} autoFocus />
        <footer className="editor-footer"><span className={dirty ? "is-dirty" : ""}>{message || (dirty ? "有未保存修改" : "已保存")}</span><small>@ 选择人物 · / 选择设定 · ⌘/Ctrl+S 保存</small></footer>
      </section>
      <ConfirmDialog open={confirmClose} title="放弃未保存修改？" message="关闭后，本次未保存的正文和设置会丢失。" confirmLabel="放弃修改" danger onCancel={() => setConfirmClose(false)} onConfirm={onClose} />
      <ConfirmDialog open={deleteConfirm} title={`删除“${draft.title}”？`} message="剧情会进入回收站保留 7 天；原有稳定 ID 和阅读位置不会立即清除。" confirmLabel="移入回收站" danger onCancel={() => setDeleteConfirm(false)} onConfirm={remove} />
    </div>
  );
}

export default function StoryPage() {
  const { snapshot, writable } = useRuntime();
  const selectedPlotId = useUiStore((state) => state.selectedPlotId);
  const selectPlot = useUiStore((state) => state.selectPlot);
  const [editorId, setEditorId] = useState<string | "new" | null>(null);
  const [readerId, setReaderId] = useState<string | null>(selectedPlotId);
  const [structureEditor, setStructureEditor] = useState(false);
  const storyScrollRef = useRef(0);
  const statuses = useMemo(() => [...new Set(snapshot.plots.map((item) => item.status))].sort(), [snapshot.plots]);
  const tags = useMemo(() => [...new Set(snapshot.plots.flatMap((item) => item.tags))].sort(), [snapshot.plots]);
  const [selectedStatuses, setSelectedStatuses] = useState<string[]>(statuses);
  const [selectedTags, setSelectedTags] = useState<string[]>(tags);
  const [chapter, setChapter] = useState("");
  const [page, setPage] = useState(1);
  useEffect(() => setSelectedStatuses(statuses), [statuses.join("\0")]);
  useEffect(() => setSelectedTags(tags), [tags.join("\0")]);
  useEffect(() => { if (chapter && !snapshot.chapters.some((item) => item.entityId === chapter)) setChapter(""); }, [chapter, snapshot.chapters]);
  useEffect(() => {
    if (!selectedPlotId) return;
    setReaderId(selectedPlotId);
  }, [selectedPlotId]);
  useEffect(() => setPage(1), [chapter, selectedStatuses.join("\0"), selectedTags.join("\0")]);
  const filteredPlots = snapshot.plots.filter((plot) =>
    (!chapter || plot.chapterId === chapter) && selectedStatuses.includes(plot.status) &&
    (selectedTags.length === tags.length || plot.tags.some((tag) => selectedTags.includes(tag))),
  );
  const totalPages = Math.max(1, Math.ceil(filteredPlots.length / 9));
  const plots = filteredPlots.slice((Math.min(page, totalPages) - 1) * 9, Math.min(page, totalPages) * 9);
  const open = (id: string) => { storyScrollRef.current = window.scrollY; selectPlot(id); setReaderId(id); };
  const closeReader = () => {
    selectPlot(null);
    setReaderId(null);
    requestAnimationFrame(() => window.scrollTo({ top: storyScrollRef.current, behavior: "auto" }));
  };
  const navigateReader = (id: string) => { selectPlot(id); setReaderId(id); };
  const readerPlot = snapshot.plots.find((item) => item.entityId === readerId);
  const readingOrder = useMemo(() => [...snapshot.plots].sort((left, right) => left.sequence - right.sequence), [snapshot.plots]);
  const readerIndex = readerPlot ? readingOrder.findIndex((item) => item.entityId === readerPlot.entityId) : -1;
  if (readerPlot) return <>
    <StoryReader
      plot={readerPlot}
      previous={readerIndex > 0 ? readingOrder[readerIndex - 1] : undefined}
      next={readerIndex >= 0 && readerIndex < readingOrder.length - 1 ? readingOrder[readerIndex + 1] : undefined}
      onBack={closeReader}
      onNavigate={navigateReader}
      onEdit={writable ? () => setEditorId(readerPlot.entityId) : undefined}
    />
    {editorId && <PlotEditor plotId={editorId} onClose={() => setEditorId(null)} />}
  </>;
  return (
    <section className="workspace-page story-page">
      <header className="page-header"><div><small>{snapshot.project.eyebrow || "Story Teller"}</small><h1>{snapshot.project.title}</h1></div><div className="page-actions"><select aria-label="篇章筛选" value={chapter} onChange={(event) => setChapter(event.target.value)}><option value="">所有篇章</option>{snapshot.chapters.map((item) => <option key={item.entityId} value={item.entityId}>{item.label}</option>)}</select>{writable && <><button className="icon-button" aria-label="编辑篇章与阅读顺序" title="编辑篇章与阅读顺序" onClick={() => setStructureEditor(true)}><Icon name="settings" /></button><button className="icon-button is-primary" aria-label="写新剧情" title="写新剧情" onClick={() => setEditorId("new")}><Icon name="plus" /></button></>}</div></header>
      <div className="filter-panel"><FilterChips label="状态" values={statuses} selected={selectedStatuses} onChange={setSelectedStatuses} /><FilterChips label="标签" values={tags} selected={selectedTags} onChange={setSelectedTags} collapsible /></div>
      <div className="plot-grid">{plots.map((plot) => <PlotCard
        key={plot.entityId}
        plot={plot}
        chapterLabel={snapshot.chapters.find((item) => item.entityId === plot.chapterId)?.label || "未安排"}
        onOpen={() => open(plot.entityId)}
      />)}</div>
      <Pagination page={Math.min(page, totalPages)} totalPages={totalPages} onChange={(value) => { setPage(value); window.scrollTo({ top: 0, behavior: "smooth" }); }} />
      {!plots.length && <div className="empty-state"><Icon name="book" /><h2>当前筛选下没有剧情</h2><p>调整状态、标签或篇章后再看。</p></div>}
      {editorId && <PlotEditor plotId={editorId} onClose={() => setEditorId(null)} />}
      {structureEditor && <StoryStructureEditor onClose={() => setStructureEditor(false)} />}
    </section>
  );
}
