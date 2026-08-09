import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Relationship } from "../api/types";
import { effectiveGraphLineMode } from "../api/relationshipPresentation";
import { useProjectMutation, useRuntime } from "../api/runtime";
import { browserDraftKey, clearBrowserDraft, restoreBrowserDraft, useBrowserDraft } from "../editor/browserDraft";
import { useEditorSaveShortcut } from "../editor/useEditorSaveShortcut";
import { ConfirmDialog } from "./ConfirmDialog";
import { Icon } from "./Icon";

const FAMILY_TYPES = new Set(["父子", "父女", "母子", "母女", "兄妹", "姐妹", "姐弟", "哥弟", "兄弟", "伴侣", "夫妻"]);

interface RelationshipDraft {
  fromCharacterId: string;
  toCharacterId: string;
  fromRole: string;
  toRole: string;
  fromImpression: string;
  toImpression: string;
  graphScope: "core" | "focus" | "hidden";
  graphLineMode: "single" | "double";
  label: string;
  type: string;
  color: string;
  body: string;
}

function emptyDraft(defaultCharacterId: string, characterIds: string[], mode: "relationship" | "impression"): RelationshipDraft {
  return {
    fromCharacterId: defaultCharacterId || characterIds[0] || "",
    toCharacterId: characterIds.find((id) => id !== defaultCharacterId) || "",
    fromRole: "",
    toRole: "",
    fromImpression: "",
    toImpression: "",
    graphScope: mode === "impression" ? "hidden" : "core",
    graphLineMode: "single",
    label: "",
    type: "",
    color: "#6f75c9",
    body: "",
  };
}

function fromRelationship(item: Relationship): RelationshipDraft {
  return {
    fromCharacterId: item.from,
    toCharacterId: item.to,
    fromRole: item.fromRole,
    toRole: item.toRole,
    fromImpression: item.fromImpression || "",
    toImpression: item.toImpression || "",
    graphScope: item.graphScope || "core",
    graphLineMode: effectiveGraphLineMode(item),
    label: item.label,
    type: item.type,
    color: item.color,
    body: item.body || "",
  };
}

