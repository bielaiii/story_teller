import { Fragment as ReactFragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Fragment } from "../api/types";
import { useProjectMutation, useRuntime } from "../api/runtime";
import type { PickedReference } from "../editor/MarkdownEditor";
import { DeferredMarkdownEditor as MarkdownEditor } from "../editor/DeferredMarkdownEditor";
import { browserDraftKey, clearBrowserDraft, restoreBrowserDraft, useBrowserDraft } from "../editor/browserDraft";
import { useEditorSaveShortcut } from "../editor/useEditorSaveShortcut";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { AppearancePeopleField, detectedCharacterIds, missingAppearanceNames } from "../components/AppearancePeopleField";
import { CompleteBlockPreview } from "../components/CompleteBlockPreview";
import { EditorSettingsSection } from "../components/EditorSettingsSection";
import { FilterChips } from "../components/FilterChips";
import { Icon } from "../components/Icon";
import { ReadOnlyArticle } from "../components/ReadOnlyArticle";
import { Pagination } from "../components/Pagination";
import { useUiStore } from "../state/ui";
import { plotChapterNumber } from "../storyOptions";

interface Draft {
  stableId: string;
  title: string;
  body: string;
  status: string;
  accent: string;
  tags: string[];
  people: string[];
  appearanceNames: string[];
  references: string[];
  fragmentType: "chapter" | "line";
  parentFragmentId: string | null;
  fragmentOrder: number;
  chapterNumber: number | null;
  plotChapterPlan: Record<string, number>;
}
const blank: Draft = {
  stableId: "",
  title: "",
  body: "",
  status: "灵感",
  accent: "#d65f8f",
  tags: [],
  people: [],
  appearanceNames: [],
  references: [],
  fragmentType: "chapter",
  parentFragmentId: null,
  fragmentOrder: 0,
  chapterNumber: null,
  plotChapterPlan: {},
};
const FRAGMENTS_PER_PAGE = 9;

export function fragmentTypeOf(item: Fragment): "chapter" | "line" {
  return item.fragmentType === "line" || item.extra?.fragmentType === "line" ? "line" : "chapter";
}

export function fragmentParentOf(item: Fragment): string | null {
  const value = item.parentFragmentId ?? item.extra?.parentFragmentId;
  return typeof value === "string" && value ? value : null;
}

export function fragmentChapterNumberOf(item: Fragment): number | null {
  const direct = item.chapterNumber ?? item.extra?.chapterNumber;
  if (typeof direct === "number" && Number.isInteger(direct) && direct > 0) return direct;
  const legacy = item.title.match(/^第\s*(\d+)\s*章(?:\s*[：:·—-]\s*|\s+)/);
  if (legacy) return Number(legacy[1]);
  const parentId = fragmentParentOf(item);
  const order = item.fragmentOrder ?? Number(item.extra?.fragmentOrder);
  return parentId && Number.isFinite(order) ? order + 1 : null;
}

export function fragmentPlotChapterPlanOf(item: Fragment): Record<string, number> {
  const value = item.plotChapterPlan ?? item.extra?.plotChapterPlan;
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value).filter((entry): entry is [string, number] =>
      typeof entry[1] === "number"
      && Number.isInteger(entry[1])
      && entry[1] >= 1
      && entry[1] <= 99999
    ),
  );
}

export function fragmentDisplayTitle(item: Fragment): string {
  return fragmentParentOf(item)
    ? item.title.replace(/^第\s*\d+\s*章(?:\s*[：:·—-]\s*|\s+)/, "").trim() || item.title
    : item.title;
}

export function groupFragments(items: Fragment[]) {
  const lines = new Set(items.filter((item) => fragmentTypeOf(item) === "line").map((item) => item.entityId));
  const children = new Map<string, Fragment[]>();
  for (const item of items) {
    const parentId = fragmentParentOf(item);
    if (fragmentTypeOf(item) !== "chapter" || !parentId || !lines.has(parentId)) continue;
    children.set(parentId, [...(children.get(parentId) || []), item]);
  }
  for (const values of children.values()) {
    values.sort((left, right) =>
      (fragmentChapterNumberOf(left) ?? Number.MAX_SAFE_INTEGER)
      - (fragmentChapterNumberOf(right) ?? Number.MAX_SAFE_INTEGER)
      || (left.fragmentOrder ?? (Number(left.extra?.fragmentOrder) || 0))
      - (right.fragmentOrder ?? (Number(right.extra?.fragmentOrder) || 0))
      || left.id.localeCompare(right.id)
    );
  }
  const topLevel = items.filter((item) =>
    fragmentTypeOf(item) === "line" || !fragmentParentOf(item) || !lines.has(fragmentParentOf(item) as string)
  );
  return { topLevel, children };
}

export function fragmentWorkspaceLineId(
  items: Fragment[],
  entityId: string | "new",
  initialParentId: string | null = null,
): string | null {
  const item = items.find((candidate) => candidate.entityId === entityId);
  if (item && fragmentTypeOf(item) === "line") return item.entityId;
  return item ? fragmentParentOf(item) : initialParentId;
}

export async function readClipboardText(
  readText: (() => Promise<string>) | undefined,
): Promise<string | null> {
  if (!readText) return null;
  try {
    return await readText();
  } catch {
    return null;
  }
}

