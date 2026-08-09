import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import type { Entry, EntryMember } from "../api/types";
import { useProjectMutation, useRuntime } from "../api/runtime";
import type { PickedReference } from "../editor/MarkdownEditor";
import { DeferredMarkdownEditor as MarkdownEditor } from "../editor/DeferredMarkdownEditor";
import { browserDraftKey, clearBrowserDraft, restoreBrowserDraft, useBrowserDraft } from "../editor/browserDraft";
import { useEditorSaveShortcut } from "../editor/useEditorSaveShortcut";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { CollapsibleList } from "../components/CollapsibleList";
import { EditorSettingsSection } from "../components/EditorSettingsSection";
import { FilterChips } from "../components/FilterChips";
import { Icon } from "../components/Icon";
import { RenderedMarkdown } from "../components/RenderedMarkdown";
import { useUiStore } from "../state/ui";
import { randomContentColor } from "../theme/contentColors";

interface EntryDraft {
  stableId: string;
  name: string;
  type: string;
  subtype: string;
  area: string;
  body: string;
  status: string;
  accent: string;
  aliases: string[];
  tags: string[];
  people: string[];
  members: EntryMember[];
  references: string[];
}

function blankEntry(initialType = "地点"): EntryDraft {
  return { stableId: "", name: "", type: initialType, subtype: initialType === "组织" ? "组织" : "", area: "", body: "", status: initialType === "组织" ? "活跃" : "", accent: randomContentColor(), aliases: [], tags: [], people: [], members: [], references: [] };
}

