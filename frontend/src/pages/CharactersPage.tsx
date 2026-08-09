import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Character, Fragment, Plot, Relationship } from "../api/types";
import { useProjectMutation, useRuntime } from "../api/runtime";
import { useEditorSaveShortcut } from "../editor/useEditorSaveShortcut";
import { browserDraftKey, clearBrowserDraft, restoreBrowserDraft, useBrowserDraft } from "../editor/browserDraft";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { CollapsibleList } from "../components/CollapsibleList";
import { Icon } from "../components/Icon";
import { RelationshipEditor } from "../components/RelationshipEditor";
import { useUiStore } from "../state/ui";
import { compactStoryPreview } from "../storyPreview";
import { CompleteBlockPreview } from "../components/CompleteBlockPreview";
import { avatarBackground, avatarGradient, randomContentColor } from "../theme/contentColors";

interface EditablePair {
  rowId: string;
  key: string;
  value: string;
}

interface EditableBullet {
  rowId: string;
  value: string;
}

interface CharacterDraft {
  name: string;
  aliases: string[];
  markers: string[];
  facts: EditablePair[];
  corePersona: EditableBullet[];
  supplementPersona: EditableBullet[];
  destinyOutline: string;
  references: string[];
  narrativeRole: "主角" | "反派" | "中立" | "配角";
  characterScope: Character["characterScope"];
  mainPlotImpact: number;
  color: string;
  group: string;
  graphVisible: boolean;
}

let pairSequence = 0;

function editablePair(key = "", value = ""): EditablePair {
  pairSequence += 1;
  return { rowId: `persona-${pairSequence}`, key, value };
}

function editablePairs(items: Array<{ key: string; value: string }> = []): EditablePair[] {
  return items.map((item) => editablePair(item.key, item.value));
}

function personaText(item: { key: string; value: string }): string {
  return /^要点 \d+$/.test(item.key) ? item.value : [item.key, item.value].filter(Boolean).join("：");
}

function editableBullets(items: Array<{ key: string; value: string }> = []): EditableBullet[] {
  return items.map((item) => ({ rowId: editablePair().rowId, value: personaText(item) }));
}

function newBullet(): EditableBullet {
  return { rowId: editablePair().rowId, value: "" };
}

function blankDraft(): CharacterDraft {
  return {
    name: "", aliases: [], markers: [], facts: [],
    corePersona: [newBullet()], supplementPersona: [], destinyOutline: "", references: [],
    narrativeRole: "配角", characterScope: "常驻人物",
    mainPlotImpact: 50, color: randomContentColor(), group: "", graphVisible: false,
  };
}

function fromCharacter(item: Character): CharacterDraft {
  return {
    name: item.name, aliases: [...item.aliases], markers: [...item.markers],
    facts: editablePairs(Object.entries(item.facts).map(([key, value]) => ({ key, value }))),
    corePersona: editableBullets(item.corePersona || []),
    supplementPersona: editableBullets(item.supplementPersona || []), destinyOutline: item.destinyOutline || "", narrativeRole: displayRole(item),
    characterScope: item.characterScope, mainPlotImpact: item.mainPlotImpact,
    color: item.color, group: item.group, graphVisible: item.graphVisible !== false,
    references: [...(item.references || [])],
  };
}

export function displayRole(item: Pick<Character, "narrativeRole" | "side">): CharacterDraft["narrativeRole"] {
  if (item.narrativeRole === "主角") return "主角";
  if (item.side === "反派方") return "反派";
  if (item.side === "中立") return "中立";
  return "配角";
}

export function storedClassification(role: CharacterDraft["narrativeRole"]): Pick<Character, "narrativeRole" | "side"> {
  if (role === "主角") return { narrativeRole: "主角", side: "主角方" };
  if (role === "反派") return { narrativeRole: "配角", side: "反派方" };
  if (role === "中立") return { narrativeRole: "配角", side: "中立" };
  return { narrativeRole: "配角", side: "主角方" };
}

export function graphVisibilityAfterRole(current: boolean, role: CharacterDraft["narrativeRole"]): boolean {
  return role === "配角" ? current : true;
}

