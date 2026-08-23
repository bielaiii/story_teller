import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Fragment } from "../api/types";
import { useRuntime } from "../api/runtime";
import {
  defaultFragmentBoardPositions,
  fragmentBoardBounds,
  fragmentBoardEdges,
  fragmentBoardStorageKey,
  FRAGMENT_BOARD_DEFAULT_VIEWPORT,
  FRAGMENT_BOARD_NODE_HEIGHT,
  FRAGMENT_BOARD_NODE_WIDTH,
  parseFragmentBoardLayout,
  reconcileFragmentBoardPositions,
  serializeFragmentBoardLayout,
  type FragmentBoardPoint,
  type FragmentBoardViewport,
} from "../fragmentBoard";
import { copyArticleText, useMarkdownArticle } from "./MarkdownArticle";
import { ConfirmDialog } from "./ConfirmDialog";
import { Icon } from "./Icon";

function typeOf(item: Fragment): "chapter" | "line" {
  return item.fragmentType === "line" || item.extra?.fragmentType === "line" ? "line" : "chapter";
}

function parentOf(item: Fragment): string | null {
  const value = item.parentFragmentId ?? item.extra?.parentFragmentId;
  return typeof value === "string" && value ? value : null;
}

function chapterOf(item: Fragment): number | null {
  const value = item.chapterNumber ?? item.extra?.chapterNumber;
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
}

function displayTitle(item: Fragment): string {
  return parentOf(item)
    ? item.title.replace(/^第\s*\d+\s*章(?:\s*[：:·—-]\s*|\s+)/, "").trim() || item.title
    : item.title;
}

function orderedSiblings(items: Fragment[], item: Fragment): Fragment[] {
  const parent = parentOf(item);
  if (!parent) return [];
  return items.filter((candidate) => parentOf(candidate) === parent).sort((left, right) =>
    (chapterOf(left) ?? Number.MAX_SAFE_INTEGER) - (chapterOf(right) ?? Number.MAX_SAFE_INTEGER)
    || Number(left.fragmentOrder ?? left.extra?.fragmentOrder ?? 0) - Number(right.fragmentOrder ?? right.extra?.fragmentOrder ?? 0)
    || left.entityId.localeCompare(right.entityId, undefined, { numeric: true })
  );
}

function edgeClass(kinds: string[], focusOnly: boolean): string {
  return [
    "fragment-board-edge",
    focusOnly ? "is-focus" : "is-core",
    ...kinds.map((kind) => `has-${kind}`),
  ].join(" ");
}

function edgeCurve(
  from: FragmentBoardPoint,
  to: FragmentBoardPoint,
  edgeId: string,
  structure: boolean,
) {
  const radius = FRAGMENT_BOARD_NODE_WIDTH / 2;
  const fromCenter = { x: from.x + radius, y: from.y + radius };
  const toCenter = { x: to.x + radius, y: to.y + radius };
  const deltaX = toCenter.x - fromCenter.x;
  const deltaY = toCenter.y - fromCenter.y;
  const distance = Math.max(1, Math.hypot(deltaX, deltaY));
  const unitX = deltaX / distance;
  const unitY = deltaY / distance;
  const start = { x: fromCenter.x + unitX * radius, y: fromCenter.y + unitY * radius };
  const end = { x: toCenter.x - unitX * radius, y: toCenter.y - unitY * radius };
  const direction = [...edgeId].reduce((sum, character) => sum + character.charCodeAt(0), 0) % 2 ? 1 : -1;
  if (structure) {
    const bend = Math.min(40, Math.max(14, distance * .08)) * direction;
    const control = {
      x: (start.x + end.x) / 2 - unitY * bend,
      y: (start.y + end.y) / 2 + unitX * bend,
    };
    return {
      path: `M ${start.x} ${start.y} Q ${control.x} ${control.y} ${end.x} ${end.y}`,
      label: {
        x: start.x * .25 + control.x * .5 + end.x * .25,
        y: start.y * .25 + control.y * .5 + end.y * .25,
      },
    };
  }
  const bend = Math.min(66, Math.max(24, distance * .13)) * direction;
  const control = {
    x: (start.x + end.x) / 2 - unitY * bend,
    y: (start.y + end.y) / 2 + unitX * bend,
  };
  return {
    path: `M ${start.x} ${start.y} Q ${control.x} ${control.y} ${end.x} ${end.y}`,
    label: {
      x: start.x * .25 + control.x * .5 + end.x * .25,
      y: start.y * .25 + control.y * .5 + end.y * .25,
    },
  };
}