export function EntryEditor({ entityId, initialType = "地点", onClose }: { entityId: string | "new"; initialType?: string; onClose: () => void }) {
  const { api, project, snapshot } = useRuntime();
  const mutation = useProjectMutation();
  const [currentId, setCurrentId] = useState<string | "new">(entityId);
  const detail = useQuery({ queryKey: ["entity", project, currentId], queryFn: () => api.detail<Entry>(currentId), enabled: currentId !== "new" });
  const [draft, setDraft] = useState<EntryDraft>(() => blankEntry(initialType));
  const [baseline, setBaseline] = useState("");
  const [message, setMessage] = useState("");
  const [confirmClose, setConfirmClose] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmRename, setConfirmRename] = useState(false);
  const draftKey = browserDraftKey(project, "entry", currentId);
  useEffect(() => {
    const item = detail.data?.data;
    const next = currentId === "new" ? blankEntry(initialType) : item ? {
      stableId: item.id, name: item.name, type: item.type, subtype: item.subtype, area: item.area,
      body: item.body || "", status: item.status, accent: item.accent, aliases: [...item.aliases],
      tags: [...item.tags], people: [...item.people], members: (item.members || item.people.map((characterId) => ({ characterId, role: "", status: "现成员" }))).map((member) => ({ ...member })),
      references: [...new Set([...(item.references || []), ...item.people])],
    } : null;
    if (next) {
      setDraft(restoreBrowserDraft(browserDraftKey(project, "entry", currentId), next));
      setBaseline(JSON.stringify(next));
    }
  }, [currentId, detail.data, initialType, project]);
  useBrowserDraft(draftKey, draft, baseline);
  const dirty = Boolean(baseline && JSON.stringify(draft) !== baseline);
  const change = <K extends keyof EntryDraft>(key: K, value: EntryDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const addReference = (reference: PickedReference) => setDraft((current) => ({
    ...current,
    people: reference.kind === "character" && !current.people.includes(reference.entityId)
      ? [...current.people, reference.entityId]
      : current.people,
    references: current.references.includes(reference.entityId)
      ? current.references
      : [...current.references, reference.entityId],
  }));
  const toggleMember = (characterId: string) => setDraft((current) => {
    const exists = current.members.some((member) => member.characterId === characterId);
    const members = exists
      ? current.members.filter((member) => member.characterId !== characterId)
      : [...current.members, { characterId, role: "", status: "现成员" }];
    return {
      ...current,
      members,
      people: members.map((member) => member.characterId),
      references: exists
        ? current.references.filter((value) => value !== characterId)
        : current.references.includes(characterId) ? current.references : [...current.references, characterId],
    };
  });
  const updateMember = (characterId: string, patch: Partial<EntryMember>) => setDraft((current) => ({
    ...current,
    members: current.members.map((member) => member.characterId === characterId ? { ...member, ...patch } : member),
  }));
  const referenceSourceCount = currentId === "new" ? 0 : new Set([
    ...snapshot.characters.filter((item) => item.references?.includes(currentId)).map((item) => item.entityId),
    ...snapshot.plots.filter((item) => item.references?.includes(currentId) || item.entries.includes(currentId)).map((item) => item.entityId),
    ...snapshot.entries.filter((item) => item.references?.includes(currentId)).map((item) => item.entityId),
    ...snapshot.fragments.filter((item) => item.references?.includes(currentId)).map((item) => item.entityId),
    ...snapshot.relationships.filter((item) => item.references?.includes(currentId)).map((item) => item.entityId),
  ]).size;
  const persist = async () => {
    try {
      const payload = { ...draft } as unknown as Record<string, unknown>;
      if (draft.type !== "组织") delete payload.members;
      if (currentId !== "new") delete payload.stableId;
      const result = await mutation.mutateAsync({ path: currentId === "new" ? "/entries" : `/entries/${encodeURIComponent(currentId)}`, method: currentId === "new" ? "POST" : "PATCH", payload });
      clearBrowserDraft(draftKey);
      if (currentId === "new") {
        const created = result.changed.entries?.find((item) => !snapshot.entries.some((existing) => existing.entityId === item.entityId));
        if (created?.entityId) setCurrentId(String(created.entityId));
      }
      setBaseline(JSON.stringify(draft)); setMessage(result.warnings[0] || "已保存");
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存失败"); }
  };
  const save = async () => {
    const previous = baseline ? (JSON.parse(baseline) as EntryDraft).name : draft.name;
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
    }
    catch (error) { setMessage(error instanceof Error ? error.message : "删除失败"); }
  };
  useEditorSaveShortcut(save);
  const discard = () => {
    clearBrowserDraft(draftKey);
    onClose();
  };
  if (entityId !== "new" && detail.isPending) return <div className="dialog-backdrop"><div className="editor-dialog loading-dialog">正在读取设定…</div></div>;
  return <div className="dialog-backdrop editor-backdrop"><section className={`editor-dialog${draft.type === "组织" ? " organization-editor-dialog" : ""}`} role="dialog" aria-modal="true" aria-label={draft.type === "组织" ? "编辑组织" : "编辑设定"}>
    <header className="dialog-header"><div><small>World Building</small><h2>{currentId === "new" ? "新建设定" : `编辑 · ${draft.name}`}</h2></div><div className="dialog-actions">{currentId !== "new" && <button className="icon-button is-danger" aria-label="删除设定" title="删除设定" onClick={() => setConfirmDelete(true)}><Icon name="trash" /></button>}<button className="icon-button" aria-label="关闭" title="关闭" onClick={() => dirty ? setConfirmClose(true) : onClose()}><Icon name="close" /></button></div></header>
    <EditorSettingsSection label="设定档案设置">
        <label className="wide"><span>名称</span><input value={draft.name} onChange={(event) => change("name", event.target.value)} /></label>
        <label><span>类型</span><input value={draft.type} onChange={(event) => change("type", event.target.value)} /></label>
        <label><span>子类型</span><input value={draft.subtype} onChange={(event) => change("subtype", event.target.value)} /></label>
        <label><span>区域</span><input value={draft.area} onChange={(event) => change("area", event.target.value)} /></label>
        <label><span>颜色</span><input type="color" value={draft.accent} onChange={(event) => change("accent", event.target.value)} /></label>
        <label className="wide"><span>别名</span><input value={draft.aliases.join("，")} onChange={(event) => change("aliases", event.target.value.split(/[，,]/).map((value) => value.trim()).filter(Boolean))} /></label>
        <label className="wide"><span>标签</span><input value={draft.tags.join("，")} onChange={(event) => change("tags", event.target.value.split(/[，,]/).map((value) => value.trim()).filter(Boolean))} /></label>
    </EditorSettingsSection>
    {draft.type === "组织" && <section className="organization-members-editor">
      <header><div><h3>组织成员</h3><p>成员身份属于组织，不会自动生成任意两个人之间的关系线。</p></div><strong>{draft.members.length} 人</strong></header>
      <div>{snapshot.characters.map((character) => {
        const member = draft.members.find((item) => item.characterId === character.entityId);
        return <article key={character.entityId} className={member ? "is-member" : ""}>
          <label className="organization-member-choice"><input type="checkbox" checked={Boolean(member)} onChange={() => toggleMember(character.entityId)} /><span>{character.name}</span></label>
          {member && <><input aria-label={`${character.name}的组织身份`} value={member.role} placeholder="身份或职位" onChange={(event) => updateMember(character.entityId, { role: event.target.value })} /><input aria-label={`${character.name}的成员状态`} value={member.status} placeholder="现成员、前成员、秘密成员…" onChange={(event) => updateMember(character.entityId, { status: event.target.value })} /></>}
        </article>;
      })}</div>
    </section>}
    <MarkdownEditor label={draft.type === "组织" ? "组织简介" : "设定正文"} value={draft.body} onChange={(value) => change("body", value)} onSave={save} characters={snapshot.characters} entries={snapshot.entries} sourceEntityId={currentId === "new" ? undefined : currentId} onReference={addReference} />
    <footer className="editor-footer"><span className={dirty ? "is-dirty" : ""}>{message || (dirty ? "未保存修改已暂存在浏览器" : "已保存")}</span><small>正文和结构化引用会在同一事务中保存</small></footer>
  </section><ConfirmDialog open={confirmClose} title="放弃未保存修改？" message="确认放弃后，浏览器中的这份设定草稿也会被删除。" confirmLabel="放弃修改" danger onCancel={() => setConfirmClose(false)} onConfirm={discard} /><ConfirmDialog open={confirmDelete} title={`删除“${draft.name}”？`} message="设定会进入统一回收站保留 7 天。" confirmLabel="移入回收站" danger onCancel={() => setConfirmDelete(false)} onConfirm={remove} /><ConfirmDialog open={confirmRename} title={`重命名为“${draft.name}”？`} message={`设定稳定 ID 不会改变；系统会在同一事务中更新 ${referenceSourceCount} 篇带稳定引用的相关正文，整次重命名可以撤销。`} confirmLabel="确认重命名" onCancel={() => setConfirmRename(false)} onConfirm={() => { setConfirmRename(false); void persist(); }} /></div>;
}

