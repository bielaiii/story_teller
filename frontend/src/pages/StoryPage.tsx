import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { PickedReference } from "../editor/MarkdownEditor";
import { DeferredMarkdownEditor as MarkdownEditor } from "../editor/DeferredMarkdownEditor";
import { useEditorSaveShortcut } from "../editor/useEditorSaveShortcut";
import { browserDraftKey, clearBrowserDraft, restoreBrowserDraft, useBrowserDraft } from "../editor/browserDraft";
import { useProjectMutation, useRuntime } from "../api/runtime";
import type { EntityDetail, Plot } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { AppearancePeopleField, detectedCharacterIds, missingAppearanceNames } from "../components/AppearancePeopleField";
import { EditorSettingsSection } from "../components/EditorSettingsSection";
import { FilterChips } from "../components/FilterChips";
import { Icon } from "../components/Icon";
import { StoryStructureEditor } from "../components/StoryStructureEditor";
import { CompleteBlockPreview } from "../components/CompleteBlockPreview";
import { StoryReader } from "../components/StoryReader";
import { Pagination } from "../components/Pagination";
import { useUiStore } from "../state/ui";
import { compactStoryPreview } from "../storyPreview";
import { plotChapterNumber, plotChapterTitle, plotStatusOptions, tagColor, tagStyle } from "../storyOptions";

interface PlotDraft {
  chapterNumber: string;
  chapterId: string;
  summary: string;
  body: string;
  status: string;
  accent: string;
  tags: string[];
  people: string[];
  appearanceNames: string[];
  entries: string[];
  lanes: string[];
  storyPositionMode: "follow_reading" | "before" | "after" | "fixed";
  storyAnchorPlotId: string;
  storySortKey: string;
  references: string[];
  key: boolean;
  climax: boolean;
}

const emptyDraft: PlotDraft = {
  chapterNumber: "1", chapterId: "", summary: "", body: "", status: "草稿", accent: "#3f7fc1",
  tags: [], people: [], appearanceNames: [], entries: [], lanes: [], references: [], key: false, climax: false,
  storyPositionMode: "follow_reading", storyAnchorPlotId: "", storySortKey: "",
};

function draftFrom(plot: Plot): PlotDraft {
  return {
    chapterNumber: String(plotChapterNumber(plot.title, plot.sequence)), chapterId: plot.chapterId, summary: plot.summary, body: plot.body || "",
    status: plot.status, accent: plot.accent, tags: [...plot.tags], people: [...plot.people],
    appearanceNames: [],
    entries: [...plot.entries], lanes: [...plot.lanes],
    storyPositionMode: plot.storyOrderMode === "fixed" ? (plot.storyAnchorSide || "fixed") : "follow_reading",
    storyAnchorPlotId: plot.storyAnchorPlotId || "",
    storySortKey: plot.storySortKey || plot.sortKey,
    references: [...new Set([...(plot.references || []), ...plot.people, ...plot.entries])],
    key: plot.key, climax: plot.climax,
  };
}

function PlotCard({ plot, chapterLabel, onOpen }: { plot: Plot; chapterLabel: string; onOpen: () => void }) {
  const importance = plot.climax ? "高潮" : plot.key ? "重点" : "";
  const preview = compactStoryPreview(plot.summary || plot.body || plot.bodyPreview || "_还没有正文。_");
  const chapterColor = tagColor(chapterLabel);
  const statusColor = tagColor(plot.status || "未标记");
  return <article className={`plot-card${importance ? " is-important" : ""}`} style={{ "--accent": plot.accent } as React.CSSProperties} onClick={onOpen}>
    {importance && <span className={`plot-card-ribbon${plot.climax ? " is-climax" : ""}`} aria-label={`${importance}剧情`}>{importance}</span>}
    <div className="plot-card-index">{String(plot.sequence).padStart(2, "0")}</div>
    <div className="card-meta">
      <span className="plot-card-meta-item" style={{ "--tag-color": chapterColor } as React.CSSProperties} aria-label={`篇章 ${chapterLabel}`} title={`篇章：${chapterLabel}`}><Icon name="book" /><strong>{chapterLabel}</strong></span>
      <span className="plot-card-meta-item" style={{ "--tag-color": statusColor } as React.CSSProperties} aria-label={`状态 ${plot.status || "未标记"}`} title={`状态：${plot.status || "未标记"}`}><Icon name="filter" /><strong>{plot.status || "未标记"}</strong></span>
    </div>
    <div className="plot-card-copy"><CompleteBlockPreview source={preview} className="plot-card-preview content-card-preview" /></div>
    <div className="metadata-tags">{plot.tags.map((tag) => <span key={tag} style={tagStyle(tag)}>{tag}</span>)}</div>
    <button className="card-arrow" aria-label={`阅读${plot.title}`}><Icon name="arrow" /></button>
  </article>;
}