export function RelationshipEditor({
  relationshipId,
  defaultCharacterId,
  mode = "relationship",
  onClose,
}: {
  relationshipId: string | "new";
  defaultCharacterId: string;
  mode?: "relationship" | "impression";
  onClose: () => void;
}) {
  const { api, project, snapshot, writable } = useRuntime();
  const mutation = useProjectMutation();
  const characterIds = snapshot.characters.map((item) => item.entityId);
  const initial = emptyDraft(defaultCharacterId, characterIds, mode);
  const [currentId, setCurrentId] = useState<string | "new">(relationshipId);
  const [draft, setDraft] = useState<RelationshipDraft>(initial);
  const [baseline, setBaseline] = useState(JSON.stringify(initial));
  const [confirmClose, setConfirmClose] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [message, setMessage] = useState(relationshipId === "new" ? "尚未保存" : "");
  const draftKey = browserDraftKey(project, "relationship", currentId);
  const detail = useQuery({
    queryKey: ["entity", project, currentId],
    queryFn: () => api.detail<Relationship>(currentId),
    enabled: currentId !== "new",
  });

  useEffect(() => {
    const next = currentId === "new"
      ? initial
      : detail.data?.data ? fromRelationship(detail.data.data) : null;
    if (!next) return;
    setDraft(restoreBrowserDraft(browserDraftKey(project, "relationship", currentId), next));
    setBaseline(JSON.stringify(next));
  }, [currentId, detail.data, project]);
  useBrowserDraft(draftKey, draft, baseline);

  const dirty = JSON.stringify(draft) !== baseline;
  const change = <K extends keyof RelationshipDraft>(key: K, value: RelationshipDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setMessage("");
  };
  const changeType = (value: string) => {
    setDraft((current) => ({
      ...current,
      type: value,
      graphScope: FAMILY_TYPES.has(value) && current.graphScope === "core" ? "focus" : current.graphScope,
    }));
    setMessage("");
  };
  const save = async () => {
    if (!writable || mutation.isPending) return;
    setMessage("");
    try {
      let payload: Record<string, unknown> = { ...draft };
      let targetId = currentId;
      const existingPair = currentId === "new" ? snapshot.relationships.find((item) =>
        (item.from === draft.fromCharacterId && item.to === draft.toCharacterId)
        || (item.from === draft.toCharacterId && item.to === draft.fromCharacterId)
      ) : null;
      if (existingPair && mode === "impression") {
        const sameDirection = existingPair.from === draft.fromCharacterId;
        payload = {
          fromImpression: sameDirection ? draft.fromImpression : draft.toImpression,
          toImpression: sameDirection ? draft.toImpression : draft.fromImpression,
        };
        targetId = existingPair.entityId;
      } else if (existingPair) {
        const sameDirection = existingPair.from === draft.fromCharacterId;
        payload = {
          ...draft,
          fromRole: sameDirection ? draft.fromRole : draft.toRole,
          toRole: sameDirection ? draft.toRole : draft.fromRole,
          fromImpression: sameDirection ? draft.fromImpression : draft.toImpression,
          toImpression: sameDirection ? draft.toImpression : draft.fromImpression,
        };
        delete payload.fromCharacterId;
        delete payload.toCharacterId;
        targetId = existingPair.entityId;
      } else if (currentId !== "new") {
        delete payload.fromCharacterId;
        delete payload.toCharacterId;
      }
      const result = await mutation.mutateAsync({
        path: targetId === "new" ? "/relationships" : `/relationships/${encodeURIComponent(targetId)}`,
        method: targetId === "new" ? "POST" : "PATCH",
        payload,
      });
      clearBrowserDraft(draftKey);
      const created = currentId === "new"
        ? result.changed.relationships?.find((item) =>
          (item as unknown as Relationship).from === draft.fromCharacterId
          && (item as unknown as Relationship).to === draft.toCharacterId)
        : null;
      if (targetId !== "new") setCurrentId(targetId);
      else if (created) setCurrentId(String(created.entityId));
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
      clearBrowserDraft(draftKey);
      onClose();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
      setConfirmDelete(false);
    }
  };
  useEditorSaveShortcut(save);
  const discard = () => {
    clearBrowserDraft(draftKey);
    onClose();
  };

  if (currentId !== "new" && detail.isPending) {
    return <div className="dialog-backdrop"><div className="editor-dialog loading-dialog">正在读取人物记录…</div></div>;
  }
  const fromPerson = snapshot.characters.find((item) => item.entityId === draft.fromCharacterId);
  const toPerson = snapshot.characters.find((item) => item.entityId === draft.toCharacterId);
  const impressionMode = mode === "impression";
  const recordName = impressionMode ? "人物印象" : "人物关系";
  const canSave = draft.graphScope !== "hidden" || Boolean(draft.fromImpression.trim() || draft.toImpression.trim());
  return <div className="dialog-backdrop editor-backdrop">
    <section className="editor-dialog relationship-editor-dialog" role="dialog" aria-modal="true" aria-label={`编辑${recordName}`}>
      <header className="dialog-header">
        <div><small>{impressionMode ? "Character Impression" : "Character Relationship"}</small><h2>{currentId === "new" ? (impressionMode ? "记录人物印象" : "建立人物关系") : `${fromPerson?.name || "人物"} · ${toPerson?.name || "人物"}`}</h2></div>
        <div className="dialog-actions">
          {currentId !== "new" && (!impressionMode || draft.graphScope === "hidden") && <button className="icon-button is-danger" aria-label={`删除${recordName}`} title={`删除${recordName}`} onClick={() => setConfirmDelete(true)}><Icon name="trash" /></button>}
          <button className="icon-button is-primary" aria-label={`保存${recordName}`} title="保存" disabled={!dirty || !canSave || mutation.isPending} onClick={() => void save()}><Icon name="save" /></button>
          <button className="icon-button" aria-label="关闭" title="关闭" onClick={() => dirty ? setConfirmClose(true) : onClose()}><Icon name="close" /></button>
        </div>
      </header>
      <div className="editor-settings relationship-settings">
        <label><span>起点人物</span><select disabled={currentId !== "new"} value={draft.fromCharacterId} onChange={(event) => change("fromCharacterId", event.target.value)}>{snapshot.characters.map((item) => <option key={item.entityId} value={item.entityId} disabled={item.entityId === draft.toCharacterId}>{item.name}</option>)}</select></label>
        <label><span>终点人物</span><select disabled={currentId !== "new"} value={draft.toCharacterId} onChange={(event) => change("toCharacterId", event.target.value)}>{snapshot.characters.map((item) => <option key={item.entityId} value={item.entityId} disabled={item.entityId === draft.fromCharacterId}>{item.name}</option>)}</select></label>
        <label className="wide"><span>{fromPerson?.name || "起点人物"}对{toPerson?.name || "终点人物"}的印象</span><input value={draft.fromImpression} onChange={(event) => change("fromImpression", event.target.value)} placeholder="例如：可靠，但仍有所隐瞒" /></label>
        <label className="wide"><span>{toPerson?.name || "终点人物"}对{fromPerson?.name || "起点人物"}的印象</span><input value={draft.toImpression} onChange={(event) => change("toImpression", event.target.value)} placeholder="例如：过于正直，不像普通帮派成员" /></label>
        {!impressionMode && <>
          <label><span>{fromPerson?.name || "起点"}的角色</span><input value={draft.fromRole} onChange={(event) => change("fromRole", event.target.value)} placeholder="例如：委托人" /></label>
          <label><span>{toPerson?.name || "终点"}的角色</span><input value={draft.toRole} onChange={(event) => change("toRole", event.target.value)} placeholder="例如：调查者" /></label>
          <label className="wide"><span>关系名称</span><input value={draft.label} onChange={(event) => change("label", event.target.value)} placeholder="例如：互相试探" /></label>
          <label><span>关系类型</span><input value={draft.type} onChange={(event) => changeType(event.target.value)} placeholder="盟友、对手、亲属…" /></label>
          <label><span>图谱层级</span><select value={draft.graphScope} onChange={(event) => change("graphScope", event.target.value as RelationshipDraft["graphScope"])}><option value="core">核心关系 · 始终显示</option><option value="focus">基础关系 · 选中时显示</option><option value="hidden">仅档案 · 不显示</option></select></label>
          <label><span>图谱连线</span><select disabled={draft.graphScope === "hidden"} value={draft.graphLineMode} onChange={(event) => change("graphLineMode", event.target.value as RelationshipDraft["graphLineMode"])}><option value="single">单线 · 双方共享关系</option><option value="double">双线 · 双方看法不同</option></select></label>
          <label><span>关系颜色</span><input type="color" value={draft.color} onChange={(event) => change("color", event.target.value)} /></label>
          {draft.graphLineMode === "double" && draft.graphScope !== "hidden" && <small className="wide impression-editor-note">双线会显示两个相反方向：{fromPerson?.name || "起点人物"} → {toPerson?.name || "终点人物"}，以及 {toPerson?.name || "终点人物"} → {fromPerson?.name || "起点人物"}。双方印象仍分别保存在上方。</small>}
          <label className="wide"><span>关系说明</span><input value={draft.body} onChange={(event) => change("body", event.target.value)} placeholder="用一句话描述这段关系" /></label>
        </>}
        {impressionMode && <small className="wide impression-editor-note">印象是单向人物笔记，不会生成常驻图谱连线；两人已有关系时会更新原记录，不会重复占用稳定 ID。</small>}
      </div>
      <footer className="editor-footer"><span className={dirty ? "is-dirty" : ""}>{message || (dirty ? "未保存修改已暂存在浏览器" : "已保存")}</span><small>保存和删除会进入统一操作历史</small></footer>
    </section>
    <ConfirmDialog open={confirmClose} title="放弃未保存修改？" message="确认放弃后，浏览器中的这份关系草稿也会被删除。" confirmLabel="放弃修改" danger onCancel={() => setConfirmClose(false)} onConfirm={discard} />
    <ConfirmDialog open={confirmDelete} title={`删除“${draft.label || `这条${recordName}`}”？`} message={`${recordName}会进入统一回收站保留 7 天，可以恢复或撤销。`} confirmLabel="移入回收站" danger onCancel={() => setConfirmDelete(false)} onConfirm={remove} />
  </div>;
}
