import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Character } from "../api/types";
import { useProjectMutation, useRuntime } from "../api/runtime";
import { useEditorSaveShortcut } from "../editor/useEditorSaveShortcut";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { CollapsibleList } from "../components/CollapsibleList";
import { Icon } from "../components/Icon";
import { RelationshipEditor } from "../components/RelationshipEditor";
import { useUiStore } from "../state/ui";

interface EditablePair {
  rowId: string;
  key: string;
  value: string;
}

interface CharacterDraft {
  name: string;
  aliases: string[];
  markers: string[];
  facts: EditablePair[];
  corePersona: EditablePair[];
  supplementPersona: EditablePair[];
  references: string[];
  narrativeRole: Character["narrativeRole"];
  characterScope: Character["characterScope"];
  side: Character["side"];
  mainPlotImpact: number;
  color: string;
  group: string;
}

let pairSequence = 0;

function editablePair(key = "", value = ""): EditablePair {
  pairSequence += 1;
  return { rowId: `persona-${pairSequence}`, key, value };
}

function editablePairs(items: Array<{ key: string; value: string }> = []): EditablePair[] {
  return items.map((item) => editablePair(item.key, item.value));
}

function blankDraft(): CharacterDraft {
  return {
    name: "", aliases: [], markers: [], facts: [],
    corePersona: [editablePair()], supplementPersona: [], references: [],
    narrativeRole: "配角", characterScope: "常驻人物", side: "中立",
    mainPlotImpact: 50, color: "#3f7fc1", group: "",
  };
}

function fromCharacter(item: Character): CharacterDraft {
  return {
    name: item.name, aliases: [...item.aliases], markers: [...item.markers],
    facts: editablePairs(Object.entries(item.facts).map(([key, value]) => ({ key, value }))),
    corePersona: editablePairs(item.corePersona || []),
    supplementPersona: editablePairs(item.supplementPersona || []), narrativeRole: item.narrativeRole,
    characterScope: item.characterScope, side: item.side, mainPlotImpact: item.mainPlotImpact,
    color: item.color, group: item.group, references: [...(item.references || [])],
  };
}

function cleanPairs(items: EditablePair[]): Array<{ key: string; value: string }> {
  return items
    .map((item) => ({ key: item.key.trim(), value: item.value.trim() }))
    .filter((item) => item.key && item.value);
}

function pairError(items: EditablePair[], label: string): string {
  const partial = items.find((item) => Boolean(item.key.trim()) !== Boolean(item.value.trim()));
  if (partial) return `${label}中的名称和内容需要一起填写`;
  const keys = cleanPairs(items).map((item) => item.key);
  const duplicate = keys.find((key, index) => keys.indexOf(key) !== index);
  return duplicate ? `${label}中存在重复名称“${duplicate}”` : "";
}

function KeyValueSection({
  title, description, items, onChange, tone,
}: {
  title: string;
  description: string;
  items: EditablePair[];
  onChange: (items: EditablePair[]) => void;
  tone: "core" | "supplement" | "facts";
}) {
  const update = (rowId: string, key: "key" | "value", value: string) => onChange(items.map((item) => (
    item.rowId === rowId ? { ...item, [key]: value } : item
  )));
  return <section className={`persona-editor-section is-${tone}`} aria-label={title}>
    <header><div className="persona-section-title"><h3>{title}</h3><p>{description}</p></div><button className="icon-button" type="button" aria-label={`添加${title}`} title={`添加${title}`} onClick={() => onChange([...items, editablePair()])}><Icon name="plus" /></button></header>
    {items.length ? <div className="persona-kv-list"><div className="persona-kv-head" aria-hidden="true"><span>名称</span><span>内容</span><span /></div>{items.map((item, index) => <article className="persona-kv-row" key={item.rowId}>
      <label><input aria-label={`${title} ${index + 1} 名称`} value={item.key} placeholder={tone === "core" ? "例如：核心欲望" : tone === "supplement" ? "例如：生活习惯" : "例如：职业"} onChange={(event) => update(item.rowId, "key", event.target.value)} /></label>
      <label><textarea aria-label={`${title} ${index + 1} 内容`} rows={1} value={item.value} placeholder={tone === "core" ? "决定人物选择和冲突的设定" : tone === "supplement" ? "丰富人物但不改变核心逻辑的细节" : "客观、稳定、便于快速查阅的信息"} onChange={(event) => update(item.rowId, "value", event.target.value)} /></label>
      <button className="icon-button is-danger" type="button" aria-label={`移除${title}第 ${index + 1} 项`} title="移除这一项" onClick={() => onChange(items.filter((candidate) => candidate.rowId !== item.rowId))}><Icon name="trash" /></button>
    </article>)}</div> : <div className="persona-empty-add"><span>还没有{title}</span><button className="icon-button" type="button" aria-label={`添加第一项${title}`} title={`添加${title}`} onClick={() => onChange([editablePair()])}><Icon name="plus" /></button></div>}
  </section>;
}

