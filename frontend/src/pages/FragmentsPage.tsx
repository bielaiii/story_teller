import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Fragment } from "../api/types";
import { useProjectMutation, useRuntime } from "../api/runtime";
import type { PickedReference } from "../editor/MarkdownEditor";
import { DeferredMarkdownEditor as MarkdownEditor } from "../editor/DeferredMarkdownEditor";
import { useEditorSaveShortcut } from "../editor/useEditorSaveShortcut";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { FilterChips } from "../components/FilterChips";
import { Icon } from "../components/Icon";
import { ReadOnlyArticle } from "../components/ReadOnlyArticle";
import { RenderedMarkdown } from "../components/RenderedMarkdown";
import { Pagination } from "../components/Pagination";

interface Draft { stableId: string; title: string; body: string; status: string; accent: string; tags: string[]; references: string[] }
const blank: Draft = { stableId: "", title: "", body: "", status: "灵感", accent: "#d65f8f", tags: [], references: [] };

function FragmentEditor({ entityId, onClose }: { entityId: string | "new"; onClose: () => void }) {
  const { api, project, snapshot } = useRuntime();
  const mutation = useProjectMutation();
  const [currentId, setCurrentId] = useState<string | "new">(entityId);
  const detail = useQuery({ queryKey: ["entity", project, currentId], queryFn: () => api.detail<Fragment>(currentId), enabled: currentId !== "new" });
  const [draft, setDraft] = useState<Draft>(blank);
  const [baseline, setBaseline] = useState("");
  const [message, setMessage] = useState("");
  const [confirmClose, setConfirmClose] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  useEffect(() => {
    const item = detail.data?.data;
    const next = currentId === "new" ? { ...blank } : item ? { stableId: item.id, title: item.title, body: item.body || "", status: item.status, accent: item.accent, tags: [...item.tags], references: [...(item.references || [])] } : null;
    if (next) { setDraft(next); setBaseline(JSON.stringify(next)); }
  }, [currentId, detail.data]);
  const dirty = Boolean(baseline && JSON.stringify(draft) !== baseline);
  const change = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const addReference = (reference: PickedReference) => setDraft((current) => ({
    ...current,
    references: current.references.includes(reference.entityId)
      ? current.references
      : [...current.references, reference.entityId],
  }));
  const save = async () => {
    try {
      const payload = { ...draft } as unknown as Record<string, unknown>;
      if (currentId !== "new") delete payload.stableId;
      const result = await mutation.mutateAsync({ path: currentId === "new" ? "/fragments" : `/fragments/${encodeURIComponent(currentId)}`, method: currentId === "new" ? "POST" : "PATCH", payload });
      if (currentId === "new") {
        const created = result.changed.fragments?.find((item) => !snapshot.fragments.some((existing) => existing.entityId === item.entityId));
        if (created?.entityId) setCurrentId(String(created.entityId));
      }
      setBaseline(JSON.stringify(draft)); setMessage(result.warnings[0] || "已保存");
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存失败"); }
  };
  const remove = async () => {
    if (currentId === "new") return;
    try { await mutation.mutateAsync({ path: `/entities/${encodeURIComponent(currentId)}`, method: "DELETE", payload: {} }); onClose(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "删除失败"); }
  };
  useEditorSaveShortcut(save);
  if (entityId !== "new" && detail.isPending) return <div className="dialog-backdrop"><div className="editor-dialog loading-dialog">正在读取灵感…</div></div>;
  return <div className="dialog-backdrop editor-backdrop"><section className="editor-dialog fragment-editor-dialog" role="dialog" aria-modal="true" aria-label="写灵感碎片"><header className="dialog-header"><div><small>Idea Fragment</small><h2>{currentId === "new" ? "写一条灵感" : draft.title}</h2></div><div className="dialog-actions">{currentId !== "new" && <button className="icon-button is-danger" aria-label="删除碎片" title="删除碎片" onClick={() => setConfirmDelete(true)}><Icon name="trash" /></button>}<button className="icon-button" aria-label="关闭" title="关闭" onClick={() => dirty ? setConfirmClose(true) : onClose()}><Icon name="close" /></button></div></header><button className="settings-toggle" type="button" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((value) => !value)}><Icon name="settings" /><span>灵感设置</span><small>{settingsOpen ? "收起" : "展开"}</small></button>{settingsOpen && <div className="editor-settings"><label className="wide"><span>标题</span><input value={draft.title} onChange={(event) => change("title", event.target.value)} /></label><label><span>状态</span><input value={draft.status} onChange={(event) => change("status", event.target.value)} /></label><label><span>颜色</span><input type="color" value={draft.accent} onChange={(event) => change("accent", event.target.value)} /></label><label className="wide"><span>标签</span><input value={draft.tags.join("，")} onChange={(event) => change("tags", event.target.value.split(/[，,]/).map((value) => value.trim()).filter(Boolean))} /></label></div>}<MarkdownEditor label="灵感正文" value={draft.body} onChange={(value) => change("body", value)} onSave={save} characters={snapshot.characters} entries={snapshot.entries} sourceEntityId={currentId === "new" ? undefined : currentId} onReference={addReference} /><footer className="editor-footer"><span className={dirty ? "is-dirty" : ""}>{message || (dirty ? "有未保存修改" : "已保存")}</span><small>可直接在当前尺寸写，也可进入沉浸模式</small></footer></section><ConfirmDialog open={confirmClose} title="放弃未保存修改？" message="关闭后，本次灵感修改会丢失。" confirmLabel="放弃修改" danger onCancel={() => setConfirmClose(false)} onConfirm={onClose} /><ConfirmDialog open={confirmDelete} title={`删除“${draft.title}”？`} message="碎片会进入统一回收站保留 7 天。" confirmLabel="移入回收站" danger onCancel={() => setConfirmDelete(false)} onConfirm={remove} /></div>;
}