export function graphVisibilityAfterScope(current: boolean, scope: CharacterDraft["characterScope"]): boolean {
  return ["一次性角色", "待定角色"].includes(scope) ? false : current;
}

export function relationshipImpressionFor(
  relationship: Pick<Relationship, "from" | "to" | "fromImpression" | "toImpression">,
  characterId: string,
): string {
  if (relationship.from === characterId) return relationship.fromImpression || "";
  if (relationship.to === characterId) return relationship.toImpression || "";
  return "";
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

function cleanBullets(items: EditableBullet[]): Array<{ key: string; value: string }> {
  return items
    .map((item) => item.value.trim())
    .filter(Boolean)
    .map((value, index) => ({ key: `要点 ${index + 1}`, value }));
}

function AutoSizeTextarea({ value, onChange, ...props }: {
  value: string;
  onChange: (value: string) => void;
} & Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange">) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    element.style.height = "0";
    element.style.height = `${element.scrollHeight}px`;
  }, [value]);
  return <textarea ref={ref} rows={1} value={value} onChange={(event) => onChange(event.target.value)} {...props} />;
}

function BulletPersonaSection({
  title, description, items, onChange, tone,
}: {
  title: string;
  description: string;
  items: EditableBullet[];
  onChange: (items: EditableBullet[]) => void;
  tone: "core" | "supplement";
}) {
  const update = (rowId: string, value: string) => onChange(items.map((item) => item.rowId === rowId ? { ...item, value } : item));
  return <section className={`persona-editor-section persona-bullet-section is-${tone}`} aria-label={title}>
    <header><div className="persona-section-title"><div><h3>{title}</h3><span>{items.length} 项</span></div><p>{description}</p></div><button className="persona-add-action" type="button" onClick={() => onChange([...items, newBullet()])}><Icon name="plus" /><span>添加一项</span></button></header>
    {items.length ? <div className="persona-bullet-editor">{items.map((item, index) => <article key={item.rowId}>
      <span className="persona-bullet-mark" aria-hidden="true" />
      <AutoSizeTextarea aria-label={`${title}第 ${index + 1} 项`} value={item.value} placeholder="输入完整的人设描述…" onChange={(value) => update(item.rowId, value)} />
      <button className="icon-button is-danger" type="button" aria-label={`移除${title}第 ${index + 1} 项`} title="移除这一项" onClick={() => onChange(items.filter((candidate) => candidate.rowId !== item.rowId))}><Icon name="trash" /></button>
    </article>)}</div> : <button className="persona-empty-add" type="button" onClick={() => onChange([newBullet()])}><Icon name="plus" /><span>添加第一项{title}</span></button>}
  </section>;
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
    <header><div className="persona-section-title"><div><h3>{title}</h3><span>{items.length} 项</span></div><p>{description}</p></div><button className="persona-add-action" type="button" onClick={() => onChange([...items, editablePair()])}><Icon name="plus" /><span>添加一项</span></button></header>
    {items.length ? <div className="persona-kv-list"><div className="persona-kv-head" aria-hidden="true"><span /><span>名称</span><span>描述</span><span /></div>{items.map((item, index) => <article className="persona-kv-row" key={item.rowId}>
      <span className="persona-row-index" aria-hidden="true">{index + 1}</span>
      <label><input aria-label={`${title} ${index + 1} 名称`} value={item.key} placeholder={tone === "core" ? "例如：核心欲望" : tone === "supplement" ? "例如：生活习惯" : "例如：职业"} onChange={(event) => update(item.rowId, "key", event.target.value)} /></label>
      <label><textarea aria-label={`${title} ${index + 1} 内容`} rows={1} value={item.value} placeholder={tone === "core" ? "决定人物选择和冲突的设定" : tone === "supplement" ? "丰富人物但不改变核心逻辑的细节" : "客观、稳定、便于快速查阅的信息"} onChange={(event) => update(item.rowId, "value", event.target.value)} /></label>
      <button className="icon-button is-danger" type="button" aria-label={`移除${title}第 ${index + 1} 项`} title="移除这一项" onClick={() => onChange(items.filter((candidate) => candidate.rowId !== item.rowId))}><Icon name="trash" /></button>
    </article>)}</div> : <button className="persona-empty-add" type="button" onClick={() => onChange([editablePair()])}><Icon name="plus" /><span>添加第一项{title}</span></button>}
  </section>;
}

