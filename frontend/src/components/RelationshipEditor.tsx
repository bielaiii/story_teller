import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Relationship } from "../api/types";
import { useProjectMutation, useRuntime } from "../api/runtime";
import type { PickedReference } from "../editor/MarkdownEditor";
import { MarkdownEditor } from "../editor/MarkdownEditor";
import { useEditorSaveShortcut } from "../editor/useEditorSaveShortcut";
import { ConfirmDialog } from "./ConfirmDialog";
import { Icon } from "./Icon";

interface RelationshipDraft {
  fromCharacterId: string;
  toCharacterId: string;
  fromRole: string;
  toRole: string;
  label: string;
  type: string;
  color: string;
  body: string;
  references: string[];
}

function emptyDraft(defaultCharacterId: string, characterIds: string[]): RelationshipDraft {
  return {
    fromCharacterId: defaultCharacterId || characterIds[0] || "",
    toCharacterId: characterIds.find((id) => id !== defaultCharacterId) || "",
    fromRole: "",
    toRole: "",
    label: "",
    type: "",
    color: "#6f75c9",
    body: "",
    references: [],
  };
}

function fromRelationship(item: Relationship): RelationshipDraft {
  return {
    fromCharacterId: item.from,
    toCharacterId: item.to,
    fromRole: item.fromRole,
    toRole: item.toRole,
    label: item.label,
    type: item.type,
    color: item.color,
    body: item.body || "",
    references: [...(item.references || [])],
  };
}