function FragmentEditor({
  entityId,
  initialParentId = null,
  onClose,
}: {
  entityId: string | "new";
  initialParentId?: string | null;
  onClose: () => void;
}) {
  const { api, project, snapshot, meta } = useRuntime();
  const mutation = useProjectMutation();
  const [currentId, setCurrentId] = useState<string | "new">(entityId);
  const [newDraftNonce, setNewDraftNonce] = useState(0);
  const [workspaceLineId, setWorkspaceLineId] = useState<string | null>(() =>
    fragmentWorkspaceLineId(snapshot.fragments, entityId, initialParentId)
  );
  const detail = useQuery({ queryKey: ["entity", project, currentId], queryFn: () => api.detail<Fragment>(currentId), enabled: currentId !== "new" });
  const [draft, setDraft] = useState<Draft>(blank);
  const [baseline, setBaseline] = useState("");
  const [message, setMessage] = useState("");
  const [confirmClose, setConfirmClose] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmConvertId, setConfirmConvertId] = useState<string | null>(null);
  const draftKey = browserDraftKey(project, "fragment", currentId);
  const supportsConversion = Boolean(
    meta?.routes.contentConversion || meta?.features.includes("content-conversion-v1")
  );
  const supportsStacks = Boolean(
    meta?.routes.fragmentStacks || meta?.features.includes("fragment-stacks-v1")
  );
  const supportsPlotPlanning = Boolean(
    meta?.routes.fragmentPlotPlanning || meta?.features.includes("fragment-plot-planning-v1")
  );
  const supportsAppearancePeople = Boolean(
    meta?.routes.appearancePeople || meta?.features.includes("appearance-people-v1")
  );
  const workspaceLine = snapshot.fragments.find((item) => item.entityId === workspaceLineId);
  const activeWorkspaceChapter = snapshot.fragments.find((item) => item.entityId === currentId);
  const lineWorkspaceActive = Boolean(workspaceLineId)
    || (currentId === "new" && draft.fragmentType === "line");
  const workspaceChapters = workspaceLineId
    ? groupFragments(snapshot.fragments).children.get(workspaceLineId) || []
    : [];
  const effectiveNewParentId = workspaceLineId || initialParentId;
  const nextOrderFor = (parentId: string | null) => {
    if (!parentId) return 0;
    const siblingOrders = snapshot.fragments
      .filter((item) => fragmentParentOf(item) === parentId && item.entityId !== currentId)
      .map((item) => item.fragmentOrder ?? (Number(item.extra?.fragmentOrder) || 0));
    return Math.max(-1, ...siblingOrders) + 1;
  };
  const nextChapterNumberFor = (parentId: string | null) => {
    if (!parentId) return null;
    const siblingNumbers = snapshot.fragments
      .filter((item) => fragmentParentOf(item) === parentId && item.entityId !== currentId)
      .map(fragmentChapterNumberOf)
      .filter((value): value is number => value !== null);
    return Math.max(0, ...siblingNumbers) + 1;
  };
  useEffect(() => {
    const item = detail.data?.data;
    const next = currentId === "new"
      ? {
        ...blank,
        parentFragmentId: effectiveNewParentId,
        fragmentOrder: nextOrderFor(effectiveNewParentId),
        chapterNumber: nextChapterNumberFor(effectiveNewParentId),
      }
      : item ? {
        stableId: item.id,
        title: fragmentDisplayTitle(item),
        body: item.body || "",
        status: item.status,
        accent: item.accent,
        tags: [...item.tags],
        people: (item.references || []).filter((identifier) =>
          snapshot.characters.some((character) => character.entityId === identifier)
        ),
        appearanceNames: [],
        references: [...(item.references || [])],
        fragmentType: fragmentTypeOf(item),
        parentFragmentId: fragmentParentOf(item),
        fragmentOrder: item.fragmentOrder ?? (Number(item.extra?.fragmentOrder) || 0),
        chapterNumber: fragmentChapterNumberOf(item),
        plotChapterPlan: fragmentTypeOf(item) === "line" ? fragmentPlotChapterPlanOf(item) : {},
      } : null;
    if (next) {
      setDraft(restoreBrowserDraft(browserDraftKey(project, "fragment", currentId), next));
      setBaseline(JSON.stringify(next));
    }
  }, [currentId, detail.data, effectiveNewParentId, newDraftNonce, project]);
  useBrowserDraft(draftKey, draft, baseline);
  const dirty = Boolean(baseline && JSON.stringify(draft) !== baseline);
  const change = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const addReference = (reference: PickedReference) => setDraft((current) => ({
    ...current,
    people: reference.kind === "character" && !current.people.includes(reference.entityId)
      ? [...current.people, reference.entityId]
      : current.people,
    references: current.references.includes(reference.entityId)
      ? current.references
      : [...current.references, reference.entityId],
  }));
  const save = async (): Promise<string | null> => {
    if (draft.fragmentType === "line") {
      const plannedNumbers = Object.values(draft.plotChapterPlan);
      if (new Set(plannedNumbers).size !== plannedNumbers.length) {
        setMessage("同一个正式剧情章号不能分配给多个碎片章节");
        return null;
      }
    }
    try {
      const missingNames = missingAppearanceNames(draft.appearanceNames, draft.body);
      if (draft.fragmentType === "chapter" && missingNames.length) {
        setMessage(`出场人物“${missingNames[0]}”没有出现在当前正文中`);
        return null;
      }
      const people = supportsAppearancePeople && draft.fragmentType === "chapter"
        ? detectedCharacterIds(snapshot.characters, draft.body, draft.people)
        : draft.people;
      const characterIds = new Set(snapshot.characters.map((item) => item.entityId));
      const references = [
        ...draft.references.filter((identifier) => !characterIds.has(identifier)),
        ...people,
      ];
      const payload = {
        ...draft,
        people,
        references,
      } as unknown as Record<string, unknown>;
      if (!supportsAppearancePeople || draft.fragmentType === "line") {
        delete payload.appearanceNames;
        delete payload.people;
      }
      if (draft.fragmentType === "chapter" && draft.parentFragmentId) {
        payload.shiftFollowing = true;
      }
      if (currentId !== "new") delete payload.stableId;
      if (draft.fragmentType !== "line") delete payload.plotChapterPlan;
      if (!supportsPlotPlanning) delete payload.plotChapterPlan;
      if (!supportsStacks) {
        delete payload.fragmentType;
        delete payload.parentFragmentId;
        delete payload.fragmentOrder;
        delete payload.chapterNumber;
        delete payload.plotChapterPlan;
        delete payload.shiftFollowing;
      }
      const result = await mutation.mutateAsync({ path: currentId === "new" ? "/fragments" : `/fragments/${encodeURIComponent(currentId)}`, method: currentId === "new" ? "POST" : "PATCH", payload });
      clearBrowserDraft(draftKey);
      const createdPeople = (result.changed.characters || [])
        .filter((character) => draft.appearanceNames.includes(String(character.name || "")))
        .map((character) => String(character.entityId));
      const savedPeople = [...new Set([...people, ...createdPeople])];
      const savedDraft = {
        ...draft,
        people: savedPeople,
        appearanceNames: [],
        references: [
          ...references.filter((identifier) => !characterIds.has(identifier)),
          ...savedPeople,
        ],
      };
      let savedId = currentId === "new" ? null : currentId;
      if (currentId === "new") {
        const created = result.changed.fragments?.find((item) => !snapshot.fragments.some((existing) => existing.entityId === item.entityId));
        if (created?.entityId) {
          const createdId = String(created.entityId);
          savedId = createdId;
          if (draft.fragmentType === "line") setWorkspaceLineId(createdId);
          else if (draft.parentFragmentId) setWorkspaceLineId(draft.parentFragmentId);
          setCurrentId(createdId);
        }
      }
      setDraft(savedDraft);
      setBaseline(JSON.stringify(savedDraft)); setMessage(result.warnings[0] || "已保存");
      return savedId;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
      return null;
    }
  };
  const remove = async () => {
    if (currentId === "new") return;
    try {
      await mutation.mutateAsync({ path: `/entities/${encodeURIComponent(currentId)}`, method: "DELETE", payload: {} });
      clearBrowserDraft(draftKey);
      setConfirmDelete(false);
      if (workspaceLineId && currentId !== workspaceLineId) {
        setCurrentId(workspaceLineId);
        setMessage("章节已移入回收站");
      } else {
        onClose();
      }
    }
    catch (error) { setMessage(error instanceof Error ? error.message : "删除失败"); }
  };
  const requestConvert = (targetId: string | "new" = currentId) => {
    if (targetId === "new") return;
    if (targetId === currentId && dirty) {
      setMessage("请先保存当前修改，再放入剧情");
      return;
    }
    setConfirmConvertId(targetId);
  };
  const convertToPlot = async () => {
    const targetId = confirmConvertId;
    if (!targetId) return;
    const keepLineWorkspaceOpen = targetId !== currentId && currentId === workspaceLineId;
    try {
      if (keepLineWorkspaceOpen && dirty && !await save()) return;
      const result = await mutation.mutateAsync({
        path: `/fragments/${encodeURIComponent(targetId)}/to-plot`,
        method: "POST",
        payload: {},
      });
      const created = result.changed.plots?.find((item) =>
        !snapshot.plots.some((existing) => existing.entityId === item.entityId)
      );
      setConfirmConvertId(null);
      useUiStore.getState().showNotice(
        created?.title
          ? `已放入正式剧情 ${created.title}，原碎片可在回收站恢复`
          : "已放入正式剧情，原碎片可在回收站恢复",
        "success",
      );
      if (keepLineWorkspaceOpen) {
        const plotChapterPlan = { ...draft.plotChapterPlan };
        delete plotChapterPlan[targetId];
        const nextDraft = { ...draft, plotChapterPlan };
        setDraft(nextDraft);
        setBaseline(JSON.stringify(nextDraft));
        clearBrowserDraft(draftKey);
        setMessage(created?.title ? `已转正为${created.title}` : "章节已转正");
      } else {
        onClose();
        if (created?.entityId) useUiStore.getState().selectPlot(String(created.entityId));
        useUiStore.getState().navigate("story");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "放入剧情失败");
      setConfirmConvertId(null);
    }
  };
  useEditorSaveShortcut(() => { void save(); });
  const discard = () => {
    clearBrowserDraft(draftKey);
    onClose();
  };
  const selectWorkspaceDocument = (nextId: string | "new") => {
    if (nextId === currentId) return;
    if (dirty) {
      setMessage("请先保存当前修改，再切换章节");
      return;
    }
    setMessage("");
    setCurrentId(nextId);
  };
  const writeNextChapter = async () => {
    if (workspaceLineId) {
      selectWorkspaceDocument("new");
      return;
    }
    if (draft.fragmentType !== "line") return;
    if (!draft.title.trim()) {
      setMessage("请先填写剧情线标题");
      return;
    }
    const createdLineId = await save();
    if (!createdLineId) return;
    setWorkspaceLineId(createdLineId);
    setCurrentId("new");
    setNewDraftNonce((value) => value + 1);
  };
  const updatePlotChapterPlan = (chapterId: string, rawValue: string) => {
    setDraft((current) => {
      const plotChapterPlan = { ...current.plotChapterPlan };
      if (!rawValue) delete plotChapterPlan[chapterId];
      else plotChapterPlan[chapterId] = Math.max(1, Math.min(99999, Math.trunc(Number(rawValue))));
      return { ...current, plotChapterPlan };
    });
  };
  const duplicatePlannedNumbers = new Set(
    Object.values(draft.plotChapterPlan).filter((number, index, values) => values.indexOf(number) !== index),
  );
  const occupiedPlotNumbers = new Set(
    snapshot.plots.map((plot) => plotChapterNumber(plot.title, plot.sequence)),
  );
  const confirmConvertTarget = confirmConvertId
    ? snapshot.fragments.find((item) => item.entityId === confirmConvertId)
    : null;
  const confirmConvertPlannedNumber = confirmConvertId
    ? draft.fragmentType === "line"
      ? draft.plotChapterPlan[confirmConvertId]
      : workspaceLine
        ? fragmentPlotChapterPlanOf(workspaceLine)[confirmConvertId]
        : undefined
    : undefined;
  if (!workspaceLineId && currentId !== "new" && detail.isPending) return <div className="dialog-backdrop"><div className="editor-dialog loading-dialog">正在读取灵感…</div></div>;
  const settingsAndEditor = currentId !== "new" && detail.isPending
    ? <div className="fragment-line-authoring-loading">正在读取章节…</div>
    : <>
    <EditorSettingsSection key={`fragment-settings-${currentId}`} label={draft.fragmentType === "line" ? "剧情线设置" : "章节设置"} defaultOpen={currentId === "new"}>
      {supportsStacks && !workspaceLineId && <div className="fragment-kind-picker wide" aria-label="碎片形态">
        <button type="button" className={draft.fragmentType === "chapter" ? "is-active" : ""} aria-pressed={draft.fragmentType === "chapter"} onClick={() => change("fragmentType", "chapter")}>
          <Icon name="book" /><span><strong>单章故事</strong><small>一张卡直接阅读正文</small></span>
        </button>
        <button type="button" className={draft.fragmentType === "line" ? "is-active" : ""} aria-pressed={draft.fragmentType === "line"} onClick={() => setDraft((current) => ({ ...current, fragmentType: "line", parentFragmentId: null, chapterNumber: null }))}>
          <Icon name="timeline" /><span><strong>整条剧情线</strong><small>在同一工作台编写多章</small></span>
        </button>
      </div>}
      {draft.fragmentType === "chapter" && (workspaceLineId || draft.parentFragmentId) ? <>
        <label><span>章号</span><input type="number" min="1" step="1" value={draft.chapterNumber ?? ""} onChange={(event) => change("chapterNumber", event.target.value ? Math.max(1, Math.trunc(Number(event.target.value))) : null)} /></label>
        <label className="wide"><span>章节标题</span><input value={draft.title} onChange={(event) => change("title", event.target.value)} /></label>
      </> : <label className="wide"><span>{draft.fragmentType === "line" ? "剧情线标题" : "章节标题"}</span><input value={draft.title} onChange={(event) => change("title", event.target.value)} /></label>}
      <label><span>状态</span><input value={draft.status} onChange={(event) => change("status", event.target.value)} /></label>
      <label><span>颜色</span><input type="color" value={draft.accent} onChange={(event) => change("accent", event.target.value)} /></label>
      <label className="wide"><span>标签</span><input value={draft.tags.join("，")} onChange={(event) => change("tags", event.target.value.split(/[，,]/).map((value) => value.trim()).filter(Boolean))} /></label>
      {supportsAppearancePeople && draft.fragmentType === "chapter" && <AppearancePeopleField
        characters={snapshot.characters}
        text={draft.body}
        people={draft.people}
        appearanceNames={draft.appearanceNames}
        onPeopleChange={(people) => change("people", people)}
        onAppearanceNamesChange={(names) => change("appearanceNames", names)}
      />}
    </EditorSettingsSection>
    {draft.fragmentType === "line" && supportsPlotPlanning
      ? <section className="fragment-line-settings-panel">
        <header>
          <span className="fragment-line-settings-mark"><Icon name="timeline" /></span>
          <div><strong>正式剧情位置</strong><p>碎片章号只表示这条灵感线的内部顺序；这里单独规划每章转正后在剧情中的实际章号。</p></div>
          <button className="primary-action" type="button" disabled={!dirty || mutation.isPending || duplicatePlannedNumbers.size > 0} onClick={() => void save()}>{mutation.isPending ? "正在保存…" : "保存设置"}</button>
        </header>
        {workspaceChapters.length > 0 ? <div className="fragment-plot-plan" role="table" aria-label="正式剧情章号规划">
          <div className="fragment-plot-plan-head" role="row">
            <span role="columnheader">碎片线内</span><span role="columnheader">章节</span><span role="columnheader">正式剧情</span><span role="columnheader">操作</span>
          </div>
          {workspaceChapters.map((chapter, index) => {
            const plannedNumber = draft.plotChapterPlan[chapter.entityId];
            const duplicate = plannedNumber !== undefined && duplicatePlannedNumbers.has(plannedNumber);
            const occupied = plannedNumber !== undefined && occupiedPlotNumbers.has(plannedNumber);
            return <div className={`fragment-plot-plan-row${duplicate ? " is-invalid" : ""}`} role="row" key={chapter.entityId}>
              <span className="fragment-plot-plan-source" role="cell"><b>{fragmentChapterNumberOf(chapter) ?? index + 1}</b><small>碎片章号</small></span>
              <span className="fragment-plot-plan-title" role="cell"><strong>{fragmentDisplayTitle(chapter)}</strong><small>{chapter.status || "未设状态"}</small></span>
              <label className="fragment-plot-plan-target" role="cell">
                <span>第</span>
                <input type="number" min="1" max="99999" step="1" aria-label={`${fragmentDisplayTitle(chapter)}的正式剧情章号`} placeholder="未设置" value={plannedNumber ?? ""} onChange={(event) => updatePlotChapterPlan(chapter.entityId, event.target.value)} />
                <span>章</span>
                <small>{duplicate ? "与其他规划重复" : occupied ? "已有剧情占用，转正时向后顺延" : plannedNumber ? "转正时按此位置插入" : "转正时自动追加到末尾"}</small>
              </label>
              <span className="fragment-plot-plan-action" role="cell">
                <button className="icon-button" type="button" aria-label={`把${fragmentDisplayTitle(chapter)}放入剧情`} title="将这一章转正" disabled={duplicate || mutation.isPending} onClick={() => requestConvert(chapter.entityId)}><Icon name="replace" /></button>
              </span>
            </div>;
          })}
        </div> : <div className="fragment-plot-plan-empty"><Icon name="book" /><p>添加章节后，就可以在这里逐章规划正式剧情位置。</p></div>}
        <footer><span>章号可以不连续，也不会改变左侧碎片线的内部顺序。</span><span>发生冲突时，会从目标章开始顺延已有的连续章节。</span></footer>
      </section>
      : draft.fragmentType === "line"
        ? <div className="fragment-line-settings-panel is-legacy">
          <span className="fragment-line-settings-mark"><Icon name="timeline" /></span>
          <div><strong>剧情线设置</strong><p>当前服务版本只能保存剧情线的基础设置。</p></div>
          <button className="primary-action" type="button" disabled={!dirty || mutation.isPending} onClick={() => void save()}>{mutation.isPending ? "正在保存…" : "保存设置"}</button>
        </div>
        : <MarkdownEditor label="章节正文" value={draft.body} onChange={(value) => change("body", value)} onSave={save} characters={snapshot.characters} entries={snapshot.entries} sourceEntityId={currentId === "new" ? undefined : currentId} onReference={addReference} />}
    </>;
  return <div className="dialog-backdrop editor-backdrop">
    <section className={`editor-dialog fragment-editor-dialog${lineWorkspaceActive ? " has-line-workspace" : ""}`} role="dialog" aria-modal="true" aria-label={lineWorkspaceActive ? "编辑整条剧情线" : "写灵感碎片"}>
      <header className="dialog-header">
        <div>
          <small>{lineWorkspaceActive ? "Story Line Workspace" : "Idea Fragment"}</small>
          <h2>{lineWorkspaceActive ? workspaceLine?.title || draft.title || "新剧情线" : currentId === "new" ? "写一条灵感" : draft.title}</h2>
          {lineWorkspaceActive && <p>{!workspaceLineId ? "先保存剧情线设置，再添加章节" : currentId === workspaceLineId ? "剧情线设置" : currentId === "new" ? "设置任意章号；如有重叠，已有章节会自动顺延" : `正在编辑：${activeWorkspaceChapter?.title || draft.title}`}</p>}
        </div>
        <div className="dialog-actions">
          {currentId !== "new" && draft.fragmentType === "chapter" && supportsConversion && <button className="icon-button" aria-label="放入剧情" title="放入剧情" onClick={() => requestConvert()}><Icon name="replace" /></button>}
          {currentId !== "new" && <button className="icon-button is-danger" aria-label={draft.fragmentType === "line" ? "删除剧情线" : "删除碎片"} title={draft.fragmentType === "line" ? "删除整条剧情线" : "删除碎片"} onClick={() => setConfirmDelete(true)}><Icon name="trash" /></button>}
          <button className="icon-button" aria-label="关闭" title="关闭" onClick={() => dirty ? setConfirmClose(true) : onClose()}><Icon name="close" /></button>
        </div>
      </header>
      {lineWorkspaceActive ? <div className="fragment-line-authoring">
        <aside className="fragment-line-authoring-rail">
          <header><div><small>LINE CONTENTS</small><strong>{workspaceChapters.length} 个章节</strong></div>{workspaceLineId && <button type="button" className={`icon-button${currentId === workspaceLineId ? " is-active" : ""}`} aria-label="编辑剧情线设置" title="编辑剧情线设置" onClick={() => selectWorkspaceDocument(workspaceLineId)}><Icon name="edit" /></button>}</header>
          <div className="fragment-line-authoring-list">
            {workspaceChapters.map((chapter, index) => <button type="button" key={chapter.entityId} className={currentId === chapter.entityId ? "is-active" : ""} onClick={() => selectWorkspaceDocument(chapter.entityId)}>
              <span className="fragment-line-authoring-number">{fragmentChapterNumberOf(chapter) ?? index + 1}</span>
              <span><strong>{fragmentDisplayTitle(chapter)}</strong><small>第 {fragmentChapterNumberOf(chapter) ?? index + 1} 章 · {chapter.status || "未设状态"}</small></span>
            </button>)}
          </div>
          <button type="button" className={`fragment-line-authoring-add${workspaceLineId && currentId === "new" ? " is-active" : ""}`} title="可指定任意章号；如有重叠，已有章节自动顺延" onClick={writeNextChapter}>
            <span><Icon name="plus" /></span>{workspaceLineId ? "添加章节" : "添加第一章"}
          </button>
        </aside>
        <div className="fragment-line-authoring-document">{settingsAndEditor}</div>
      </div> : settingsAndEditor}
      <footer className="editor-footer"><span className={dirty ? "is-dirty" : ""}>{message || (dirty ? "未保存修改已暂存在浏览器" : "已保存")}</span><small>可直接在当前尺寸写，也可进入沉浸模式</small></footer>
    </section>
    <ConfirmDialog open={confirmClose} title="放弃未保存修改？" message="确认放弃后，浏览器中的这份灵感草稿也会被删除。" confirmLabel="放弃修改" danger onCancel={() => setConfirmClose(false)} onConfirm={discard} />
    <ConfirmDialog open={confirmDelete} title={`删除“${draft.title}”？`} message={draft.fragmentType === "line" ? workspaceChapters.length ? `剧情线和线内 ${workspaceChapters.length} 个章节会作为一个整体移入回收站；恢复剧情线时会一并恢复。` : "空剧情线会进入回收站保留 7 天。" : "碎片会进入统一回收站保留 7 天。"} confirmLabel={draft.fragmentType === "line" ? "整条移入回收站" : "移入回收站"} danger onCancel={() => setConfirmDelete(false)} onConfirm={remove} />
    <ConfirmDialog open={Boolean(confirmConvertId)} title={`把“${confirmConvertTarget ? fragmentDisplayTitle(confirmConvertTarget) : draft.title}”放入剧情？`} message={confirmConvertPlannedNumber ? `正文、标签、颜色和引用会迁移到正式剧情第 ${confirmConvertPlannedNumber} 章；如该位置已有剧情，后续连续章节会顺延。原碎片会进入回收站，整次操作可以撤销。` : "正文、标签、颜色和引用会迁移到正式剧情末尾的新章节；原碎片会进入回收站，整次操作可以撤销。"} confirmLabel="放入剧情" onCancel={() => setConfirmConvertId(null)} onConfirm={convertToPlot} />
  </div>;
}