export default function EntriesPage() {
  const { snapshot, writable } = useRuntime();
  const selected = useUiStore((state) => state.selectedEntryId);
  const select = useUiStore((state) => state.selectEntry);
  const [editor, setEditor] = useState<{ entityId: string | "new"; initialType?: string } | null>(null);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const closeSearch = () => { setQuery(""); setSearchOpen(false); };
  const tags = useMemo(() => [...new Set(snapshot.entries.flatMap((item) => item.tags))].sort(), [snapshot.entries]);
  const [selectedTags, setSelectedTags] = useState<string[]>(tags);
  useEffect(() => setSelectedTags(tags), [tags.join("\0")]);
  const entries = snapshot.entries.filter((item) => (selectedTags.length === tags.length || item.tags.some((tag) => selectedTags.includes(tag))) && `${item.name} ${item.aliases.join(" ")} ${item.bodyPreview}`.toLowerCase().includes(query.toLowerCase()));
  useEffect(() => { if (!selected && entries[0]) select(entries[0].entityId); }, [entries, select, selected]);
  const current = snapshot.entries.find((item) => item.entityId === selected) || entries[0];
  const currentMembers = current?.members || [];
  const plots = current ? snapshot.plots.filter((plot) => plot.entries.includes(current.entityId)) : [];
  return <section className="workspace-page entries-page-new"><header className="page-header"><div className="entry-page-title"><small>World Archive</small><h1>设定档案</h1></div><div className="page-actions">{writable && <button className="icon-button" aria-label="新建组织" title="创建家庭、帮派或公司" onClick={() => setEditor({ entityId: "new", initialType: "组织" })}><Icon name="person-add" /></button>}</div></header>
    <div className="two-column-workspace"><aside className="sticky-rail entry-library"><div className="entry-library-tools"><div className={`entry-search-control${searchOpen ? " is-open" : ""}`}>{searchOpen && createPortal(<><button className="entry-search-scrim" type="button" aria-label="关闭设定搜索" onClick={closeSearch} /><section className="entry-search-dialog" role="dialog" aria-modal="true" aria-label="搜索设定"><header><strong>搜索设定</strong><button className="icon-button" type="button" aria-label="关闭设定搜索" onClick={closeSearch}><Icon name="close" /></button></header><label className="entry-search-field"><Icon name="search" /><input autoFocus aria-label="搜索设定" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") closeSearch(); }} placeholder="输入名称、别名或正文关键词" /></label></section></>, document.body)}<button className="icon-button" type="button" aria-label={searchOpen ? "关闭设定搜索" : "搜索设定"} title={searchOpen ? "关闭搜索" : "搜索设定"} aria-expanded={searchOpen} aria-haspopup="dialog" onClick={() => searchOpen ? closeSearch() : setSearchOpen(true)}><Icon name={searchOpen ? "close" : "search"} /></button></div>{writable && <button className="icon-button is-primary" aria-label="新建设定" title="新建设定" onClick={() => setEditor({ entityId: "new" })}><Icon name="plus" /></button>}</div><div className="entry-library-filter"><FilterChips label="标签" values={tags} selected={selectedTags} onChange={setSelectedTags} collapsible trigger="text" defaultExpanded={false} /></div>{entries.map((item) => <button key={item.entityId} className={current?.entityId === item.entityId ? "is-active" : ""} onClick={() => select(item.entityId)}><span className="entry-color" style={{ background: item.accent }} /><span><strong>{item.name}</strong><small>{item.type}{item.subtype ? ` · ${item.subtype}` : ""}</small></span></button>)}</aside><article className="sticky-detail entry-detail-panel">{current ? <><header><div><small>{current.type}</small><h2>{current.name}</h2><p>{current.area || current.subtype || "未填写区域"}</p></div>{writable && <button className="icon-button" aria-label="编辑设定" title="编辑设定" onClick={() => setEditor({ entityId: current.entityId })}><Icon name="edit" /></button>}</header>{current.type === "组织" && <section className="organization-member-summary"><h3>组织成员</h3>{currentMembers.length ? <div>{currentMembers.map((member) => { const character = snapshot.characters.find((item) => item.entityId === member.characterId); return <button key={member.characterId} onClick={() => { useUiStore.getState().selectCharacter(member.characterId); useUiStore.getState().navigate("characters"); }}><span style={{ background: character?.gradient || character?.color }}>{character?.name.slice(0, 1)}</span><strong>{character?.name || "已删除人物"}</strong><small>{member.role || member.status}</small></button>; })}</div> : <p className="empty-copy">还没有组织成员</p>}</section>}{current.tags.length > 0 && <div className="entry-index-strip" aria-label="设定关键词" style={{ "--entry-accent": current.accent } as React.CSSProperties}><div className="entry-index-caption"><small>Archive Index</small><strong>关键词</strong></div><ol>{current.tags.map((tag) => <li key={tag}><strong>{tag}</strong></li>)}</ol></div>}<section><h3>{current.type === "组织" ? "组织简介" : "正文预览"}</h3><RenderedMarkdown source={current.bodyPreview || "还没有正文"} className="entry-body-preview content-card-preview" /></section><section><h3>引用剧情</h3><CollapsibleList items={plots} itemKey={(plot) => plot.entityId} resetKey={current.entityId} label={`${current.name}引用的剧情`} className="related-cards" emptyText="还没有引用剧情" renderItem={(plot) => <button onClick={() => { useUiStore.getState().selectPlot(plot.entityId); useUiStore.getState().navigate("story"); }}><strong>{plot.title}</strong><small>第 {plot.sequence} 篇</small></button>} /></section></> : <div className="empty-state"><Icon name="book" /><h2>选择一项设定</h2></div>}</article></div>
    {editor && <EntryEditor entityId={editor.entityId} initialType={editor.initialType} onClose={() => setEditor(null)} />}
  </section>;
}