function CharacterEditor({ entityId, onClose }: { entityId: string | "new"; onClose: () => void }) {
  const { api, project, snapshot } = useRuntime();
  const mutation = useProjectMutation();
  const [currentId, setCurrentId] = useState<string | "new">(entityId);
  const detail = useQuery({
    queryKey: ["entity", project, currentId],
    queryFn: () => api.detail<Character>(currentId),
    enabled: currentId !== "new",
  });
  const [draft, setDraft] = useState<CharacterDraft>(() => blankDraft());
  const [baseline, setBaseline] = useState("");
  const [message, setMessage] = useState("");
  const [confirmClose, setConfirmClose] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmRename, setConfirmRename] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  useEffect(() => {
    const next = currentId === "new" ? blankDraft() : detail.data?.data ? fromCharacter(detail.data.data) : null;
    if (next) { setDraft(next); setBaseline(JSON.stringify(next)); }
  }, [currentId, detail.data]);
  const dirty = Boolean(baseline && JSON.stringify(draft) !== baseline);
  const change = <K extends keyof CharacterDraft>(key: K, value: CharacterDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const referenceSourceCount = currentId === "new" ? 0 : new Set([
    ...snapshot.characters.filter((item) => item.references?.includes(currentId)).map((item) => item.entityId),
    ...snapshot.plots.filter((item) => item.references?.includes(currentId) || item.people.includes(currentId)).map((item) => item.entityId),
    ...snapshot.entries.filter((item) => item.references?.includes(currentId) || item.people.includes(currentId)).map((item) => item.entityId),
    ...snapshot.fragments.filter((item) => item.references?.includes(currentId)).map((item) => item.entityId),
    ...snapshot.relationships.filter((item) => item.references?.includes(currentId)).map((item) => item.entityId),
  ]).size;
  const persist = async () => {
    setMessage("");
    const validation = [
      pairError(draft.facts, "人物档案"),
      pairError(draft.corePersona, "核心人设"),
      pairError(draft.supplementPersona, "补充人设"),
    ].find(Boolean);
    if (validation) { setMessage(validation); return; }
    try {
      const corePersona = cleanPairs(draft.corePersona);
      const supplementPersona = cleanPairs(draft.supplementPersona);
      const result = await mutation.mutateAsync({
        path: currentId === "new" ? "/characters" : `/characters/${encodeURIComponent(currentId)}`,
        method: currentId === "new" ? "POST" : "PATCH",
        payload: {
          ...draft,
          facts: Object.fromEntries(cleanPairs(draft.facts).map((item) => [item.key, item.value])),
          corePersona,
          supplementPersona,
        },
      });
      if (currentId === "new") {
        const created = result.changed.characters?.find((item) => !snapshot.characters.some((existing) => existing.entityId === item.entityId));
        if (created?.entityId) setCurrentId(String(created.entityId));
      }
      setBaseline(JSON.stringify(draft));
      setMessage(result.warnings[0] || "已保存");
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存失败"); }
  };
  const save = async () => {
    const previous = baseline ? (JSON.parse(baseline) as CharacterDraft).name : draft.name;
    if (currentId !== "new" && draft.name.trim() !== previous.trim()) {
      setConfirmRename(true);
      return;
    }
    await persist();
  };
  const remove = async () => {
    if (currentId === "new") return;
    try {
      await mutation.mutateAsync({ path: `/entities/${encodeURIComponent(currentId)}`, method: "DELETE", payload: {} });
      onClose();
    } catch (error) { setMessage(error instanceof Error ? error.message : "删除失败"); }
  };
  useEditorSaveShortcut(save);
  if (entityId !== "new" && detail.isPending) return <div className="dialog-backdrop"><div className="editor-dialog loading-dialog">正在读取人物档案…</div></div>;
  return <div className="dialog-backdrop editor-backdrop">
    <section className="editor-dialog character-editor-dialog" role="dialog" aria-modal="true" aria-label="编辑人物档案">
      <header className="dialog-header"><div><small>Character Profile</small><h2>{currentId === "new" ? "新建人物" : `编辑档案 · ${draft.name}`}</h2></div><div className="dialog-actions">{currentId !== "new" && <button className="icon-button is-danger" aria-label="删除人物" title="删除人物" onClick={() => setConfirmDelete(true)}><Icon name="trash" /></button>}<button className="icon-button is-primary" aria-label="保存（⌘/Ctrl+S）" title="保存" disabled={!dirty || mutation.isPending} onClick={() => void save()}><Icon name="save" /></button><button className="icon-button" aria-label="关闭" title="关闭" onClick={() => dirty ? setConfirmClose(true) : onClose()}><Icon name="close" /></button></div></header>
      <div className="character-editor-settings"><button className="settings-toggle" type="button" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((value) => !value)}><Icon name="settings" /><span>人物档案设置</span><small>{settingsOpen ? "收起" : "展开"}</small></button>
      {settingsOpen && <div className="profile-editor-grid">
        <label className="wide"><span>姓名</span><input value={draft.name} onChange={(event) => change("name", event.target.value)} /></label>
        <label><span>戏份定位</span><select value={draft.narrativeRole} onChange={(event) => change("narrativeRole", event.target.value as CharacterDraft["narrativeRole"])}><option>主角</option><option>配角</option></select></label>
        <label><span>出场类型</span><select value={draft.characterScope} onChange={(event) => change("characterScope", event.target.value as CharacterDraft["characterScope"])}><option>主线人物</option><option>常驻人物</option><option>一次性角色</option><option>待定角色</option></select></label>
        <label><span>阵营</span><select value={draft.side} onChange={(event) => change("side", event.target.value as CharacterDraft["side"])}><option>主角方</option><option>中立</option><option>反派方</option></select></label>
        <label><span>主线影响 <small>0 最小 · 100 最大</small></span><input type="number" min="0" max="100" value={draft.mainPlotImpact} onChange={(event) => change("mainPlotImpact", Number(event.target.value))} /></label>
        <label><span>分组</span><input value={draft.group} onChange={(event) => change("group", event.target.value)} /></label>
        <label><span>颜色</span><input type="color" value={draft.color} onChange={(event) => change("color", event.target.value)} /></label>
        <label className="wide"><span>别名（逗号分隔）</span><input value={draft.aliases.join("，")} onChange={(event) => change("aliases", event.target.value.split(/[，,]/).map((value) => value.trim()).filter(Boolean))} /></label>
        <label className="wide"><span>标识（逗号分隔）</span><input value={draft.markers.join("，")} onChange={(event) => change("markers", event.target.value.split(/[，,]/).map((value) => value.trim()).filter(Boolean))} /></label>
      </div>}</div>
      <div className="persona-editor-scroll">
        <KeyValueSection title="核心人设" description="只放会决定人物长期选择、关系和冲突的设定。" items={draft.corePersona} onChange={(items) => change("corePersona", items)} tone="core" />
        <KeyValueSection title="补充人设" description="记录习惯、偏好、经历等可继续扩展的细节，不与核心设定混在一起。" items={draft.supplementPersona} onChange={(items) => change("supplementPersona", items)} tone="supplement" />
        <KeyValueSection title="人物档案" description="年龄、职业、身份、住址等适合快速查阅的客观信息。" items={draft.facts} onChange={(items) => change("facts", items)} tone="facts" />
      </div>
      <footer className="editor-footer"><span className={dirty ? "is-dirty" : ""}>{message || (dirty ? "有未保存修改" : "已保存")}</span><small>保存不会关闭档案或重置当前状态</small></footer>
    </section>
    <ConfirmDialog open={confirmClose} title="放弃未保存修改？" message="关闭后，本次人物档案修改会丢失。" confirmLabel="放弃修改" danger onCancel={() => setConfirmClose(false)} onConfirm={onClose} />
    <ConfirmDialog open={confirmDelete} title={`删除“${draft.name}”？`} message="人物会进入回收站；图谱节点和相连关系会立即从活动视图隐藏，恢复人物后有效关系会自然回来。" confirmLabel="移入回收站" danger onCancel={() => setConfirmDelete(false)} onConfirm={remove} />
    <ConfirmDialog open={confirmRename} title={`重命名为“${draft.name}”？`} message={`人物稳定 ID 不会改变；系统会在同一事务中更新 ${referenceSourceCount} 篇带稳定引用的相关正文，整次重命名可以撤销。`} confirmLabel="确认重命名" onCancel={() => setConfirmRename(false)} onConfirm={() => { setConfirmRename(false); void persist(); }} />
  </div>;
}