export default function FragmentsPage() {
  const { snapshot, writable, api, project, meta } = useRuntime();
  const mutation = useProjectMutation();
  const selectedFragmentId = useUiStore((state) => state.selectedFragmentId);
  const selectFragment = useUiStore((state) => state.selectFragment);
  const tags = useMemo(() => [...new Set(snapshot.fragments.flatMap((item) => item.tags))].sort(), [snapshot.fragments]);
  const [selectedTags, setSelectedTags] = useState<string[]>(tags);
  const [editor, setEditor] = useState<string | "new" | null>(null);
  const [newParentId, setNewParentId] = useState<string | null>(null);
  const [reader, setReader] = useState<string | null>(null);
  const [expandedLines, setExpandedLines] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(1);
  const [clipboardDialog, setClipboardDialog] = useState(false);
  const [clipboardText, setClipboardText] = useState("");
  const [clipboardHint, setClipboardHint] = useState("");
  const paginationScroll = useRef<number | null>(null);
  const supportsClipboardImport = Boolean(
    meta?.routes.fragmentClipboardImport
    || meta?.features.includes("fragment-clipboard-import-v1")
  );
  useEffect(() => setSelectedTags(tags), [tags.join("\0")]);
  useEffect(() => setPage(1), [selectedTags.join("\0")]);
  useEffect(() => {
    if (!selectedFragmentId) return;
    const target = snapshot.fragments.find((item) => item.entityId === selectedFragmentId);
    if (!target) return;
    if (target.parentFragmentId) {
      setExpandedLines((current) => new Set([...current, target.parentFragmentId as string]));
    }
    setReader(target.entityId);
    selectFragment(null);
  }, [selectFragment, selectedFragmentId, snapshot.fragments]);
  const grouped = useMemo(() => groupFragments(snapshot.fragments), [snapshot.fragments]);
  const matchesFilter = (item: Fragment) =>
    selectedTags.length === tags.length || item.tags.some((tag) => selectedTags.includes(tag));
  const filteredFragments = grouped.topLevel.filter((item) =>
    matchesFilter(item)
    || (fragmentTypeOf(item) === "line" && (grouped.children.get(item.entityId) || []).some(matchesFilter))
  );
  const totalPages = Math.max(1, Math.ceil(filteredFragments.length / FRAGMENTS_PER_PAGE));
  const activePage = Math.min(page, totalPages);
  const fragments = filteredFragments.slice((activePage - 1) * FRAGMENTS_PER_PAGE, activePage * FRAGMENTS_PER_PAGE);
  useLayoutEffect(() => {
    if (paginationScroll.current === null) return;
    const top = paginationScroll.current;
    const restore = () => {
      window.scrollTo({ top, left: window.scrollX, behavior: "auto" });
      document.documentElement.scrollTop = top;
      document.body.scrollTop = top;
    };
    restore();
    let secondFrame = 0;
    const firstFrame = requestAnimationFrame(() => {
      restore();
      secondFrame = requestAnimationFrame(restore);
    });
    paginationScroll.current = null;
    return () => {
      cancelAnimationFrame(firstFrame);
      if (secondFrame) cancelAnimationFrame(secondFrame);
    };
  }, [activePage]);
  const changePage = (value: number) => {
    paginationScroll.current = window.scrollY;
    setPage(value);
  };
  const readerItem = snapshot.fragments.find((item) => item.entityId === reader);
  const readerDetail = useQuery({
    queryKey: ["entity", project, reader],
    queryFn: () => api.detail<Fragment>(reader as string),
    enabled: Boolean(reader) && !snapshot.readonly,
  });
  const readerData = snapshot.readonly ? readerItem : readerDetail.data?.data;
  const openNew = (parentId: string | null = null) => {
    setNewParentId(parentId);
    setEditor("new");
  };
  const openClipboardPaste = (hint: string) => {
    setClipboardText("");
    setClipboardHint(hint);
    setClipboardDialog(true);
  };
  const importText = async (text: string) => {
    if (!text.trim()) {
      setClipboardHint("还没有检测到文字，请先粘贴内容。");
      return false;
    }
    try {
      const result = await mutation.mutateAsync({
        path: "/fragments/import-clipboard",
        method: "POST",
        payload: { text },
      });
      const created = (result.changed.fragments || []) as unknown as Fragment[];
      const line = created.find((item) => fragmentTypeOf(item) === "line");
      const chapterCount = line
        ? created.filter((item) => fragmentParentOf(item) === line.entityId).length
        : 1;
      setSelectedTags(tags);
      setPage(Math.max(1, Math.ceil((grouped.topLevel.length + 1) / FRAGMENTS_PER_PAGE)));
      if (line) {
        setExpandedLines((current) => new Set(current).add(line.entityId));
        useUiStore.getState().showNotice(`已从剪贴板生成剧情线和 ${chapterCount} 个章节`, "success");
      } else if (created[0]) {
        setReader(created[0].entityId);
        useUiStore.getState().showNotice("已从剪贴板生成单篇灵感", "success");
      }
      setClipboardDialog(false);
      setClipboardText("");
      return true;
    } catch {
      // useProjectMutation 已经展示服务端给出的解析或保存错误。
      return false;
    }
  };
  const tryReadClipboard = async () => {
    const clipboard = navigator.clipboard;
    const text = await readClipboardText(
      clipboard?.readText ? clipboard.readText.bind(clipboard) : undefined
    );
    if (text === null) {
      setClipboardHint("当前浏览器不允许自动读取。输入区已经聚焦，请直接按 ⌘/Ctrl+V。");
      return;
    }
    if (!text.trim()) {
      setClipboardHint("剪贴板里暂时没有文字，请在下方粘贴要导入的内容。");
      return;
    }
    setClipboardText(text);
    setClipboardHint("已读取剪贴板内容，确认无误后点击“生成灵感”。");
  };
  const importFromClipboard = () => {
    openClipboardPaste("请在下方按 ⌘/Ctrl+V；也可以尝试让浏览器自动读取。");
  };
  const edit = (event: React.MouseEvent, item: Fragment) => {
    event.stopPropagation();
    setNewParentId(null);
    setEditor(item.entityId);
  };
  const chapterCard = (item: Fragment, label: string, compact = false) => <article key={item.entityId} className={`fragment-card-new${compact ? " is-child" : ""}`} role="button" tabIndex={0} style={{ "--accent": item.accent } as React.CSSProperties} onClick={() => setReader(item.entityId)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setReader(item.entityId); }}>
    <div className={`fragment-card-index${compact ? " is-chapter-number" : ""}`}>{label}</div>
    <header>{!compact && !["", "空", "待补充"].includes(item.status) && <span>{item.status}</span>}{writable && <button className="icon-button" aria-label={`编辑${fragmentDisplayTitle(item)}`} title="编辑碎片" onClick={(event) => edit(event, item)}><Icon name="edit" /></button>}</header>
    <div className="fragment-card-copy"><h2>{fragmentDisplayTitle(item)}</h2><CompleteBlockPreview source={item.bodyPreview || "还没有正文"} className="fragment-card-preview content-card-preview" /></div>
    <div className="metadata-tags">{item.tags.map((tag) => <span key={tag} style={{ color: item.accent, borderColor: item.accent }}>{tag}</span>)}</div>
  </article>;
  return <section className="workspace-page fragments-page-new">
    <header className="page-header"><div><small>Idea Inbox</small><h1>灵感碎片箱</h1><p>单章直接阅读，剧情线展开后按章节继续推演。</p></div>{writable && <div className="fragment-page-actions">{supportsClipboardImport && <button className="fragment-import-action" disabled={mutation.isPending} onClick={importFromClipboard}><span><Icon name="clipboard" /></span>{mutation.isPending ? "正在解析…" : "从剪贴板导入"}</button>}<button className="fragment-create-action" onClick={() => openNew()}><span><Icon name="plus" /></span>新建碎片</button></div>}</header>
    {tags.length > 0 && <FilterChips label="标签" values={tags} selected={selectedTags} onChange={setSelectedTags} collapsible />}
    <div className="fragment-grid-new">{fragments.map((item, index) => {
      if (fragmentTypeOf(item) !== "line") {
        return chapterCard(item, String((activePage - 1) * FRAGMENTS_PER_PAGE + index + 1).padStart(2, "0"));
      }
      const children = grouped.children.get(item.entityId) || [];
      const expanded = expandedLines.has(item.entityId);
      const toggle = () => setExpandedLines((current) => {
        const next = new Set(current);
        if (next.has(item.entityId)) next.delete(item.entityId);
        else next.add(item.entityId);
        return next;
      });
      return <ReactFragment key={item.entityId}>
        <article className={`fragment-card-new is-line${expanded ? " is-expanded" : ""}`} role="button" tabIndex={0} aria-expanded={expanded} style={{ "--accent": item.accent } as React.CSSProperties} onClick={toggle} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") toggle(); }}>
          <div className="fragment-card-index"><Icon name="timeline" /></div>
          <header><span>{children.length} 个章节</span>{writable && <button className="icon-button" aria-label={`编辑${item.title}`} title="编辑剧情线" onClick={(event) => edit(event, item)}><Icon name="edit" /></button>}</header>
          <div className="fragment-card-copy"><small>STORY LINE</small><h2>{item.title}</h2><CompleteBlockPreview source={item.bodyPreview || "还没有剧情线概述"} className="fragment-card-preview content-card-preview" /></div>
          <div className="metadata-tags">{item.tags.map((tag) => <span key={tag} style={{ color: item.accent, borderColor: item.accent }}>{tag}</span>)}</div>
          <span className="fragment-card-arrow" aria-hidden="true"><Icon name={expanded ? "up" : "down"} /></span>
        </article>
        {expanded && <section className="fragment-line-expanded" aria-label={`${item.title}的章节`}>
          <header><div><small>EXPANDED STORY LINE</small><h2>{item.title}</h2><p>{children.length ? `共 ${children.length} 个章节，选择任意卡片阅读正文。` : "这条线还是空的，可以从第一个章节开始。"}</p></div>{writable && <button className="icon-button fragment-line-edit" aria-label={`编辑${item.title}剧情线`} title="编辑剧情线" onClick={(event) => edit(event, item)}><Icon name="edit" /></button>}</header>
          {children.length > 0 ? <div className="fragment-line-chapters">{children.map((child, childIndex) => chapterCard(child, `第 ${fragmentChapterNumberOf(child) ?? childIndex + 1} 章`, true))}</div> : <div className="fragment-line-empty"><Icon name="book" /><span>尚未添加章节</span></div>}
        </section>}
      </ReactFragment>;
    })}</div>
    <Pagination page={activePage} totalPages={totalPages} onChange={changePage} />
    {!fragments.length && <div className="empty-state"><Icon name="book" /><h2>还没有灵感碎片</h2><p>可以记录一章，也可以先搭一整条剧情线。</p></div>}
    {clipboardDialog && <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && !mutation.isPending && setClipboardDialog(false)}>
      <section className="clipboard-import-dialog" role="dialog" aria-modal="true" aria-labelledby="clipboard-import-title">
        <header><div><small>Clipboard Import</small><h2 id="clipboard-import-title">粘贴灵感内容</h2><p>{clipboardHint}</p></div><button className="icon-button" disabled={mutation.isPending} onClick={() => setClipboardDialog(false)} aria-label="关闭粘贴面板"><Icon name="close" /></button></header>
        <label><span>剪贴板文字</span><textarea autoFocus value={clipboardText} onChange={(event) => { setClipboardText(event.target.value); setClipboardHint("检测到章节标题时会生成剧情线，否则生成单篇灵感。"); }} onPaste={() => setClipboardHint("内容已粘贴，确认后即可自动拆分。")} onKeyDown={(event) => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) { event.preventDefault(); void importText(clipboardText); } }} placeholder={"可直接粘贴普通灵感，或按以下格式粘贴任意数量章节：\n\n第一章：标题\n这一章的正文……\n\n第 25 章：标题\n这一章的正文……"} /></label>
        <div className="clipboard-import-rules"><span><Icon name="timeline" /></span><p><strong>自动识别章节</strong><small>支持第 1 章、第二十五章、第一百零八章等写法；缺章允许，重复章号会提示修正。</small></p><button className="clipboard-read-action" type="button" onClick={() => void tryReadClipboard()}>尝试自动读取</button></div>
        <footer><small>⌘/Ctrl+Enter 也可以直接导入</small><div><button className="text-action" disabled={mutation.isPending} onClick={() => setClipboardDialog(false)}>取消</button><button className="primary-action" disabled={!clipboardText.trim() || mutation.isPending} onClick={() => void importText(clipboardText)}>{mutation.isPending ? "正在生成…" : "生成灵感"}</button></div></footer>
      </section>
    </div>}
    {editor && <FragmentEditor entityId={editor} initialParentId={editor === "new" ? newParentId : null} onClose={() => { setEditor(null); setNewParentId(null); }} />}
    {readerItem && !snapshot.readonly && readerDetail.isPending && <div className="dialog-backdrop"><div className="reader-dialog loading-dialog">正在读取完整碎片…</div></div>}
    {readerItem && !snapshot.readonly && readerDetail.isError && <div className="dialog-backdrop"><section className="reader-dialog loading-dialog"><p>{readerDetail.error instanceof Error ? readerDetail.error.message : "读取碎片失败"}</p><button className="primary-action" onClick={() => setReader(null)}>关闭</button></section></div>}
    {readerItem && readerData && <ReadOnlyArticle title={fragmentDisplayTitle(readerItem)} eyebrow={fragmentParentOf(readerItem) ? `剧情线 · 第 ${fragmentChapterNumberOf(readerItem) ?? "?"} 章` : "灵感碎片"} body={readerData.body || ""} onClose={() => setReader(null)} />}
  </section>;
}
