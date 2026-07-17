import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";
import { useProjectMutation, useRuntime } from "../api/runtime";
import type { DiagnosticItem, TrashItem } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Icon } from "../components/Icon";
import { useUiStore } from "../state/ui";

const kindLabels: Record<string, string> = { character: "人物", plot: "剧情", entry: "设定", fragment: "碎片", relationship: "关系", timeline_line: "剧情线", chapter: "篇章" };
const levelLabels = { error: "错误", warning: "警告", info: "提醒" } as const;
const previewRenderer = new MarkdownIt({ html: false, linkify: true, breaks: false });

function TrashPreviewContent({ data }: { data: Record<string, unknown> }) {
  const body = [data.body, data.intro].find((value) => typeof value === "string" && value.trim()) as string | undefined;
  const metadata = Object.entries(data).filter(([key, value]) => (
    !["body", "intro", "extra", "references"].includes(key)
    && (typeof value === "string" || typeof value === "number" || typeof value === "boolean" || Array.isArray(value))
  ));
  const html = body ? DOMPurify.sanitize(previewRenderer.render(body)) : "";
  return <div className="trash-preview-content">
    {metadata.length > 0 && <dl>{metadata.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{Array.isArray(value) ? value.join("、") : String(value)}</dd></div>)}</dl>}
    {body ? <article className="trash-preview-prose prose" dangerouslySetInnerHTML={{ __html: html }} /> : <p className="empty-copy">这项内容没有文章正文。</p>}
  </div>;
}

