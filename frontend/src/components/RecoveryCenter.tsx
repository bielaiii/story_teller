import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";
import { useProjectMutation, useRuntime } from "../api/runtime";
import type { TrashItem } from "../api/types";
import { ConfirmDialog } from "./ConfirmDialog";
import { Icon } from "./Icon";

const kindLabels: Record<string, string> = {
  character: "人物", plot: "剧情", entry: "设定", fragment: "碎片",
  relationship: "关系", timeline_line: "剧情线", chapter: "篇章",
};
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

export default function RecoveryCenter({ onClose }: { onClose: () => void }) {
  const { api, project } = useRuntime();
  const mutation = useProjectMutation();
  const trash = useQuery({ queryKey: ["trash", project], queryFn: () => api.trash() });
  const operations = useQuery({ queryKey: ["operations", project], queryFn: () => api.operations() });
  const [preview, setPreview] = useState<TrashItem | null>(null);
  const previewQuery = useQuery({
    queryKey: ["trash-detail", project, preview?.entityId],
    queryFn: () => api.trashDetail<Record<string, unknown>>(preview!.entityId),
    enabled: Boolean(preview),
  });
  const [undoId, setUndoId] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const restore = async (item: TrashItem) => {
    try {
      await mutation.mutateAsync({ path: `/entities/${encodeURIComponent(item.entityId)}/restore`, method: "POST", payload: {} });
      setPreview(null);
      setMessage(`已恢复${item.title}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "恢复失败");
    }
  };
  const undo = async () => {
    if (!undoId) return;
    try {
      await mutation.mutateAsync({ path: "/operations/undo", method: "POST", payload: { operationId: undoId } });
      setUndoId(null);
      setMessage("操作已撤销");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "撤销失败");
    }
  };

  return <div className="dialog-backdrop recovery-center-backdrop">
    <section className="recovery-center-dialog" role="dialog" aria-modal="true" aria-label="回收站与撤销记录">
      <header><div><small>Recovery</small><h2>恢复中心</h2><p>删除内容保留七天；近期操作在没有后续冲突时可以整体撤销。</p></div><div className="dialog-actions">{message && <span className="page-message">{message}</span>}<button className="icon-button" aria-label="关闭恢复中心" title="关闭" onClick={onClose}><Icon name="close" /></button></div></header>
      <div className="recovery-center-grid">
        <section className="recovery-panel"><header><div><small>Trash</small><h3>回收站</h3></div><strong>{trash.data?.items.length || 0}</strong></header><div className="trash-list-new">{trash.data?.items.map((item) => <article key={item.entityId}><button className="trash-preview-main" onClick={() => setPreview(item)}><span>{kindLabels[item.kind] || item.kind}</span><strong>{item.title}</strong><small>{item.kind === "character" ? `ID ${item.id} · ` : ""}{item.daysRemaining} 天后永久删除</small></button><button className="icon-button" aria-label={`恢复${item.title}${item.kind === "character" ? `（ID ${item.id}）` : ""}`} title="恢复" onClick={() => restore(item)}><Icon name="restore" /></button></article>)}{!trash.isPending && !trash.data?.items.length && <div className="empty-state compact"><Icon name="trash" /><p>回收站是空的</p></div>}</div></section>
        <section className="recovery-panel"><header><div><small>History</small><h3>操作记录</h3></div><strong>{operations.data?.items.length || 0}</strong></header><div className="operation-list-new">{operations.data?.items.map((item) => <article key={item.id}><div><span>{kindLabels[item.entityKind] || "内容"}</span><strong>{item.label}</strong><small>{new Date(item.createdAt * 1000).toLocaleString("zh-CN")}</small>{!item.canUndo && item.undoBlockedReason && <em>{item.undoBlockedReason}</em>}</div><button className="icon-button" disabled={!item.canUndo} aria-label={`撤销${item.label}`} title={item.undoBlockedReason || "撤销"} onClick={() => setUndoId(item.id)}><Icon name="undo" /></button></article>)}</div></section>
      </div>
    </section>
    {preview && <section className="trash-preview-dialog" role="dialog" aria-modal="true" aria-label={`预览${preview.title}`}><header><div><small>{kindLabels[preview.kind]}</small><h2>{preview.title}</h2></div><button className="icon-button" aria-label="关闭预览" onClick={() => setPreview(null)}><Icon name="close" /></button></header>{previewQuery.isPending ? <p>正在读取预览…</p> : <TrashPreviewContent data={previewQuery.data?.data || {}} />}<footer><small>{preview.daysRemaining} 天后永久删除</small><button className="icon-button is-primary" aria-label={`恢复${preview.title}`} title="恢复" onClick={() => restore(preview)}><Icon name="restore" /></button></footer></section>}
    <ConfirmDialog open={Boolean(undoId)} title="撤销这项操作？" message="只有相关数据没有被后续修改时才能整体撤销；不会覆盖更新的内容。" confirmLabel="撤销操作" onCancel={() => setUndoId(null)} onConfirm={undo} />
  </div>;
}