const PINNED_CHARACTER_NAMES = ["沈清妙", "黎清妍", "姜昭妍"];

export function orderCharactersForList(characters: Character[]): Character[] {
  const pinnedOrder = new Map(PINNED_CHARACTER_NAMES.map((name, index) => [name, index]));
  return characters
    .map((character, index) => ({ character, index }))
    .sort((left, right) => {
      const leftOrder = pinnedOrder.get(left.character.name) ?? PINNED_CHARACTER_NAMES.length;
      const rightOrder = pinnedOrder.get(right.character.name) ?? PINNED_CHARACTER_NAMES.length;
      return leftOrder - rightOrder || left.index - right.index;
    })
    .map(({ character }) => character);
}

function CharacterList({
  characters, currentId, duplicateNames, select,
}: {
  characters: Character[];
  currentId?: string;
  duplicateNames: Set<string>;
  select: (entityId: string) => void;
}) {
  return <>{characters.map((item) => <button key={item.entityId} className={currentId === item.entityId ? "is-active" : ""} onClick={() => select(item.entityId)}><span className="avatar" style={{ background: avatarBackground(item) }}>{item.name.slice(0, 1)}</span><span><strong>{item.name}</strong><small>{displayRole(item)} · {item.characterScope}{duplicateNames.has(item.name) ? ` · ID ${item.id}` : ""}</small></span></button>)}</>;
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
  const draftKey = browserDraftKey(project, "character", currentId);
  useEffect(() => {
    const next = currentId === "new" ? blankDraft() : detail.data?.data ? fromCharacter(detail.data.data) : null;
    if (next) {
      setDraft(restoreBrowserDraft(browserDraftKey(project, "character", currentId), next));
      setBaseline(JSON.stringify(next));
    }
  }, [currentId, detail.data, project]);
  useBrowserDraft(draftKey, draft, baseline);
  const dirty = Boolean(baseline && JSON.stringify(draft) !== baseline);
  const change = <K extends keyof CharacterDraft>(key: K, value: CharacterDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const changeRole = (narrativeRole: CharacterDraft["narrativeRole"]) => setDraft((current) => ({
    ...current,
    narrativeRole,
    graphVisible: graphVisibilityAfterRole(current.graphVisible, narrativeRole),
  }));
  const changeScope = (characterScope: CharacterDraft["characterScope"]) => setDraft((current) => ({
    ...current,
    characterScope,
    graphVisible: graphVisibilityAfterScope(current.graphVisible, characterScope),
  }));
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
    ].find(Boolean);
    if (validation) { setMessage(validation); return; }
    try {
      const corePersona = cleanBullets(draft.corePersona);
      const supplementPersona = cleanBullets(draft.supplementPersona);
      const classification = storedClassification(draft.narrativeRole);
      const result = await mutation.mutateAsync({
        path: currentId === "new" ? "/characters" : `/characters/${encodeURIComponent(currentId)}`,
        method: currentId === "new" ? "POST" : "PATCH",
        payload: {
          ...draft,
          ...classification,
          facts: Object.fromEntries(cleanPairs(draft.facts).map((item) => [item.key, item.value])),
          corePersona,
          supplementPersona,
        },
      });
      clearBrowserDraft(draftKey);
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
      clearBrowserDraft(draftKey);
      onClose();
    } catch (error) { setMessage(error instanceof Error ? error.message : "删除失败"); }
  };
  useEditorSaveShortcut(save);
  const discard = () => {
    clearBrowserDraft(draftKey);
    onClose();
  };
  if (entityId !== "new" && detail.isPending) return <div className="dialog-backdrop"><div className="editor-dialog loading-dialog">正在读取人物档案…</div></div>;
  return <div className="dialog-backdrop editor-backdrop">
    <section className="editor-dialog character-editor-dialog" role="dialog" aria-modal="true" aria-label="编辑人物档案">
      <header className="dialog-header"><div><small>Character Profile</small><h2>{currentId === "new" ? "新建人物" : `编辑档案 · ${draft.name}`}</h2></div><div className="dialog-actions">{currentId !== "new" && <button className="icon-button is-danger" aria-label="删除人物" title="删除人物" onClick={() => setConfirmDelete(true)}><Icon name="trash" /></button>}<button className="icon-button is-primary" aria-label="保存（⌘/Ctrl+S）" title="保存" disabled={!dirty || mutation.isPending} onClick={() => void save()}><Icon name="save" /></button><button className="icon-button" aria-label="关闭" title="关闭" onClick={() => dirty ? setConfirmClose(true) : onClose()}><Icon name="close" /></button></div></header>
      <div className="character-editor-body">
        <aside className="character-editor-settings">
          <header><span className="character-editor-avatar" style={{ background: avatarGradient(draft.color) }}>{draft.name.trim().slice(0, 1) || "人"}</span><div><small>Basic Profile</small><h3>基础资料</h3></div></header>
          <div className="profile-editor-grid">
            <label className="wide"><span>姓名</span><input value={draft.name} placeholder="输入人物姓名" onChange={(event) => change("name", event.target.value)} /></label>
            <label><span>戏份定位</span><select value={draft.narrativeRole} onChange={(event) => changeRole(event.target.value as CharacterDraft["narrativeRole"])}><option>主角</option><option>反派</option><option>中立</option><option>配角</option></select></label>
            <label><span>出场类型</span><select value={draft.characterScope} onChange={(event) => changeScope(event.target.value as CharacterDraft["characterScope"])}><option>主线人物</option><option>常驻人物</option><option>一次性角色</option><option>待定角色</option></select></label>
            <label className="wide graph-visibility-field">
              <span>人物图谱</span>
              <button
                type="button"
                role="checkbox"
                aria-checked={draft.graphVisible}
                className={draft.graphVisible ? "graph-visibility-choice is-selected" : "graph-visibility-choice"}
                onClick={() => change("graphVisible", !draft.graphVisible)}
              >
                <span className="choice-circle" aria-hidden="true"><span /></span>
                <span>显示在图谱中</span>
              </button>
            </label>
            <label><span>主线影响 <small>0–100</small></span><input type="number" min="0" max="100" value={draft.mainPlotImpact} onChange={(event) => change("mainPlotImpact", Number(event.target.value))} /></label>
            <label className="wide"><span>分组</span><input value={draft.group} placeholder="例如：沈家" onChange={(event) => change("group", event.target.value)} /></label>
            <label className="color-field"><span>人物颜色</span><span><input type="color" value={draft.color} onChange={(event) => change("color", event.target.value)} /><small>{draft.color.toUpperCase()}</small></span></label>
            <label className="wide"><span>别名</span><input value={draft.aliases.join("，")} placeholder="多个别名用逗号分隔" onChange={(event) => change("aliases", event.target.value.split(/[，,]/).map((value) => value.trim()).filter(Boolean))} /></label>
            <label className="wide"><span>标识</span><input value={draft.markers.join("，")} placeholder="多个标识用逗号分隔" onChange={(event) => change("markers", event.target.value.split(/[，,]/).map((value) => value.trim()).filter(Boolean))} /></label>
          </div>
        </aside>
        <main className="persona-editor-scroll">
          <header className="persona-workspace-heading"><div><small>Character Notes</small><h3>人物设定</h3></div><p>用清晰的名称和描述记录人物特征，随时可以继续补充。</p></header>
          <section className="character-outline-editor">
            <header><div><h3>人物大纲</h3><p>讲述人物的命运走向、关键转折和最终归宿；留空时不会在人物详情中显示。</p></div></header>
            <AutoSizeTextarea aria-label="人物大纲" value={draft.destinyOutline} placeholder="例如：她从被家族安排的人生中逐渐醒来，最终选择离开既定轨道……" onChange={(value) => change("destinyOutline", value)} />
          </section>
          <BulletPersonaSection title="核心人设" description="决定人物长期选择、关系和冲突。" items={draft.corePersona} onChange={(items) => change("corePersona", items)} tone="core" />
          <BulletPersonaSection title="补充人设" description="习惯、偏好、经历等扩展细节。" items={draft.supplementPersona} onChange={(items) => change("supplementPersona", items)} tone="supplement" />
          <KeyValueSection title="人物档案" description="年龄、职业、身份、住址等客观信息。" items={draft.facts} onChange={(items) => change("facts", items)} tone="facts" />
        </main>
      </div>
      <footer className="editor-footer"><span className={dirty ? "is-dirty" : ""}>{message || (dirty ? "未保存修改已暂存在浏览器" : "已保存")}</span><small>保存不会关闭档案或重置当前状态</small></footer>
    </section>
    <ConfirmDialog open={confirmClose} title="放弃未保存修改？" message="确认放弃后，浏览器中的这份人物草稿也会被删除。" confirmLabel="放弃修改" danger onCancel={() => setConfirmClose(false)} onConfirm={discard} />
    <ConfirmDialog open={confirmDelete} title={`删除“${draft.name}”？`} message="人物会进入回收站；图谱节点和相连关系会立即从活动视图隐藏，恢复人物后有效关系会自然回来。" confirmLabel="移入回收站" danger onCancel={() => setConfirmDelete(false)} onConfirm={remove} />
    <ConfirmDialog open={confirmRename} title={`重命名为“${draft.name}”？`} message={`人物稳定 ID 不会改变；系统会在同一事务中更新 ${referenceSourceCount} 篇带稳定引用的相关正文，整次重命名可以撤销。`} confirmLabel="确认重命名" onCancel={() => setConfirmRename(false)} onConfirm={() => { setConfirmRename(false); void persist(); }} />
  </div>;
}