export default function ChecksPage() {
  const { api, project, snapshot, writable } = useRuntime();
  const mutation = useProjectMutation();
  const trash = useQuery({ queryKey: ["trash", project], queryFn: () => api.trash(), enabled: writable });
  const operations = useQuery({ queryKey: ["operations", project], queryFn: () => api.operations(), enabled: writable });
  const diagnostics = useQuery({ queryKey: ["diagnostics", project], queryFn: () => api.diagnostics(), enabled: writable });
  const [preview, setPreview] = useState<TrashItem | null>(null);
  const previewQuery = useQuery({ queryKey: ["trash-detail", project, preview?.entityId], queryFn: () => api.trashDetail<Record<string, unknown>>(preview!.entityId), enabled: Boolean(preview) });
  const [undoId, setUndoId] = useState<number | null>(null);
  const [ignoreItem, setIgnoreItem] = useState<DiagnosticItem | null>(null);
  const [ignoreReason, setIgnoreReason] = useState("");
  const [message, setMessage] = useState("");
  const restore = async (item: TrashItem) => {
    try { await mutation.mutateAsync({ path: `/entities/${encodeURIComponent(item.entityId)}/restore`, method: "POST", payload: {} }); setPreview(null); setMessage(`已恢复${item.title}`); }
    catch (error) { setMessage(error instanceof Error ? error.message : "恢复失败"); }
  };
  const undo = async () => {
    if (!undoId) return;
    try { await mutation.mutateAsync({ path: "/operations/undo", method: "POST", payload: { operationId: undoId } }); setUndoId(null); setMessage("操作已撤销"); }
    catch (error) { setMessage(error instanceof Error ? error.message : "撤销失败"); }
  };
  const setIgnored = async (item: DiagnosticItem, reason: string) => {
    try {
      await mutation.mutateAsync({ path: `/diagnostics/${encodeURIComponent(item.id)}/ignore`, method: "PUT", payload: { reason } });
      setIgnoreItem(null); setIgnoreReason(""); setMessage(reason ? "提醒已忽略并记录原因" : "提醒已恢复显示");
    } catch (error) { setMessage(error instanceof Error ? error.message : "更新提醒失败"); }
  };
  const jump = (item: DiagnosticItem) => {
    const store = useUiStore.getState();
    if (item.kind === "plot") { store.selectPlot(item.entityId); store.navigate("story"); }
    else if (item.kind === "character") { store.selectCharacter(item.entityId); store.navigate("characters"); }
    else if (item.kind === "entry") { store.selectEntry(item.entityId); store.navigate("entries"); }
    else if (item.kind === "timeline_line") { store.setTimelineFocus(item.entityId); store.navigate("timeline"); }
    else if (item.kind === "relationship") {
      const relation = snapshot.relationships.find((entry) => entry.entityId === item.entityId);
      if (relation) store.selectCharacter(relation.from);
      store.navigate("characters");
    } else store.navigate("story");
  };
  if (!writable) return <section className="workspace-page checks-page-new"><header className="page-header"><div><small>Static Snapshot</small><h1>检查</h1><p>当前是只读静态快照，不会连接本地操作历史或回收站。</p></div></header><div className="check-panel static-summary"><header><div><small>Snapshot Contents</small><h2>快照内容</h2></div><strong>{snapshot.project.revision}</strong></header><div className="static-count-grid"><div><strong>{snapshot.plots.length}</strong><span>剧情</span></div><div><strong>{snapshot.characters.length}</strong><span>人物</span></div><div><strong>{snapshot.entries.length}</strong><span>设定</span></div><div><strong>{snapshot.fragments.length}</strong><span>碎片</span></div></div><p>确定性诊断、回收站、操作撤销和所有编辑功能只在本地 SQLite 服务中提供。</p></div></section>;
  const activeDiagnostics = diagnostics.data?.items.filter((item) => !item.ignored) || [];
  const ignoredDiagnostics = diagnostics.data?.items.filter((item) => item.ignored) || [];
  const summary = diagnostics.data?.summary;
  return <section className="workspace-page checks-page-new">
    <header className="page-header"><div><small>Content Check</small><h1>配置检查</h1></div>{message && <span className="page-message">{message}</span>}</header>
    <div className="checks-grid"><section className="check-panel"><header><div><small>Recovery</small><h2>回收站</h2></div><strong>{trash.data?.items.length || 0}</strong></header><div className="trash-list-new">{trash.data?.items.map((item) => <article key={item.entityId}><button className="trash-preview-main" onClick={() => setPreview(item)}><span>{kindLabels[item.kind] || item.kind}</span><strong>{item.title}</strong><small>{item.daysRemaining} 天后永久删除</small></button><button className="icon-button" aria-label={`恢复${item.title}`} title="恢复" onClick={() => restore(item)}><Icon name="restore" /></button></article>)}{trash.data?.items.length === 0 && <div className="empty-state compact"><Icon name="trash" /><p>回收站是空的</p></div>}</div></section><section className="check-panel"><header><div><small>Undo History</small><h2>操作记录</h2></div><strong>{operations.data?.items.length || 0}</strong></header><div className="operation-list-new">{operations.data?.items.map((item) => <article key={item.id}><div><span>{kindLabels[item.entityKind] || "内容"}</span><strong>{item.label}</strong><small>{new Date(item.createdAt * 1000).toLocaleString("zh-CN")}</small>{!item.canUndo && item.undoBlockedReason && <em>{item.undoBlockedReason}</em>}</div><button className="icon-button" disabled={!item.canUndo} aria-label={`撤销${item.label}`} title={item.undoBlockedReason || "撤销"} onClick={() => setUndoId(item.id)}><Icon name="undo" /></button></article>)}</div></section></div>
    <section className="check-panel diagnostic-panel-new">
      <header><div><small>Deterministic Diagnostics</small><h2>内容与配置诊断</h2></div><div className="diagnostic-summary"><span className="is-error">{summary?.errors || 0} 错误</span><span className="is-warning">{summary?.warnings || 0} 警告</span><span>{summary?.info || 0} 提醒</span></div></header>
      <div className="diagnostic-list-new">{activeDiagnostics.map((item) => <article className={`is-${item.level}`} key={item.id}><span className="diagnostic-level">{levelLabels[item.level]}</span><button className="diagnostic-main" onClick={() => item.entityId && jump(item)} disabled={!item.entityId}><strong>{item.title}</strong><p>{item.detail}</p><small>{item.suggestion}</small></button><button className="icon-button" aria-label={`忽略${item.title}`} title="暂时忽略" onClick={() => { setIgnoreItem(item); setIgnoreReason(""); }}><Icon name="close" /></button></article>)}{!diagnostics.isPending && !activeDiagnostics.length && <div className="diagnostic-clean"><Icon name="restore" /><strong>没有活动问题</strong><p>当前结构化数据通过了可确定检查。</p></div>}</div>
      {ignoredDiagnostics.length > 0 && <details className="ignored-diagnostics"><summary>已忽略 {ignoredDiagnostics.length} 条</summary>{ignoredDiagnostics.map((item) => <article key={item.id}><div><strong>{item.title}</strong><p>{item.ignoreReason}</p></div><button className="icon-button" aria-label={`恢复提醒${item.title}`} title="恢复提醒" onClick={() => setIgnored(item, "")}><Icon name="restore" /></button></article>)}</details>}
    </section>
    {preview && <div className="dialog-backdrop"><section className="trash-preview-dialog"><header><div><small>{kindLabels[preview.kind]}</small><h2>{preview.title}</h2></div><button className="icon-button" aria-label="关闭预览" onClick={() => setPreview(null)}><Icon name="close" /></button></header>{previewQuery.isPending ? <p>正在读取预览…</p> : <TrashPreviewContent data={previewQuery.data?.data || {}} />}<footer><small>{preview.daysRemaining} 天后永久删除</small><button className="icon-button is-primary" aria-label={`恢复${preview.title}`} title="恢复" onClick={() => restore(preview)}><Icon name="restore" /></button></footer></section></div>}
    <ConfirmDialog open={Boolean(undoId)} title="撤销这项操作？" message="只有相关数据没有被后续修改时才能整体撤销；不会覆盖更新的内容。" confirmLabel="撤销操作" onCancel={() => setUndoId(null)} onConfirm={undo} />
    <ConfirmDialog open={Boolean(ignoreItem)} title="暂时忽略这条提醒？" message="请写明为什么暂时忽略；问题消失后，这条忽略记录不会继续影响其他诊断。" confirmLabel="记录并忽略" confirmDisabled={!ignoreReason.trim()} onCancel={() => { setIgnoreItem(null); setIgnoreReason(""); }} onConfirm={() => { if (ignoreItem) return setIgnored(ignoreItem, ignoreReason); }}><label className="confirm-input"><span>忽略原因</span><textarea rows={3} value={ignoreReason} onChange={(event) => setIgnoreReason(event.target.value)} autoFocus /></label></ConfirmDialog>
  </section>;
}
