import { useState } from "react";
import { useProjectMutation, useRuntime } from "../api/runtime";
import { ConfirmDialog } from "./ConfirmDialog";
import { Icon } from "./Icon";

interface ChapterDraft {
  entityId: string;
  stableId: string;
  label: string;
  persisted: boolean;
}

interface PlotDraft {
  entityId: string;
  title: string;
  chapterId: string;
}

function generatedChapterId(): string {
  const suffix = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID().replaceAll("-", "").slice(0, 12)
    : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  return `chapter-${suffix}`;
}

function moveItem<T>(values: T[], index: number, direction: -1 | 1): T[] {
  const target = index + direction;
  if (target < 0 || target >= values.length) return values;
  const next = [...values];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export function StoryStructureEditor({ onClose }: { onClose: () => void }) {
  const { snapshot, writable } = useRuntime();
  const mutation = useProjectMutation();
  const initialChapters: ChapterDraft[] = snapshot.chapters.map((item) => ({
    entityId: item.entityId,
    stableId: item.id,
    label: item.label,
    persisted: true,
  }));
  const initialPlots: PlotDraft[] = snapshot.plots.map((item) => ({
    entityId: item.entityId,
    title: item.title,
    chapterId: item.chapterId,
  }));
  const initialState = JSON.stringify({ chapters: initialChapters, plots: initialPlots });
  const [chapters, setChapters] = useState(initialChapters);
  const [plots, setPlots] = useState(initialPlots);
  const [baseline, setBaseline] = useState(initialState);
  const [removeId, setRemoveId] = useState<string | null>(null);
  const [replacementId, setReplacementId] = useState("");
  const [confirmClose, setConfirmClose] = useState(false);
  const [message, setMessage] = useState("");
  const dirty = JSON.stringify({ chapters, plots }) !== baseline;

  const addChapter = () => {
    const stableId = generatedChapterId();
    setChapters((current) => [...current, {
      entityId: `chapter:${stableId}`,
      stableId,
      label: `新篇章 ${current.length + 1}`,
      persisted: false,
    }]);
    setMessage("");
  };
  const requestRemove = (entityId: string) => {
    const target = chapters.find((item) => item.entityId !== entityId)?.entityId || "";
    setReplacementId(target);
    setRemoveId(entityId);
  };
  const removeChapter = () => {
    if (!removeId || chapters.length <= 1) return;
    const affected = plots.some((item) => item.chapterId === removeId);
    if (affected && !replacementId) return;
    setChapters((current) => current.filter((item) => item.entityId !== removeId));
    if (affected) {
      setPlots((current) => current.map((item) => item.chapterId === removeId
        ? { ...item, chapterId: replacementId }
        : item));
    }
    setRemoveId(null);
    setMessage("");
  };
  const save = async () => {
    if (!writable || mutation.isPending) return;
    setMessage("");
    try {
      const result = await mutation.mutateAsync({
        path: "/story-structure",
        method: "PUT",
        payload: {
          chapters: chapters.map((item) => ({
            entityId: item.persisted ? item.entityId : "",
            stableId: item.stableId,
            label: item.label,
          })),
          plots: plots.map((item) => ({ entityId: item.entityId, chapterId: item.chapterId })),
        },
      });
      const savedChapters = chapters.map((item) => ({ ...item, persisted: true }));
      setChapters(savedChapters);
      setBaseline(JSON.stringify({ chapters: savedChapters, plots }));
      setMessage(result.warnings[0] || "篇章与阅读顺序已保存");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    }
  };
  const removed = chapters.find((item) => item.entityId === removeId);
  const affectedCount = plots.filter((item) => item.chapterId === removeId).length;

  return <div className="dialog-backdrop">
    <section className="story-structure-dialog" role="dialog" aria-modal="true" aria-label="编辑篇章与阅读顺序">
      <header>
        <div><small>Story Structure</small><h2>篇章与阅读顺序</h2><p>这里只调整读者看到文章的顺序，不改写时间线中的故事发生顺序。</p></div>
        <button className="icon-button" aria-label="关闭" title="关闭" onClick={() => dirty ? setConfirmClose(true) : onClose()}><Icon name="close" /></button>
      </header>
      <div className="story-structure-body">
        <section className="chapter-manager">
          <header><div><small>Chapters</small><h3>篇章</h3></div><button className="icon-button" aria-label="新增篇章" title="新增篇章" onClick={addChapter}><Icon name="plus" /></button></header>
          <div className="chapter-editor-list">{chapters.map((item, index) => {
            const count = plots.filter((plot) => plot.chapterId === item.entityId).length;
            return <article key={item.entityId}>
              <span className="order-number">{index + 1}</span>
              <label><span className="sr-only">篇章名称</span><input value={item.label} onChange={(event) => { const label = event.target.value; setChapters((current) => current.map((chapter) => chapter.entityId === item.entityId ? { ...chapter, label } : chapter)); setMessage(""); }} /></label>
              <small>{count} 篇剧情</small>
              <div className="row-icon-actions">
                <button className="icon-button" disabled={index === 0} aria-label={`上移${item.label}`} title="上移" onClick={() => setChapters((current) => moveItem(current, index, -1))}><Icon name="up" /></button>
                <button className="icon-button" disabled={index === chapters.length - 1} aria-label={`下移${item.label}`} title="下移" onClick={() => setChapters((current) => moveItem(current, index, 1))}><Icon name="down" /></button>
                <button className="icon-button is-danger" disabled={chapters.length === 1} aria-label={`删除${item.label}`} title={chapters.length === 1 ? "至少保留一个篇章" : "删除篇章"} onClick={() => requestRemove(item.entityId)}><Icon name="trash" /></button>
              </div>
            </article>;
          })}</div>
        </section>
        <section className="plot-order-manager">
          <header><div><small>Reading Order</small><h3>剧情阅读顺序</h3></div><strong>{plots.length}</strong></header>
          <div className="plot-order-list">{plots.map((item, index) => <article key={item.entityId}>
            <span className="order-number">{String(index + 1).padStart(2, "0")}</span>
            <strong>{item.title}</strong>
            <select aria-label={`${item.title}所属篇章`} value={item.chapterId} onChange={(event) => { const chapterId = event.target.value; setPlots((current) => current.map((plot) => plot.entityId === item.entityId ? { ...plot, chapterId } : plot)); setMessage(""); }}>{chapters.map((chapter) => <option key={chapter.entityId} value={chapter.entityId}>{chapter.label}</option>)}</select>
            <div className="row-icon-actions">
              <button className="icon-button" disabled={index === 0} aria-label={`上移${item.title}`} title="阅读顺序上移" onClick={() => setPlots((current) => moveItem(current, index, -1))}><Icon name="up" /></button>
              <button className="icon-button" disabled={index === plots.length - 1} aria-label={`下移${item.title}`} title="阅读顺序下移" onClick={() => setPlots((current) => moveItem(current, index, 1))}><Icon name="down" /></button>
            </div>
          </article>)}</div>
        </section>
      </div>
      <footer><span className={dirty ? "is-dirty" : ""}>{message || (dirty ? "有未保存修改" : "没有待保存修改")}</span><button className="primary-action" disabled={!dirty || mutation.isPending} onClick={save}>{mutation.isPending ? "正在保存…" : "保存结构"}</button></footer>
    </section>
    <ConfirmDialog open={Boolean(removeId)} title={`删除“${removed?.label || "这个篇章"}”？`} message={affectedCount ? `其中 ${affectedCount} 篇剧情会在同一事务中移动到接收篇章，之后原篇章进入回收站。` : "篇章会进入统一回收站保留 7 天。"} confirmLabel={affectedCount ? "移动剧情并删除" : "移入回收站"} danger confirmDisabled={affectedCount > 0 && !replacementId} onCancel={() => setRemoveId(null)} onConfirm={removeChapter}>
      {affectedCount > 0 && <label className="confirm-field"><span>接收篇章</span><select value={replacementId} onChange={(event) => setReplacementId(event.target.value)}>{chapters.filter((item) => item.entityId !== removeId).map((item) => <option key={item.entityId} value={item.entityId}>{item.label}</option>)}</select></label>}
    </ConfirmDialog>
    <ConfirmDialog open={confirmClose} title="放弃结构调整？" message="未保存的篇章名称、归属和阅读顺序会丢失。" confirmLabel="放弃修改" danger onCancel={() => setConfirmClose(false)} onConfirm={onClose} />
  </div>;
}