export default function FragmentsPage() {
  const { snapshot, writable } = useRuntime();
  const tags = useMemo(() => [...new Set(snapshot.fragments.flatMap((item) => item.tags))].sort(), [snapshot.fragments]);
  const [selectedTags, setSelectedTags] = useState<string[]>(tags);
  const [editor, setEditor] = useState<string | "new" | null>(null);
  const [reader, setReader] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  useEffect(() => setSelectedTags(tags), [tags.join("\0")]);
  useEffect(() => setPage(1), [selectedTags.join("\0")]);
  const filteredFragments = snapshot.fragments.filter((item) => selectedTags.length === tags.length || item.tags.some((tag) => selectedTags.includes(tag)));
  const totalPages = Math.max(1, Math.ceil(filteredFragments.length / 6));
  const fragments = filteredFragments.slice((Math.min(page, totalPages) - 1) * 6, Math.min(page, totalPages) * 6);
  const readerItem = snapshot.fragments.find((item) => item.entityId === reader);
  return <section className="workspace-page fragments-page-new"><header className="page-header"><div><small>Idea Inbox</small><h1>灵感碎片箱</h1></div>{writable && <button className="icon-button is-primary" aria-label="写灵感碎片" title="写灵感碎片" onClick={() => setEditor("new")}><Icon name="plus" /></button>}</header>{tags.length > 0 && <FilterChips label="标签" values={tags} selected={selectedTags} onChange={setSelectedTags} collapsible />}<div className="fragment-grid-new">{fragments.map((item) => <article key={item.entityId} className="fragment-card-new" role="button" tabIndex={0} style={{ "--accent": item.accent } as React.CSSProperties} onClick={() => setReader(item.entityId)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setReader(item.entityId); }}><header>{!["", "空", "待补充"].includes(item.status) && <span>{item.status}</span>}{writable && <button className="icon-button" aria-label={`编辑${item.title}`} title="编辑碎片" onClick={(event) => { event.stopPropagation(); setEditor(item.entityId); }}><Icon name="edit" /></button>}</header><h2>{item.title}</h2><RenderedMarkdown source={item.bodyPreview || "还没有正文"} className="fragment-card-preview content-card-preview" /><div className="metadata-tags">{item.tags.map((tag) => <span key={tag} style={{ color: item.accent, borderColor: item.accent }}>{tag}</span>)}</div></article>)}</div><Pagination page={Math.min(page, totalPages)} totalPages={totalPages} onChange={setPage} />{!fragments.length && <div className="empty-state"><Icon name="book" /><h2>还没有灵感碎片</h2><p>随时记下一小段场景、对白或画面。</p></div>}{editor && <FragmentEditor entityId={editor} onClose={() => setEditor(null)} />}{readerItem && <ReadOnlyArticle title={readerItem.title} eyebrow="灵感碎片" body={readerItem.body || ""} onClose={() => setReader(null)} />}</section>;
}