function readStoredLayout(storageKey: string, validIds: Set<string>) {
  try {
    return parseFragmentBoardLayout(window.localStorage?.getItem(storageKey) || null, validIds);
  } catch {
    return null;
  }
}

function FragmentBoardReader({
  item,
  fragments,
  relationLabels,
  onSelect,
  onClose,
  onEdit,
  onImmersive,
}: {
  item: Fragment;
  fragments: Fragment[];
  relationLabels: string[];
  onSelect: (id: string) => void;
  onClose: () => void;
  onEdit: (item: Fragment) => void;
  onImmersive: (id: string) => void;
}) {
  const { api, project, snapshot, writable } = useRuntime();
  const detail = useQuery({
    queryKey: ["entity", project, item.entityId],
    queryFn: () => api.detail<Fragment>(item.entityId),
    enabled: !snapshot.readonly,
  });
  const data = snapshot.readonly ? item : detail.data?.data;
  const body = data?.body || "";
  const { renderedHtml } = useMarkdownArticle(body, `fragment-board-heading-${item.entityId.replace(/\W/g, "-")}`);
  const proseRef = useRef<HTMLElement>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  const siblings = useMemo(() => orderedSiblings(fragments, item), [fragments, item]);
  const siblingIndex = siblings.findIndex((candidate) => candidate.entityId === item.entityId);
  const previous = siblingIndex > 0 ? siblings[siblingIndex - 1] : null;
  const next = siblingIndex >= 0 && siblingIndex < siblings.length - 1 ? siblings[siblingIndex + 1] : null;

  useEffect(() => {
    proseRef.current?.scrollTo({ top: 0 });
  }, [item.entityId]);
  useEffect(() => {
    if (copyState === "idle") return;
    const timer = window.setTimeout(() => setCopyState("idle"), 2400);
    return () => window.clearTimeout(timer);
  }, [copyState]);

  const copy = async () => {
    try {
      await copyArticleText(proseRef.current?.innerText?.trim() || body || "还没有正文。");
      setCopyState("copied");
    } catch {
      setCopyState("error");
    }
  };

  const parent = parentOf(item) ? fragments.find((candidate) => candidate.entityId === parentOf(item)) : null;
  const eyebrow = parent
    ? `${parent.title} · 第 ${chapterOf(item) ?? "?"} 章`
    : typeOf(item) === "line" ? "剧情线" : "灵感碎片";
  return <aside className="fragment-board-reader" aria-label={`阅读${displayTitle(item)}`} style={{ "--accent": item.accent } as React.CSSProperties}>
    <header>
      <div><small>{eyebrow}</small><h2>{displayTitle(item)}</h2></div>
      <div className="fragment-board-reader-actions">
        <span role="status" aria-live="polite">{copyState === "copied" ? "已复制" : copyState === "error" ? "复制失败" : ""}</span>
        <button className="icon-button" type="button" aria-label={copyState === "copied" ? "正文已复制" : "复制正文"} title="复制正文" onClick={() => void copy()}><Icon name={copyState === "copied" ? "check" : "clipboard"} /></button>
        <button className="icon-button" type="button" aria-label="沉浸阅读" title="沉浸阅读" onClick={() => onImmersive(item.entityId)}><Icon name="expand" /></button>
        {writable && <button className="icon-button" type="button" aria-label={`编辑${displayTitle(item)}`} title="编辑碎片" onClick={() => onEdit(item)}><Icon name="edit" /></button>}
        <button className="icon-button" type="button" aria-label="关闭画布阅读" title="关闭" onClick={onClose}><Icon name="close" /></button>
      </div>
    </header>
    <div className="fragment-board-reader-meta">
      {item.key && <span>关键剧情</span>}{item.climax && <span>高潮剧情</span>}
      {item.tags.map((tag) => <span key={tag}>{tag}</span>)}
    </div>
    {relationLabels.length > 0 && <div className="fragment-board-reader-relations" aria-label="当前自动关联">{relationLabels.map((label) => <span key={label}>{label}</span>)}</div>}
    {detail.isPending && !snapshot.readonly && <p className="fragment-board-reader-loading">正在读取完整正文…</p>}
    {detail.isError && <p className="fragment-board-reader-loading is-error">{detail.error instanceof Error ? detail.error.message : "读取碎片失败"}</p>}
    <section ref={proseRef} className="fragment-board-reader-prose prose" dangerouslySetInnerHTML={{ __html: renderedHtml }} />
    {siblings.length > 1 && <footer>
      <button type="button" disabled={!previous} onClick={() => previous && onSelect(previous.entityId)}><small>上一章</small><strong>{previous ? displayTitle(previous) : "没有上一章"}</strong></button>
      <button type="button" disabled={!next} onClick={() => next && onSelect(next.entityId)}><small>下一章</small><strong>{next ? displayTitle(next) : "没有下一章"}</strong></button>
    </footer>}
  </aside>;
}