function PlotEditor({ plotId, onClose }: { plotId: string | "new"; onClose: () => void }) {
  const { api, project, snapshot, writable, meta } = useRuntime();
  const mutation = useProjectMutation();
  const queryClient = useQueryClient();
  const [currentId, setCurrentId] = useState<string | "new">(plotId);
  const [initialChapterId] = useState(() => snapshot.chapters[0]?.entityId || "");
  const [initialChapterNumber] = useState(() => Math.max(0, ...snapshot.plots.map((plot) => plotChapterNumber(plot.title, plot.sequence))) + 1);
  const detail = useQuery({
    queryKey: ["entity", project, currentId],
    queryFn: () => api.detail<Plot>(currentId),
    enabled: currentId !== "new",
  });
  const [draft, setDraft] = useState<PlotDraft>({ ...emptyDraft, chapterId: initialChapterId, chapterNumber: String(initialChapterNumber) });
  const [baseline, setBaseline] = useState("");
  const [confirmClose, setConfirmClose] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [convertConfirm, setConvertConfirm] = useState(false);
  const [duplicateConfirm, setDuplicateConfirm] = useState(false);
  const [chapterErrorPulse, setChapterErrorPulse] = useState(0);
  const [message, setMessage] = useState("");
  const draftKey = browserDraftKey(project, "plot", currentId);
  const supportsConversion = Boolean(
    meta?.routes.contentConversion || meta?.features.includes("content-conversion-v1")
  );
  const supportsAppearancePeople = Boolean(
    meta?.routes.appearancePeople || meta?.features.includes("appearance-people-v1")
  );

  useEffect(() => {
    if (currentId === "new") {
      const next = { ...emptyDraft, chapterId: initialChapterId, chapterNumber: String(initialChapterNumber) };
      setDraft(restoreBrowserDraft(browserDraftKey(project, "plot", currentId), next));
      setBaseline(JSON.stringify(next));
    } else if (detail.data?.data) {
      const next = draftFrom(detail.data.data);
      setDraft(restoreBrowserDraft(browserDraftKey(project, "plot", currentId), next));
      setBaseline(JSON.stringify(next));
    }
  }, [currentId, detail.data, initialChapterId, initialChapterNumber, project]);
  useBrowserDraft(draftKey, draft, baseline);

  const dirty = Boolean(baseline && JSON.stringify(draft) !== baseline);
  const close = () => dirty ? setConfirmClose(true) : onClose();
  const change = <K extends keyof PlotDraft>(key: K, value: PlotDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const changeStoryPositionMode = (mode: PlotDraft["storyPositionMode"]) => setDraft((current) => ({
    ...current,
    storyPositionMode: mode,
    storyAnchorPlotId: (mode === "before" || mode === "after")
      ? (current.storyAnchorPlotId || storyAnchorOptions[0]?.entityId || "")
      : current.storyAnchorPlotId,
  }));
  const chapterNumber = Number(draft.chapterNumber);
  const chapterNumberIsValid = draft.chapterNumber.trim() !== ""
    && Number.isInteger(chapterNumber)
    && chapterNumber >= 1
    && chapterNumber <= 99999;
  const currentChapterTitle = chapterNumberIsValid ? plotChapterTitle(chapterNumber) : "未设置章号";
  const storyAnchorOptions = snapshot.plots.filter((item) => item.entityId !== currentId);
  const rejectInvalidChapter = () => {
    setChapterErrorPulse((current) => current + 1);
    setMessage("请填写 1 至 99999 之间的整数章号");
  };
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
  const persist = async (shiftFollowing: boolean) => {
    if (!writable || mutation.isPending) return;
    if (!chapterNumberIsValid) {
      rejectInvalidChapter();
      return;
    }
    setMessage("");
    try {
      const title = plotChapterTitle(chapterNumber);
      const { chapterNumber: _chapterNumberText, ...draftFields } = draft;
      const appearanceText = `${draft.summary}\n${draft.body}`;
      const missingNames = missingAppearanceNames(draft.appearanceNames, appearanceText);
      if (missingNames.length) {
        setMessage(`出场人物“${missingNames[0]}”没有出现在当前正文中`);
        return;
      }
      const people = supportsAppearancePeople
        ? detectedCharacterIds(snapshot.characters, appearanceText, draft.people)
        : draft.people;
      const characterIds = new Set(snapshot.characters.map((item) => item.entityId));
      const references = [
        ...draft.references.filter((identifier) => !characterIds.has(identifier)),
        ...people,
      ];
      const payload = {
        ...draftFields,
        people,
        references,
        chapterNumber,
        title,
        shiftFollowing,
      } as unknown as Record<string, unknown>;
      if (!supportsAppearancePeople) delete payload.appearanceNames;
      const result = await mutation.mutateAsync({
        path: currentId === "new" ? "/plots" : `/plots/${encodeURIComponent(currentId)}`,
        method: currentId === "new" ? "POST" : "PATCH",
        payload,
      });
      clearBrowserDraft(draftKey);
      const changedPlot = result.changed.plots?.find((plot) => (
        plot.entityId === currentId
        || (currentId === "new" && !snapshot.plots.some((existing) => existing.entityId === plot.entityId))
      ));
      const savedDraft = {
        ...draft,
        people: Array.isArray(changedPlot?.people) ? changedPlot.people.map(String) : draft.people,
        appearanceNames: [],
        references: [
          ...references.filter((identifier) => !characterIds.has(identifier)),
          ...(Array.isArray(changedPlot?.people) ? changedPlot.people.map(String) : people),
        ],
      };
      if (currentId === "new") {
        const created = changedPlot;
        if (created?.entityId) setCurrentId(String(created.entityId));
      } else {
        queryClient.setQueryData<EntityDetail<Plot>>(["entity", project, currentId], (current) => current ? {
          ...current,
          title,
          data: { ...current.data, ...draftFields, people: savedDraft.people, title },
        } : current);
      }
      setDraft(savedDraft);
      setBaseline(JSON.stringify(savedDraft));
      setMessage(result.warnings[0] || "已保存");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    }
  };
  const save = async () => {
    if (!chapterNumberIsValid) {
      rejectInvalidChapter();
      return;
    }
    const duplicate = snapshot.plots.some((plot) => (
      plot.entityId !== currentId
      && plotChapterNumber(plot.title, plot.sequence) === chapterNumber
    ));
    if (duplicate) {
      setDuplicateConfirm(true);
      return;
    }
    await persist(false);
  };
  const remove = async () => {
    if (currentId === "new") return;
    try {
      await mutation.mutateAsync({ path: `/entities/${encodeURIComponent(currentId)}`, method: "DELETE", payload: {} });
      clearBrowserDraft(draftKey);
      onClose();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
    }
  };
  const requestConvert = () => {
    if (dirty) {
      setMessage("请先保存当前修改，再放入碎片箱");
      return;
    }
    setConvertConfirm(true);
  };
  const convertToFragment = async () => {
    if (currentId === "new") return;
    try {
      await mutation.mutateAsync({
        path: `/plots/${encodeURIComponent(currentId)}/to-fragment`,
        method: "POST",
        payload: {},
      });
      useUiStore.getState().selectPlot(null);
      useUiStore.getState().showNotice("已放入碎片箱，原剧情可在回收站恢复", "success");
      onClose();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "放入碎片失败");
      setConvertConfirm(false);
    }
  };
  useEditorSaveShortcut(save);
  const discard = () => {
    clearBrowserDraft(draftKey);
    onClose();
  };
  if (plotId !== "new" && detail.isPending) return <div className="dialog-backdrop"><div className="editor-dialog loading-dialog">正在读取正文…</div></div>;
  return (
    <div className="dialog-backdrop editor-backdrop" role="presentation">
      <section className="editor-dialog" role="dialog" aria-modal="true" aria-label={currentId === "new" ? "写新剧情" : `编辑${currentChapterTitle}`}>
        <header className="dialog-header">
          <div><small>{currentId === "new" ? "New Story" : "Story Editor"}</small><h2>{currentId === "new" ? "写新剧情" : currentChapterTitle}</h2></div>
          <div className="dialog-actions">
            {currentId !== "new" && writable && supportsConversion && <button className="icon-button" aria-label="放入碎片箱" title="放入碎片箱" onClick={requestConvert}><Icon name="replace" /></button>}
            {currentId !== "new" && writable && <button className="icon-button is-danger" aria-label="删除剧情" title="删除剧情" onClick={() => setDeleteConfirm(true)}><Icon name="trash" /></button>}
            <button className="icon-button" aria-label="关闭" title="关闭" onClick={close}><Icon name="close" /></button>
          </div>
        </header>
        <EditorSettingsSection label="剧情设置">
          <label><span>章节</span><span key={chapterErrorPulse} className={`chapter-number-field${chapterErrorPulse ? " is-invalid-pulse" : ""}`}>第 <input type="number" min="1" max="99999" step="1" aria-label="章号" aria-invalid={!chapterNumberIsValid} value={draft.chapterNumber} onChange={(event) => change("chapterNumber", event.target.value)} /> 章</span></label>
          <label><span>篇</span><select value={draft.chapterId} onChange={(event) => change("chapterId", event.target.value)}><option value="">主线</option>{snapshot.chapters.map((item) => <option key={item.entityId} value={item.entityId}>{item.label}</option>)}</select></label>
          <label className="wide"><span>故事时间位置</span><select value={draft.storyPositionMode} onChange={(event) => changeStoryPositionMode(event.target.value as PlotDraft["storyPositionMode"])}><option value="follow_reading">按阅读顺序（正序自动同步）</option><option value="before">发生在某剧情之前</option><option value="after">发生在某剧情之后</option><option value="fixed">指定故事位置</option></select></label>
          {(draft.storyPositionMode === "before" || draft.storyPositionMode === "after") && <label className="wide"><span>{draft.storyPositionMode === "before" ? "发生在" : "发生在"}</span><select value={draft.storyAnchorPlotId} onChange={(event) => change("storyAnchorPlotId", event.target.value)}><option value="">选择参考剧情</option>{storyAnchorOptions.map((item) => <option key={item.entityId} value={item.entityId}>第 {item.sequence} 章 · {item.title}</option>)}</select><small>{draft.storyPositionMode === "before" ? "之前" : "之后"}</small></label>}
          {draft.storyPositionMode === "fixed" && <label className="wide"><span>故事位置</span><input inputMode="numeric" value={draft.storySortKey} onChange={(event) => change("storySortKey", event.target.value.replace(/\D/g, ""))} placeholder="填写故事时间序号" /><small>数字越小，故事发生得越早</small></label>}
          <label><span>状态</span><select value={draft.status} onChange={(event) => change("status", event.target.value)}>{plotStatusOptions(draft.status).map((status) => <option key={status} value={status}>{status}</option>)}</select></label>
          <label><span>强调色</span><input type="color" value={draft.accent} onChange={(event) => change("accent", event.target.value)} /></label>
          <label className="wide"><span>摘要</span><input value={draft.summary} onChange={(event) => change("summary", event.target.value)} /></label>
          <label className="wide"><span>标签（逗号分隔）</span><input value={draft.tags.join("，")} onChange={(event) => change("tags", event.target.value.split(/[，,]/).map((item) => item.trim()).filter(Boolean))} /></label>
          {supportsAppearancePeople && <AppearancePeopleField
            characters={snapshot.characters}
            text={`${draft.summary}\n${draft.body}`}
            people={draft.people}
            appearanceNames={draft.appearanceNames}
            onPeopleChange={(people) => change("people", people)}
            onAppearanceNamesChange={(names) => change("appearanceNames", names)}
          />}
          <label className="check"><input type="checkbox" checked={draft.key} onChange={(event) => change("key", event.target.checked)} />关键剧情</label>
          <label className="check"><input type="checkbox" checked={draft.climax} onChange={(event) => change("climax", event.target.checked)} />高潮剧情</label>
        </EditorSettingsSection>
        <MarkdownEditor value={draft.body} onChange={(body) => change("body", body)} onSave={save} characters={snapshot.characters} entries={snapshot.entries} sourceEntityId={currentId === "new" ? undefined : currentId} onReference={addReference} autoFocus />
        <footer className="editor-footer"><span className={dirty ? "is-dirty" : ""}>{message || (dirty ? "未保存修改已暂存在浏览器" : "已保存")}</span><small>@ 选择人物 · / 选择设定 · ⌘/Ctrl+S 保存</small></footer>
      </section>
      <ConfirmDialog open={confirmClose} title="放弃未保存修改？" message="确认放弃后，浏览器中的这份剧情草稿也会被删除。" confirmLabel="放弃修改" danger onCancel={() => setConfirmClose(false)} onConfirm={discard} />
      <ConfirmDialog open={deleteConfirm} title={`删除“${currentChapterTitle}”？`} message="剧情会进入回收站保留 7 天；原有稳定 ID 和阅读位置不会立即清除。" confirmLabel="移入回收站" danger onCancel={() => setDeleteConfirm(false)} onConfirm={remove} />
      <ConfirmDialog open={convertConfirm} title={`把“${currentChapterTitle}”放入碎片箱？`} message="正文、标签、颜色和引用会迁移到新碎片；原剧情会进入回收站，整次操作可以撤销。" confirmLabel="放入碎片箱" onCancel={() => setConvertConfirm(false)} onConfirm={convertToFragment} />
      <ConfirmDialog open={duplicateConfirm} title={`${currentChapterTitle}已经存在`} message="你可以继续编辑并重新填写章号，或者插入到这个位置，将这一章及后面的章节依次顺延。" confirmLabel="插入并顺延后续章节" onCancel={() => setDuplicateConfirm(false)} onConfirm={async () => { setDuplicateConfirm(false); await persist(true); }} />
    </div>
  );
}

