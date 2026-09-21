import { useState } from "react";

const labels: Record<string, string> = {
  body: "正文", title: "标题", name: "名称", summary: "摘要", chapterNumber: "章号",
  tags: "标签", people: "人物", references: "关联内容", status: "状态", accent: "颜色",
  stories: "故事线", corePersona: "核心人设", supplementPersona: "补充人设",
  aliases: "别名", markers: "人物标记", destinyOutline: "命运大纲", narrativeRole: "人物定位",
  characterScope: "人物范围", mainPlotImpact: "主线影响", color: "颜色", group: "分组", graphVisible: "在图谱显示",
  appearanceNames: "新增出场人物", entries: "设定", storyPositionMode: "故事排序方式", storyAnchorPlotId: "相邻剧情",
  storySortKey: "故事顺序", key: "重点", climax: "高潮", stableId: "编号", type: "类型", subtype: "子类型", area: "区域",
  members: "组织成员", fragmentType: "碎片形态", parentFragmentId: "所属剧情线", fragmentOrder: "章节顺序",
  plotChapterPlan: "正式剧情章号规划", fromCharacterId: "起点人物", toCharacterId: "终点人物",
  fromRole: "起点称谓", toRole: "终点称谓", graphScope: "图谱显示范围", graphLineMode: "连线方式", label: "关系名称",
  facts: "人物档案", fromImpression: "对起点人物的印象", toImpression: "对终点人物的印象",
};
function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) return value.map(display).join("\n") || "—";
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    if ("key" in record && "value" in record) return `${record.key ? `${record.key}：` : ""}${record.value}`;
    return Object.entries(record).filter(([key]) => key !== "rowId")
      .map(([key, item]) => `${labels[key] || key}：${display(item)}`).join("\n");
  }
  return String(value);
}

export function BrowserDraftNotice<T>({ session, draft }: {
  session: { storageError: boolean; conflict: { latest: T; baseline: T | null } | null; acceptLatest: () => void };
  draft: T;
}) {
  const [expanded, setExpanded] = useState(false);
  const conflict = session.conflict;
  const keys = conflict ? Object.keys(draft as object).filter(key =>
    JSON.stringify((draft as Record<string, unknown>)[key]) !== JSON.stringify((conflict.latest as Record<string, unknown>)[key])) : [];
  return <>
    {session.storageError && <p className="draft-storage-warning" role="alert">浏览器草稿保存失败，当前编辑仍在页面中。请勿关闭页面，恢复服务后保存，或先复制正文备份。</p>}
    {conflict && <section className="draft-recovery" aria-label="草稿版本冲突">
      <p role="alert">这份草稿来自较早版本，或未记录版本。请对比最新内容，整理当前草稿后再确认；确认前不会覆盖已保存内容。</p>
      <button type="button" onClick={() => setExpanded(!expanded)}>{expanded ? "收起对比" : "对比草稿与最新内容"}</button>
      {expanded && <>
        <div className="draft-comparison">{keys.map(key => <div key={key}>
          <h4>{labels[key] || key}</h4>
          <div className="draft-comparison-columns">
            <div><strong>开始编辑时的内容</strong><pre>{conflict.baseline === null ? "旧版草稿未记录原始内容" : display((conflict.baseline as Record<string, unknown>)[key])}</pre></div>
            <div><strong>最新已保存内容</strong><pre>{display((conflict.latest as Record<string, unknown>)[key])}</pre></div>
            <div><strong>当前草稿</strong><pre>{display((draft as Record<string, unknown>)[key])}</pre></div>
          </div>
        </div>)}{!keys.length && <p>当前草稿与最新内容相同。</p>}</div>
        <button type="button" onClick={session.acceptLatest}>已对比，使用当前草稿继续编辑</button>
        <small>确认后仍需点击保存；若其他窗口再次修改，保存会再次检查版本。</small>
      </>}
    </section>}
  </>;
}