export function FragmentBoard({
  fragments,
  selectedTags,
  allTags,
  onEdit,
  onImmersive,
}: {
  fragments: Fragment[];
  selectedTags: string[];
  allTags: string[];
  onEdit: (item: Fragment) => void;
  onImmersive: (id: string) => void;
}) {
  const { project, snapshot } = useRuntime();
  const stageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const panRef = useRef<{ pointerId: number; x: number; y: number; originX: number; originY: number; moved: boolean } | null>(null);
  const dragRef = useRef<{ id: string; pointerId: number; x: number; y: number; origin: FragmentBoardPoint; moved: boolean } | null>(null);
  const suppressClickRef = useRef<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [size, setSize] = useState({ width: 1000, height: 680 });
  const defaults = useMemo(() => defaultFragmentBoardPositions(fragments), [fragments]);
  const storageKey = useMemo(
    () => fragmentBoardStorageKey(window.location.pathname, project),
    [project],
  );
  const validIds = useMemo(() => new Set(fragments.map((item) => item.entityId)), [fragments]);
  const initialLayout = useMemo(
    () => readStoredLayout(storageKey, validIds),
    [storageKey, validIds],
  );
  const autoFitRef = useRef(initialLayout === null);
  const [positions, setPositions] = useState<Map<string, FragmentBoardPoint>>(() => {
    return reconcileFragmentBoardPositions(defaults, initialLayout, fragments);
  });
  const [viewport, setViewport] = useState<FragmentBoardViewport>(() =>
    initialLayout?.viewport
    || { ...FRAGMENT_BOARD_DEFAULT_VIEWPORT }
  );

  useEffect(() => {
    setPositions((current) => reconcileFragmentBoardPositions(defaults, {
      version: 5,
      nodes: Object.fromEntries(current),
      viewport: FRAGMENT_BOARD_DEFAULT_VIEWPORT,
    }, fragments));
  }, [defaults, fragments]);

  useEffect(() => {
    if (selectedId && !validIds.has(selectedId)) setSelectedId(null);
  }, [selectedId, validIds]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        window.localStorage?.setItem(storageKey, serializeFragmentBoardLayout(positions, viewport));
      } catch {
        // The board remains usable in memory when local storage is disabled or full.
      }
    }, 160);
    return () => window.clearTimeout(timer);
  }, [positions, storageKey, viewport]);

  useEffect(() => {
    const target = stageRef.current;
    if (!target) return;
    const observer = new ResizeObserver(([entry]) => setSize({
      width: Math.max(1, entry.contentRect.width),
      height: Math.max(1, entry.contentRect.height),
    }));
    observer.observe(target);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedId(null);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);

  const selected = selectedId ? fragments.find((item) => item.entityId === selectedId) || null : null;
  const edges = useMemo(
    () => fragmentBoardEdges(fragments, snapshot.characters, selectedId),
    [fragments, selectedId, snapshot.characters],
  );
  const relatedIds = useMemo(() => {
    const result = new Set<string>();
    if (selectedId) result.add(selectedId);
    for (const edge of edges) {
      if (edge.fromId === selectedId) result.add(edge.toId);
      if (edge.toId === selectedId) result.add(edge.fromId);
    }
    return result;
  }, [edges, selectedId]);
  const selectedRelationLabels = useMemo(() => [...new Set(edges
    .filter((edge) => edge.fromId === selectedId || edge.toId === selectedId)
    .flatMap((edge) => edge.labels))], [edges, selectedId]);
  const tagFilterActive = selectedTags.length < allTags.length;
  const bounds = useMemo(() => fragmentBoardBounds(positions), [positions]);
  const worldWidth = Math.max(2200, bounds.maxX + 520);
  const worldHeight = Math.max(1400, bounds.maxY + 420);
  const visibleIds = useMemo(() => {
    const margin = 360;
    const left = -viewport.x / viewport.scale - margin;
    const top = -viewport.y / viewport.scale - margin;
    const right = left + size.width / viewport.scale + margin * 2;
    const bottom = top + size.height / viewport.scale + margin * 2;
    return new Set([...positions].filter(([, point]) =>
      point.x + FRAGMENT_BOARD_NODE_WIDTH >= left && point.x <= right
      && point.y + FRAGMENT_BOARD_NODE_HEIGHT >= top && point.y <= bottom
    ).map(([id]) => id));
  }, [positions, size, viewport]);

  const commitViewport = (next: FragmentBoardViewport) => setViewport({
    x: next.x,
    y: next.y,
    scale: Math.max(.18, Math.min(2.5, next.scale)),
  });
  const zoom = (factor: number) => {
    const nextScale = Math.max(.18, Math.min(2.5, viewport.scale * factor));
    const centerX = size.width / 2;
    const centerY = size.height / 2;
    const worldX = (centerX - viewport.x) / viewport.scale;
    const worldY = (centerY - viewport.y) / viewport.scale;
    commitViewport({ scale: nextScale, x: centerX - worldX * nextScale, y: centerY - worldY * nextScale });
  };
  const fitPositions = (targetPositions: Map<string, FragmentBoardPoint>) => {
    const targetBounds = fragmentBoardBounds(targetPositions);
    const rect = stageRef.current?.getBoundingClientRect();
    const stageWidth = rect?.width || size.width;
    const stageHeight = rect?.height || size.height;
    const width = Math.max(1, targetBounds.maxX - targetBounds.minX);
    const height = Math.max(1, targetBounds.maxY - targetBounds.minY);
    const scale = Math.max(.18, Math.min(1.15, Math.min((stageWidth - 100) / width, (stageHeight - 100) / height)));
    commitViewport({
      scale,
      x: (stageWidth - width * scale) / 2 - targetBounds.minX * scale,
      y: (stageHeight - height * scale) / 2 - targetBounds.minY * scale,
    });
  };
  const fit = () => fitPositions(positions);

  useEffect(() => {
    if (!autoFitRef.current) return;
    autoFitRef.current = false;
    fitPositions(positions);
  }, [positions]);

  const resetLayout = () => {
    try { window.localStorage?.removeItem(storageKey); } catch { /* keep the in-memory reset */ }
    setPositions(new Map(defaults));
    window.requestAnimationFrame(() => fitPositions(defaults));
    setSelectedId(null);
    setConfirmReset(false);
  };

  const onWheel: React.WheelEventHandler<HTMLDivElement> = (event) => {
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const pointerX = event.clientX - rect.left;
    const pointerY = event.clientY - rect.top;
    const scale = Math.max(.18, Math.min(2.5, viewport.scale * (event.deltaY > 0 ? .9 : 1.1)));
    const worldX = (pointerX - viewport.x) / viewport.scale;
    const worldY = (pointerY - viewport.y) / viewport.scale;
    commitViewport({ scale, x: pointerX - worldX * scale, y: pointerY - worldY * scale });
  };
  const beginPan: React.PointerEventHandler<HTMLDivElement> = (event) => {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    panRef.current = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      originX: viewport.x,
      originY: viewport.y,
      moved: false,
    };
  };
  const movePan: React.PointerEventHandler<HTMLDivElement> = (event) => {
    const pan = panRef.current;
    if (!pan || pan.pointerId !== event.pointerId) return;
    if (Math.hypot(event.clientX - pan.x, event.clientY - pan.y) > 4) pan.moved = true;
    setViewport((current) => ({ ...current, x: pan.originX + event.clientX - pan.x, y: pan.originY + event.clientY - pan.y }));
  };
  const finishPan: React.PointerEventHandler<HTMLDivElement> = (event) => {
    if (panRef.current?.pointerId !== event.pointerId) return;
    panRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const beginNodeDrag = (event: React.PointerEvent<HTMLButtonElement>, item: Fragment) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    const origin = positions.get(item.entityId);
    if (!origin) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { id: item.entityId, pointerId: event.pointerId, x: event.clientX, y: event.clientY, origin, moved: false };
  };
  const moveNode = (event: React.PointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (Math.hypot(event.clientX - drag.x, event.clientY - drag.y) > 4) drag.moved = true;
    if (!drag.moved) return;
    const next = {
      x: Math.max(20, Math.min(30_000, drag.origin.x + (event.clientX - drag.x) / viewport.scale)),
      y: Math.max(20, Math.min(30_000, drag.origin.y + (event.clientY - drag.y) / viewport.scale)),
    };
    setPositions((current) => new Map(current).set(drag.id, next));
  };
  const finishNode = (event: React.PointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (drag.moved) suppressClickRef.current = drag.id;
  };

  return <section className={`fragment-board-shell${selected ? " has-reader" : ""}`}>
    <div className="fragment-board-stage" ref={stageRef}>
      <header className="fragment-board-toolbar">
        <div className="fragment-board-legend" aria-label="画布关系图例"><span className="is-structure">剧情线</span><span className="is-reference">明确引用</span><span className="is-focus">人物 / 标签（聚焦时）</span></div>
        <strong>{fragments.length} 个碎片</strong>
        <div>
          <button type="button" aria-label="缩小画布" title="缩小" onClick={() => zoom(.86)}>−</button>
          <span>{Math.round(viewport.scale * 100)}%</span>
          <button type="button" aria-label="放大画布" title="放大" onClick={() => zoom(1.16)}>＋</button>
          <button type="button" aria-label="适应全部碎片" title="适应全部" onClick={fit}><Icon name="expand" /></button>
          <button type="button" aria-label="重新整理画布" title="清除本地位置并重新整理" onClick={() => setConfirmReset(true)}><Icon name="restore" /></button>
        </div>
      </header>
      <div
        ref={canvasRef}
        className={`fragment-board-canvas${panRef.current?.moved ? " is-panning" : ""}`}
        role="application"
        aria-label="灵感画布，可拖动碎片节点或平移画布"
        tabIndex={0}
        onWheel={onWheel}
        onPointerDown={beginPan}
        onPointerMove={movePan}
        onPointerUp={finishPan}
        onPointerCancel={finishPan}
        onClick={(event) => {
          if (!(event.target as Element).closest(".fragment-board-node")) setSelectedId(null);
        }}
      >
        <div className="fragment-board-world" style={{ width: worldWidth, height: worldHeight, transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.scale})` }}>
          <svg className="fragment-board-edges" width={worldWidth} height={worldHeight} aria-hidden="true">
            <defs>
              <marker id="fragment-board-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8 Z" /></marker>
            </defs>
            {edges.map((edge) => {
              const from = positions.get(edge.fromId);
              const to = positions.get(edge.toId);
              if (!from || !to) return null;
              const curve = edgeCurve(from, to, edge.id, edge.kinds.includes("structure"));
              const label = edge.labels.join(" · ");
              const labelWidth = Math.min(220, Math.max(54, label.length * 11 + 16));
              const selectedEdge = edge.fromId === selectedId || edge.toId === selectedId;
              return <g key={edge.id} className={`${edgeClass(edge.kinds, edge.focusOnly)}${selectedEdge ? " is-selected-edge" : ""}`} data-edge-id={edge.id}>
                <path d={curve.path} markerStart={edge.arrows.includes("reverse") ? "url(#fragment-board-arrow)" : undefined} markerEnd={edge.arrows.includes("forward") ? "url(#fragment-board-arrow)" : undefined} />
                <g className="fragment-board-edge-label" transform={`translate(${curve.label.x}, ${curve.label.y})`}>
                  <rect x={-labelWidth / 2} y={-10} width={labelWidth} height={20} rx={10} />
                  <text textAnchor="middle" dominantBaseline="central">{label.length > 20 ? `${label.slice(0, 19)}…` : label}</text>
                </g>
              </g>;
            })}
          </svg>
          {fragments.filter((item) => visibleIds.has(item.entityId)).map((item) => {
            const point = positions.get(item.entityId);
            if (!point) return null;
            const isSelected = selectedId === item.entityId;
            const unrelated = Boolean(selectedId && !relatedIds.has(item.entityId));
            const tagDimmed = tagFilterActive && !item.tags.some((tag) => selectedTags.includes(tag));
            return <button
              key={item.entityId}
              data-entity-id={item.entityId}
              type="button"
              className={`fragment-board-node${typeOf(item) === "line" ? " is-line" : ""}${isSelected ? " is-selected" : ""}${unrelated ? " is-unrelated" : ""}${tagDimmed ? " is-tag-dimmed" : ""}`}
              style={{ left: point.x, top: point.y, "--accent": item.accent } as React.CSSProperties}
              aria-label={`阅读${displayTitle(item)}`}
              aria-pressed={isSelected}
              onPointerDown={(event) => beginNodeDrag(event, item)}
              onPointerMove={moveNode}
              onPointerUp={finishNode}
              onPointerCancel={finishNode}
              onClick={() => {
                if (suppressClickRef.current === item.entityId) {
                  suppressClickRef.current = null;
                  return;
                }
                setSelectedId(item.entityId);
              }}
            >
              <span className="fragment-board-node-kind">{typeOf(item) === "line" ? "STORY LINE" : parentOf(item) ? `第 ${chapterOf(item) ?? "?"} 章` : "IDEA"}</span>
              <strong>{displayTitle(item)}</strong>
              <small>{item.bodyPreview || (typeOf(item) === "line" ? "打开剧情线" : "还没有正文")}</small>
              <span className="fragment-board-node-tags">{item.tags.slice(0, 2).map((tag) => <i key={tag}>{tag}</i>)}{item.tags.length > 2 && <i>+{item.tags.length - 2}</i>}</span>
            </button>;
          })}
        </div>
      </div>
    </div>
    {selected && <FragmentBoardReader
      item={selected}
      fragments={fragments}
      relationLabels={selectedRelationLabels}
      onSelect={setSelectedId}
      onClose={() => setSelectedId(null)}
      onEdit={onEdit}
      onImmersive={onImmersive}
    />}
    <ConfirmDialog open={confirmReset} title="重新整理灵感画布？" message="只会清除当前浏览器保存的节点位置和视角，不会修改任何碎片内容。" confirmLabel="重新整理" onCancel={() => setConfirmReset(false)} onConfirm={resetLayout} />
  </section>;
}