export function RelationshipEditor({
  relationshipId,
  defaultCharacterId,
  onClose,
}: {
  relationshipId: string | "new";
  defaultCharacterId: string;
  onClose: () => void;
}) {
  const { api, project, snapshot, writable } = useRuntime();
  const mutation = useProjectMutation();
  const characterIds = snapshot.characters.map((item) => item.entityId);
  const initial = emptyDraft(defaultCharacterId, characterIds);
  const [currentId, setCurrentId] = useState<string | "new">(relationshipId);
  const [draft, setDraft] = useState<RelationshipDraft>(initial);
  const [baseline, setBaseline] = useState(JSON.stringify(initial));
  const [settingsOpen, setSettingsOpen] = useState(relationshipId === "new");
  const [confirmClose, setConfirmClose] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [message, setMessage] = useState(relationshipId === "new" ? "尚未保存" : "");
  const detail = useQuery({
    queryKey: ["entity", project, currentId],
    queryFn: () => api.detail<Relationship>(currentId),
    enabled: currentId !== "new",
  });

  useEffect(() => {
    if (!detail.data?.data) return;
    const next = fromRelationship(detail.data.data);
    setDraft(next);
    setBaseline(JSON.stringify(next));
  }, [detail.data]);

  const dirty = JSON.stringify(draft) !== baseline;
  const change = <K extends keyof RelationshipDraft>(key: K, value: RelationshipDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setMessage("");
  };
  const addReference = (reference: PickedReference) => setDraft((current) => ({
    ...current,
    references: current.references.includes(reference.entityId)
      ? current.references
      : [...current.references, reference.entityId],
  }));
  const save = async () => {
    if (!writable || mutation.isPending) return;
    setMessage("");
    try {
      const payload: Record<string, unknown> = { ...draft };
      if (currentId !== "new") {
        delete payload.fromCharacterId;
        delete payload.toCharacterId;
      }
      const result = await mutation.mutateAsync({
        path: currentId === "new" ? "/relationships" : `/relationships/${encodeURIComponent(currentId)}`,
        method: currentId === "new" ? "POST" : "PATCH",
        payload,
      });
      const created = currentId === "new"
        ? result.changed.relationships?.find((item) =>
          (item as unknown as Relationship).from === draft.fromCharacterId
          && (item as unknown as Relationship).to === draft.toCharacterId)
        : null;
      if (created) setCurrentId(String(created.entityId));
      setBaseline(JSON.stringify(draft));
      setMessage(result.warnings[0] || "已保存");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    }
  };
  const remove = async () => {
    if (currentId === "new") return;
    try {
      await mutation.mutateAsync({
        path: `/entities/${encodeURIComponent(currentId)}`,
        method: "DELETE",
        payload: {},
      });
      onClose();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
      setConfirmDelete(false);
    }
  };
  useEditorSaveShortcut(save);

  if (currentId !== "new" && detail.isPending) {
    return <div className="dialog-backdrop"><div className="editor-dialog loading-dialog">正在读取人物关系…</div></div>;
  }
  const fromPerson = snapshot.characters.find((item) => item.entityId === draft.fromCharacterId);
  const toPerson = snapshot.characters.find((item) => item.entityId === draft.toCharacterId);
  return <div className="dialog-backdrop editor-backdrop">
    <section className="editor-dialog relationship-editor-dialog" role="dialog" aria-modal="true" aria-label="编辑人物关系">
      <header className="dialog-header">
        <div><small>Character Relationship</small><h2>{currentId === "new" ? "建立人物关系" : `${fromPerson?.name || "人物"} · ${toPerson?.name || "人物"}`}</h2></div>
        <div className="dialog-actions">
          {currentId !== "new" && <button className="icon-button is-danger" aria-label="删除人物关系" title="删除人物关系" onClick={() => setConfirmDelete(true)}><Icon name="trash" /></button>}
          <button className="icon-button" aria-label="关闭" title="关闭" onClick={() => dirty ? setConfirmClose(true) : onClose()}><Icon name="close" /></button>
        </div>
      </header>
      <button className="settings-toggle" type="button" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((value) => !value)}><Icon name="settings" /><span>关系设置</span><small>{settingsOpen ? "收起" : "展开"}</small></button>
      {settingsOpen && <div className="editor-settings relationship-settings">
        <label><span>起点人物</span><select disabled={currentId !== "new"} value={draft.fromCharacterId} onChange={(event) => change("fromCharacterId", event.target.value)}>{snapshot.characters.map((item) => <option key={item.entityId} value={item.entityId} disabled={item.entityId === draft.toCharacterId}>{item.name}</option>)}</select></label>
        <label><span>终点人物</span><select disabled={currentId !== "new"} value={draft.toCharacterId} onChange={(event) => change("toCharacterId", event.target.value)}>{snapshot.characters.map((item) => <option key={item.entityId} value={item.entityId} disabled={item.entityId === draft.fromCharacterId}>{item.name}</option>)}</select></label>
        <label><span>{fromPerson?.name || "起点"}的角色</span><input value={draft.fromRole} onChange={(event) => change("fromRole", event.target.value)} placeholder="例如：委托人" /></label>
        <label><span>{toPerson?.name || "终点"}的角色</span><input value={draft.toRole} onChange={(event) => change("toRole", event.target.value)} placeholder="例如：调查者" /></label>
        <label className="wide"><span>关系名称</span><input value={draft.label} onChange={(event) => change("label", event.target.value)} placeholder="例如：互相试探" /></label>
        <label><span>关系类型</span><input value={draft.type} onChange={(event) => change("type", event.target.value)} placeholder="盟友、对手、亲属…" /></label>
        <label><span>关系颜色</span><input type="color" value={draft.color} onChange={(event) => change("color", event.target.value)} /></label>
      </div>}
      <MarkdownEditor label="关系说明" value={draft.body} onChange={(value) => change("body", value)} onSave={save} characters={snapshot.characters} entries={snapshot.entries} sourceEntityId={currentId === "new" ? undefined : currentId} onReference={addReference} autoFocus />
      <footer className="editor-footer"><span className={dirty ? "is-dirty" : ""}>{message || (dirty ? "有未保存修改" : "已保存")}</span><small>保存、删除与引用都进入统一操作历史</small></footer>
    </section>
    <ConfirmDialog open={confirmClose} title="放弃未保存修改？" message="关闭后，本次人物关系修改会丢失。" confirmLabel="放弃修改" danger onCancel={() => setConfirmClose(false)} onConfirm={onClose} />
    <ConfirmDialog open={confirmDelete} title={`删除“${draft.label || "这条人物关系"}”？`} message="关系会进入统一回收站保留 7 天，可以恢复或撤销。" confirmLabel="移入回收站" danger onCancel={() => setConfirmDelete(false)} onConfirm={remove} />
  </div>;
}