export default function CharactersPage() {
  const { snapshot, writable } = useRuntime();
  const selected = useUiStore((state) => state.selectedCharacterId);
  const select = useUiStore((state) => state.selectCharacter);
  const openPlotFromCharacter = useUiStore((state) => state.openPlotFromCharacter);
  const selectFragment = useUiStore((state) => state.selectFragment);
  const [editor, setEditor] = useState<string | "new" | null>(null);
  const [relationshipEditor, setRelationshipEditor] = useState<{ id: string | "new"; mode: "relationship" | "impression" } | null>(null);
  const [query, setQuery] = useState("");
  const [minorOpen, setMinorOpen] = useState(false);
  const duplicateNames = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of snapshot.characters) counts.set(item.name, (counts.get(item.name) || 0) + 1);
    return new Set([...counts].filter(([, count]) => count > 1).map(([name]) => name));
  }, [snapshot.characters]);
  const major = snapshot.characters.filter((item) => !["一次性角色", "待定角色"].includes(item.characterScope));
  const minor = snapshot.characters.filter((item) => ["一次性角色", "待定角色"].includes(item.characterScope));
  const source = minorOpen ? minor : major;
  const characters = orderCharactersForList(source.filter((item) => `${item.name} ${item.aliases.join(" ")} ${item.group} ${item.markers.join(" ")}`.toLowerCase().includes(query.toLowerCase())));
  useEffect(() => {
    if (!selected && characters[0]) select(characters[0].entityId);
  }, [characters, select, selected]);
  const current = snapshot.characters.find((item) => item.entityId === selected) || characters[0];
  const relatedStories: Array<
    { kind: "plot"; item: Plot } | { kind: "fragment"; item: Fragment }
  > = current ? [
    ...snapshot.plots
      .filter((plot) => plot.people.includes(current.entityId))
      .map((item) => ({ kind: "plot" as const, item })),
    ...snapshot.fragments
      .filter((fragment) =>
        fragment.fragmentType !== "line"
        && fragment.references?.includes(current.entityId)
      )
      .map((item) => ({ kind: "fragment" as const, item })),
  ] : [];
  const connections = current ? snapshot.relationships.filter((item) => item.from === current.entityId || item.to === current.entityId) : [];
  const relationships = connections.filter((item) => Boolean(item.label || item.type || item.fromRole || item.toRole));
  const impressions = current ? connections.filter((item) => Boolean(relationshipImpressionFor(item, current.entityId))) : [];
  const organizations = current ? snapshot.entries.filter((item) => item.type === "组织" && (item.members || []).some((member) => member.characterId === current.entityId)) : [];
  return <section className="workspace-page character-page-new">
    <header className="page-header"><div><small>Character Workspace</small><h1>人物管理中心</h1><p>集中查看人物定位、组织归属、剧情参与、关系和看法。</p></div><div className="page-actions"><button className={`minor-toggle${minorOpen ? " is-active" : ""}`} aria-pressed={minorOpen} title={minorOpen ? "返回主要角色" : "查看临时角色"} onClick={() => setMinorOpen((value) => !value)}>{minorOpen ? "主要角色" : "临时角色"} <strong>{minorOpen ? major.length : minor.length}</strong></button><button className="icon-button" aria-label="管理组织" title="前往组织与设定" onClick={() => useUiStore.getState().navigate("entries")}><Icon name="book" /></button>{writable && <button className="icon-button character-create-button" aria-label="新建人物" title="创建人物档案" onClick={() => setEditor("new")}><Icon name="person-add" /></button>}</div></header>
    <div className="two-column-workspace">
      <aside className="sticky-rail character-library"><label className="rail-search"><Icon name="search" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索人物、别名或标识" /></label><div className="character-list-new"><CharacterList characters={characters} currentId={current?.entityId} duplicateNames={duplicateNames} select={select} /></div></aside>
      <article className="sticky-detail profile-detail-panel">{current ? <>
        <header><span className="large-avatar" style={{ background: avatarBackground(current) }}>{current.name.slice(0, 1)}</span><div><small>{current.group || "未分组"}{duplicateNames.has(current.name) ? ` · ID ${current.id}` : ""}</small><h2>{current.name}</h2><p>{displayRole(current)} · {current.characterScope}</p></div>{writable && <button className="icon-button" aria-label="编辑人物档案" title="编辑档案" onClick={() => setEditor(current.entityId)}><Icon name="edit" /></button>}</header>
        <div className="profile-kv-grid"><div><span>主线影响</span><strong>{current.mainPlotImpact}</strong></div>{Object.entries(current.facts).map(([key, value]) => <div key={key}><span>{key}</span><strong>{value}</strong></div>)}</div>
        {Boolean(current.destinyOutline?.trim()) && <section className="character-outline-detail"><h3>人物大纲</h3><p>{current.destinyOutline}</p></section>}
        <section><h3>核心人设</h3>{current.corePersona?.length ? <dl className="persona-read-list is-core">{current.corePersona.map((item) => <div key={item.key}><dd>{personaText(item)}</dd></div>)}</dl> : <p className="empty-copy">还没有核心人设</p>}</section>
        {Boolean(current.supplementPersona?.length) && <section><h3>补充人设</h3><dl className="persona-read-list">{current.supplementPersona?.map((item) => <div key={item.key}><dd>{personaText(item)}</dd></div>)}</dl></section>}
        <section><h3>所属组织</h3>{organizations.length ? <div className="character-organizations">{organizations.map((organization) => { const membership = (organization.members || []).find((member) => member.characterId === current.entityId); return <button key={organization.entityId} onClick={() => { useUiStore.getState().selectEntry(organization.entityId); useUiStore.getState().navigate("entries"); }}><span style={{ background: organization.accent }} /><strong>{organization.name}</strong><small>{membership?.role || membership?.status || organization.subtype}</small></button>; })}</div> : <p className="empty-copy">还没有加入组织；家庭、帮派和公司可在设定页统一维护</p>}</section>
        <section><h3>相关剧情</h3><CollapsibleList items={relatedStories} itemKey={(story) => `${story.kind}:${story.item.entityId}`} resetKey={current.entityId} label={`${current.name}的相关剧情`} className="related-cards character-related-plots" emptyText="还没有相关剧情或碎片" renderItem={(story) => story.kind === "plot" ? <button onClick={() => { openPlotFromCharacter(story.item.entityId, current.entityId); useUiStore.getState().navigate("story"); }}><span><strong>{story.item.title}</strong><CompleteBlockPreview source={compactStoryPreview(story.item.summary || story.item.bodyPreview || "还没有剧情摘要")} className="character-related-plot-preview content-card-preview" /></span><small>剧情 · 第 {story.item.sequence} 章</small></button> : <button onClick={() => { selectFragment(story.item.entityId); useUiStore.getState().navigate("fragments"); }}><span><strong>{story.item.title}</strong><CompleteBlockPreview source={compactStoryPreview(story.item.bodyPreview || "还没有碎片正文")} className="character-related-plot-preview content-card-preview" /></span><small>{story.item.parentFragmentId ? `剧情线碎片${story.item.chapterNumber ? ` · 第 ${story.item.chapterNumber} 章` : ""}` : "灵感碎片"}</small></button>} /></section>
        <section>
          <div className="section-heading"><h3>人物印象</h3>{writable && <button className="icon-button" aria-label={`记录${current.name}对其他人物的印象`} title="记录人物印象" onClick={() => setRelationshipEditor({ id: "new", mode: "impression" })}><Icon name="plus" /></button>}</div>
          <CollapsibleList
            items={impressions}
            itemKey={(relation) => relation.entityId}
            resetKey={current.entityId}
            label={`${current.name}的人物印象`}
            className="relationship-list-new impression-list-new"
            emptyText="还没有记录对其他人物的印象"
            renderItem={(relation) => {
              const otherId = relation.from === current.entityId ? relation.to : relation.from;
              const other = snapshot.characters.find((item) => item.entityId === otherId);
              return <article><button className="relationship-target impression-target" onClick={() => other && select(other.entityId)}><strong>{other?.name || "已删除人物"}</strong><small>对其看法</small><p>{relationshipImpressionFor(relation, current.entityId)}</p></button>{writable && <button className="icon-button" aria-label={`编辑对${other?.name || "对方"}的印象`} title="编辑人物印象" onClick={() => setRelationshipEditor({ id: relation.entityId, mode: "impression" })}><Icon name="edit" /></button>}</article>;
            }}
          />
        </section>
        <section>
          <div className="section-heading"><h3>人物关系</h3>{writable && <button className="icon-button" aria-label={`为${current.name}建立人物关系`} title="建立人物关系" onClick={() => setRelationshipEditor({ id: "new", mode: "relationship" })}><Icon name="plus" /></button>}</div>
          <CollapsibleList
            items={relationships}
            itemKey={(relation) => relation.entityId}
            resetKey={current.entityId}
            label={`${current.name}的人物关系`}
            className="relationship-list-new"
            emptyText="还没有记录人物关系"
            renderItem={(relation) => {
              const otherId = relation.from === current.entityId ? relation.to : relation.from;
              const other = snapshot.characters.find((item) => item.entityId === otherId);
              return <article>
                <button className="relationship-target" onClick={() => other && select(other.entityId)}>
                  <span style={{ background: relation.color }} />
                  <strong>{other?.name || "已删除人物"}</strong>
                  <small>{relation.label || relation.type || "未命名关系"}</small>
                </button>
                {writable && <button className="icon-button" aria-label={`编辑${relation.label || "人物关系"}`} title="编辑人物关系" onClick={() => setRelationshipEditor({ id: relation.entityId, mode: "relationship" })}><Icon name="edit" /></button>}
              </article>;
            }}
          />
        </section>
      </> : <div className="empty-state"><Icon name="person" /><h2>选择一个人物</h2></div>}</article>
    </div>
    {editor && <CharacterEditor entityId={editor} onClose={() => setEditor(null)} />}
    {relationshipEditor && current && <RelationshipEditor relationshipId={relationshipEditor.id} mode={relationshipEditor.mode} defaultCharacterId={current.entityId} onClose={() => setRelationshipEditor(null)} />}
  </section>;
}