export default function CharactersPage() {
  const { snapshot, writable } = useRuntime();
  const selected = useUiStore((state) => state.selectedCharacterId);
  const select = useUiStore((state) => state.selectCharacter);
  const [editor, setEditor] = useState<string | "new" | null>(null);
  const [relationshipEditor, setRelationshipEditor] = useState<string | "new" | null>(null);
  const [query, setQuery] = useState("");
  const [minorOpen, setMinorOpen] = useState(false);
  const major = snapshot.characters.filter((item) => !["一次性角色", "待定角色"].includes(item.characterScope));
  const minor = snapshot.characters.filter((item) => ["一次性角色", "待定角色"].includes(item.characterScope));
  const source = minorOpen ? minor : major;
  const characters = source.filter((item) => `${item.name} ${item.aliases.join(" ")} ${item.group} ${item.markers.join(" ")}`.toLowerCase().includes(query.toLowerCase()));
  useEffect(() => {
    if (!selected && characters[0]) select(characters[0].entityId);
  }, [characters, select, selected]);
  const current = snapshot.characters.find((item) => item.entityId === selected) || characters[0];
  const relatedPlots = current ? snapshot.plots.filter((plot) => plot.people.includes(current.entityId)) : [];
  const relationships = current ? snapshot.relationships.filter((item) => item.from === current.entityId || item.to === current.entityId) : [];
  return <section className="workspace-page character-page-new">
    <header className="page-header"><div><small>Character Workspace</small><h1>人物管理中心</h1><p>集中查看人物定位、剧情参与和关系；临时角色仍收在次级抽屉中。</p></div><div className="page-actions"><button className={`minor-toggle${minorOpen ? " is-active" : ""}`} aria-pressed={minorOpen} title={minorOpen ? "返回主要角色" : "查看临时角色"} onClick={() => setMinorOpen((value) => !value)}>{minorOpen ? "主要角色" : "临时角色"} <strong>{minorOpen ? major.length : minor.length}</strong></button>{writable && <button className="icon-button is-primary" aria-label="新建人物" title="新建人物" onClick={() => setEditor("new")}><Icon name="plus" /></button>}</div></header>
    <div className="two-column-workspace">
      <aside className="sticky-rail character-library"><label className="rail-search"><Icon name="search" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索人物、别名或分组" /></label><div className="character-list-new">{characters.map((item) => <button key={item.entityId} className={current?.entityId === item.entityId ? "is-active" : ""} onClick={() => select(item.entityId)}><span className="avatar" style={{ background: item.gradient || item.color }}>{item.name.slice(0, 1)}</span><span><strong>{item.name}</strong><small>{item.narrativeRole} · {item.characterScope}</small></span></button>)}</div></aside>
      <article className="sticky-detail profile-detail-panel">{current ? <>
        <header><span className="large-avatar" style={{ background: current.gradient || current.color }}>{current.name.slice(0, 1)}</span><div><small>{current.group || "未分组"}</small><h2>{current.name}</h2><p>{current.narrativeRole} · {current.characterScope} · {current.side}</p></div>{writable && <button className="icon-button" aria-label="编辑人物档案" title="编辑档案" onClick={() => setEditor(current.entityId)}><Icon name="edit" /></button>}</header>
        <div className="profile-kv-grid"><div><span>主线影响</span><strong>{current.mainPlotImpact}</strong></div>{Object.entries(current.facts).map(([key, value]) => <div key={key}><span>{key}</span><strong>{value}</strong></div>)}</div>
        <section><h3>核心人设</h3>{current.corePersona?.length ? <dl className="persona-read-list is-core">{current.corePersona.map((item) => <div key={item.key}><dt>{item.key}</dt><dd>{item.value}</dd></div>)}</dl> : <p className="empty-copy">还没有核心人设</p>}</section>
        {Boolean(current.supplementPersona?.length) && <section><h3>补充人设</h3><dl className="persona-read-list">{current.supplementPersona?.map((item) => <div key={item.key}><dt>{item.key}</dt><dd>{item.value}</dd></div>)}</dl></section>}
        <section><h3>相关剧情</h3><CollapsibleList items={relatedPlots} itemKey={(plot) => plot.entityId} resetKey={current.entityId} label={`${current.name}的相关剧情`} className="related-cards" emptyText="还没有相关剧情" renderItem={(plot) => <button onClick={() => { useUiStore.getState().selectPlot(plot.entityId); useUiStore.getState().navigate("story"); }}><strong>{plot.title}</strong><small>第 {plot.sequence} 篇</small></button>} /></section>
        <section><div className="section-heading"><h3>人物关系</h3>{writable && <button className="icon-button" aria-label={`为${current.name}建立人物关系`} title="建立人物关系" onClick={() => setRelationshipEditor("new")}><Icon name="plus" /></button>}</div><CollapsibleList items={relationships} itemKey={(relation) => relation.entityId} resetKey={current.entityId} label={`${current.name}的人物关系`} className="relationship-list-new" emptyText="还没有记录人物关系" renderItem={(relation) => { const otherId = relation.from === current.entityId ? relation.to : relation.from; const other = snapshot.characters.find((item) => item.entityId === otherId); return <article><button className="relationship-target" onClick={() => other && select(other.entityId)}><span style={{ background: relation.color }} /><strong>{other?.name || "已删除人物"}</strong><small>{relation.label || relation.type || "未命名关系"}</small></button>{writable && <button className="icon-button" aria-label={`编辑${relation.label || "人物关系"}`} title="编辑人物关系" onClick={() => setRelationshipEditor(relation.entityId)}><Icon name="edit" /></button>}</article>; }} /></section>
      </> : <div className="empty-state"><Icon name="person" /><h2>选择一个人物</h2></div>}</article>
    </div>
    {editor && <CharacterEditor entityId={editor} onClose={() => setEditor(null)} />}
    {relationshipEditor && current && <RelationshipEditor relationshipId={relationshipEditor} defaultCharacterId={current.entityId} onClose={() => setRelationshipEditor(null)} />}
  </section>;
}