export default function StoryPage() {
  const { snapshot, writable } = useRuntime();
  const selectedPlotId = useUiStore((state) => state.selectedPlotId);
  const selectPlot = useUiStore((state) => state.selectPlot);
  const [editorId, setEditorId] = useState<string | "new" | null>(null);
  const [readerId, setReaderId] = useState<string | null>(selectedPlotId);
  const storyReturnCharacterId = useUiStore((state) => state.storyReturnCharacterId);
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
  useEffect(() => { if (chapter && chapter !== "__mainline__" && !snapshot.chapters.some((item) => item.entityId === chapter)) setChapter(""); }, [chapter, snapshot.chapters]);
  useEffect(() => {
    if (!selectedPlotId) return;
    setReaderId(selectedPlotId);
  }, [selectedPlotId]);
  useEffect(() => setPage(1), [chapter, selectedStatuses.join("\0"), selectedTags.join("\0")]);
  const filteredPlots = snapshot.plots.filter((plot) =>
    (!chapter || (chapter === "__mainline__" ? !plot.chapterId : plot.chapterId === chapter)) && selectedStatuses.includes(plot.status) &&
    (selectedTags.length === tags.length || plot.tags.some((tag) => selectedTags.includes(tag))),
  );
  const totalPages = Math.max(1, Math.ceil(filteredPlots.length / 9));
  const plots = filteredPlots.slice((Math.min(page, totalPages) - 1) * 9, Math.min(page, totalPages) * 9);
  const open = (id: string) => { storyScrollRef.current = window.scrollY; selectPlot(id); setReaderId(id); };
  const closeReader = () => {
    useUiStore.getState().clearStoryReturn();
    selectPlot(null);
    setReaderId(null);
    requestAnimationFrame(() => window.scrollTo({ top: storyScrollRef.current, behavior: "auto" }));
  };
  const returnToCharacter = () => {
    if (!storyReturnCharacterId) return;
    const returnId = storyReturnCharacterId;
    selectPlot(null);
    setReaderId(null);
    useUiStore.getState().selectCharacter(returnId);
    useUiStore.getState().navigate("characters");
  };
  const navigateReader = (id: string) => { selectPlot(id); setReaderId(id); };
  const readerPlot = snapshot.plots.find((item) => item.entityId === readerId);
  const returnCharacter = snapshot.characters.find((item) => item.entityId === storyReturnCharacterId);
  const readingOrder = useMemo(() => [...snapshot.plots].sort((left, right) => left.sequence - right.sequence), [snapshot.plots]);
  const readerIndex = readerPlot ? readingOrder.findIndex((item) => item.entityId === readerPlot.entityId) : -1;
  if (readerPlot) return <>
    <StoryReader
      plot={readerPlot}
      previous={readerIndex > 0 ? readingOrder[readerIndex - 1] : undefined}
      next={readerIndex >= 0 && readerIndex < readingOrder.length - 1 ? readingOrder[readerIndex + 1] : undefined}
      onBack={closeReader}
      originBackLabel={returnCharacter ? `返回${returnCharacter.name}` : undefined}
      onOriginBack={returnToCharacter}
      onNavigate={navigateReader}
      onEdit={writable ? () => setEditorId(readerPlot.entityId) : undefined}
    />
    {editorId && <PlotEditor plotId={editorId} onClose={() => setEditorId(null)} />}
  </>;
  return (
    <section className="workspace-page story-page">
      <header className="page-header"><div><small>{snapshot.project.eyebrow || "Story Teller"}</small><h1>{snapshot.project.title}</h1></div><div className="page-actions"><select aria-label="篇章筛选" value={chapter} onChange={(event) => setChapter(event.target.value)}><option value="">所有篇</option><option value="__mainline__">主线</option>{snapshot.chapters.map((item) => <option key={item.entityId} value={item.entityId}>{item.label}</option>)}</select>{writable && <><button className="icon-button" aria-label="编辑篇章与阅读顺序" title="编辑篇章与阅读顺序" onClick={() => setStructureEditor(true)}><Icon name="settings" /></button><button className="icon-button is-primary" aria-label="写新剧情" title="写新剧情" onClick={() => setEditorId("new")}><Icon name="plus" /></button></>}</div></header>
      <div className="filter-panel"><FilterChips label="状态" values={statuses} selected={selectedStatuses} onChange={setSelectedStatuses} /><FilterChips label="标签" values={tags} selected={selectedTags} onChange={setSelectedTags} collapsible inlineExpanded /></div>
      <div className="plot-grid">{plots.map((plot) => <PlotCard
        key={plot.entityId}
        plot={plot}
        chapterLabel={snapshot.chapters.find((item) => item.entityId === plot.chapterId)?.label || "主线"}
        onOpen={() => open(plot.entityId)}
      />)}</div>
      <Pagination page={Math.min(page, totalPages)} totalPages={totalPages} onChange={setPage} />
      {!plots.length && <div className="empty-state"><Icon name="book" /><h2>当前筛选下没有剧情</h2><p>调整状态、标签或篇章后再看。</p></div>}
      {editorId && <PlotEditor plotId={editorId} onClose={() => setEditorId(null)} />}
      {structureEditor && <StoryStructureEditor onClose={() => setStructureEditor(false)} />}
    </section>
  );
}
