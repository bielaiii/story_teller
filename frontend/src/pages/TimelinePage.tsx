import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Plot, TimelineLine, TimelineNode } from "../api/types";
import { useProjectMutation, useRuntime } from "../api/runtime";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Icon } from "../components/Icon";
import { RenderedMarkdown } from "../components/RenderedMarkdown";
import { useUiStore } from "../state/ui";

interface LineDraft {
  entityId: string;
  stableId: string;
  persisted: boolean;
  name: string;
  color: string;
  side: "center" | "left" | "right";
  startPlotId: string | null;
  endPlotId: string | null;
}

interface AssignmentDraft {
  plotId: string;
  lineIds: string[];
  storySortKey: string;
}

interface TimelineTrackGeometry {
  id: string;
  name: string;
  color: string;
  x: number;
  startY: number;
  endY: number;
  startSourceX: number;
  endTargetX: number;
  startSourceColor: string;
  endTargetColor: string;
  isMain: boolean;
}

interface TimelineGeometry {
  height: number;
  plotY: Map<string, number>;
  tracks: TimelineTrackGeometry[];
}

export function visibleTimelineTrackIds(geometry: TimelineGeometry, top: number, bottom: number): Set<string> {
  return new Set(geometry.tracks.filter((track) => {
    const start = track.isMain ? track.startY : track.startY - timelineTurnHeight(track.startSourceX, track.x);
    const end = track.isMain ? track.endY : track.endY + timelineTurnHeight(track.x, track.endTargetX);
    return end >= top - 24 && start <= bottom + 24;
  }).map((track) => track.id));
}

const TIMELINE_TOP = 158;
const TIMELINE_STEP = 116;

function timelineCornerRadius(sourceX: number, targetX: number): number {
  return Math.min(28, Math.max(14, Math.abs(targetX - sourceX) * .28));
}

function timelineTurnHeight(sourceX: number, targetX: number): number {
  return timelineCornerRadius(sourceX, targetX) * 2.45;
}

export function buildTimelineGeometry(
  width: number,
  plotIds: string[],
  lines: TimelineLine[],
  nodes: TimelineNode[],
  mainLineId: string,
): TimelineGeometry {
  const height = Math.max(640, plotIds.length * TIMELINE_STEP + 160);
  const plotY = new Map(plotIds.map((id, index) => [id, TIMELINE_TOP + index * TIMELINE_STEP]));
  const mainLine = lines.find((line) => line.entityId === mainLineId) || lines[0];
  const mainX = width / 2;
  const leftLines = lines.filter((line) => line.entityId !== mainLine?.entityId && line.side === "left");
  const rightLines = lines.filter((line) => line.entityId !== mainLine?.entityId && line.side !== "left");
  const xByLine = new Map<string, number>();
  if (mainLine) xByLine.set(mainLine.entityId, mainX);
  leftLines.forEach((line, index) => xByLine.set(line.entityId, mainX - (index + 1) * 82));
  rightLines.forEach((line, index) => xByLine.set(line.entityId, mainX + (index + 1) * 82));
  const lineById = new Map(lines.map((line) => [line.entityId, line]));
  const memberships = new Map<string, string[]>();
  nodes.forEach((node) => memberships.set(node.plotId, [...(memberships.get(node.plotId) || []), node.lineId]));
  const linePlotIds = (lineId: string) => nodes
    .filter((node) => node.lineId === lineId && plotY.has(node.plotId))
    .sort((left, right) => (plotY.get(left.plotId) || 0) - (plotY.get(right.plotId) || 0))
    .map((node) => node.plotId);
  const connectedLine = (plotId: string | undefined, ownLineId: string) => {
    const candidates = (plotId ? memberships.get(plotId) : [])?.filter((id) => id !== ownLineId) || [];
    return candidates.includes(mainLine?.entityId || "") ? mainLine?.entityId : candidates[0] || mainLine?.entityId || ownLineId;
  };

  const tracks = lines.map((line): TimelineTrackGeometry => {
    const isMain = line.entityId === mainLine?.entityId;
    const ownedPlots = linePlotIds(line.entityId);
    const startPlotId = line.startPlotId && plotY.has(line.startPlotId) ? line.startPlotId : ownedPlots[0];
    const endPlotId = line.endPlotId && plotY.has(line.endPlotId) ? line.endPlotId : ownedPlots.at(-1);
    const startY = isMain ? 92 : plotY.get(startPlotId || "") || TIMELINE_TOP;
    const endY = isMain ? height - 34 : Math.max(startY, plotY.get(endPlotId || "") || startY);
    const startSourceId = connectedLine(startPlotId, line.entityId);
    const endTargetId = connectedLine(endPlotId, line.entityId);
    return {
      id: line.entityId,
      name: line.name,
      color: line.color,
      x: xByLine.get(line.entityId) || mainX,
      startY,
      endY,
      startSourceX: xByLine.get(startSourceId) || mainX,
      endTargetX: xByLine.get(endTargetId) || mainX,
      startSourceColor: lineById.get(startSourceId)?.color || line.color,
      endTargetColor: lineById.get(endTargetId)?.color || line.color,
      isMain,
    };
  });
  return { height, plotY, tracks };
}

function TimelineTrackCanvas({ geometry, focus }: { geometry: TimelineGeometry; focus: string | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = canvas?.parentElement;
    if (!canvas || !container) return;
    let frame = 0;
    const draw = () => {
      frame = 0;
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
      const width = container.clientWidth;
      const scrollViewport = container.closest(".timeline-editor-visual-scroll") as HTMLElement | null;
      const height = Math.min(scrollViewport?.clientHeight || window.innerHeight, geometry.height);
      if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
        canvas.width = Math.round(width * ratio);
        canvas.height = Math.round(height * ratio);
      }
      canvas.style.height = `${height}px`;
      const context = canvas.getContext("2d");
      if (!context) return;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      const canvasBounds = canvas.getBoundingClientRect();
      const containerBounds = container.getBoundingClientRect();
      const offsetY = canvasBounds.top - containerBounds.top;
      const localY = (worldY: number) => worldY - offsetY;
      const visible = (from: number, to: number) => to >= offsetY - 80 && from <= offsetY + height + 80;

      for (const track of geometry.tracks) {
        const startTurnHeight = timelineTurnHeight(track.startSourceX, track.x);
        const endTurnHeight = timelineTurnHeight(track.x, track.endTargetX);
        if (!visible(track.isMain ? track.startY : track.startY - startTurnHeight, track.isMain ? track.endY : track.endY + endTurnHeight)) continue;
        const muted = Boolean(focus && focus !== track.id);
        context.globalAlpha = muted ? .09 : track.isMain ? .92 : .76;
        context.lineWidth = focus === track.id ? 6 : track.isMain ? 5 : 4;
        context.lineCap = "round";
        context.lineJoin = "round";
        if (track.isMain) {
          context.beginPath();
          context.moveTo(track.x, localY(track.startY));
          context.lineTo(track.x, localY(track.endY));
          context.strokeStyle = track.color;
          context.stroke();
          continue;
        }

        const startGradient = context.createLinearGradient(track.startSourceX, 0, track.x, 0);
        startGradient.addColorStop(0, track.startSourceColor);
        startGradient.addColorStop(1, track.color);
        const startRadius = timelineCornerRadius(track.startSourceX, track.x);
        const startSourceY = track.startY - startTurnHeight;
        const startRailY = track.startY - startRadius;
        const startDirection = Math.sign(track.x - track.startSourceX) || 1;
        context.beginPath();
        context.moveTo(track.startSourceX, localY(startSourceY));
        context.quadraticCurveTo(
          track.startSourceX,
          localY(startRailY),
          track.startSourceX + startDirection * startRadius,
          localY(startRailY),
        );
        context.lineTo(track.x - startDirection * startRadius, localY(startRailY));
        context.quadraticCurveTo(track.x, localY(startRailY), track.x, localY(track.startY));
        context.strokeStyle = startGradient;
        context.stroke();

        context.beginPath();
        context.moveTo(track.x, localY(track.startY));
        context.lineTo(track.x, localY(track.endY));
        context.strokeStyle = track.color;
        context.stroke();

        const endGradient = context.createLinearGradient(track.x, 0, track.endTargetX, 0);
        endGradient.addColorStop(0, track.color);
        endGradient.addColorStop(1, track.endTargetColor);
        const endRadius = timelineCornerRadius(track.x, track.endTargetX);
        const endRailY = track.endY + endRadius;
        const endTargetY = track.endY + endTurnHeight;
        const endDirection = Math.sign(track.endTargetX - track.x) || 1;
        context.beginPath();
        context.moveTo(track.x, localY(track.endY));
        context.quadraticCurveTo(
          track.x,
          localY(endRailY),
          track.x + endDirection * endRadius,
          localY(endRailY),
        );
        context.lineTo(track.endTargetX - endDirection * endRadius, localY(endRailY));
        context.quadraticCurveTo(track.endTargetX, localY(endRailY), track.endTargetX, localY(endTargetY));
        context.strokeStyle = endGradient;
        context.stroke();
      }
      context.globalAlpha = 1;
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(draw); };
    const observer = new ResizeObserver(schedule);
    observer.observe(container);
    window.addEventListener("scroll", schedule, { passive: true, capture: true });
    window.addEventListener("resize", schedule);
    draw();
    return () => {
      if (frame) cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("scroll", schedule, true);
      window.removeEventListener("resize", schedule);
    };
  }, [focus, geometry]);

  return <canvas ref={canvasRef} className="timeline-track-canvas" aria-hidden="true" />;
}

function rank(index: number): string {
  return String(index * 10 ** 12).padStart(24, "0");
}

function generatedLineId(): string {
  const suffix = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID().replaceAll("-", "").slice(0, 12)
    : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  return `line-${suffix}`;
}

export default function TimelinePage() {
  const { api, project, snapshot, writable } = useRuntime();
  const mutation = useProjectMutation();
  const canvasWrapRef = useRef<HTMLDivElement>(null);
  const editorTimelineScrollRef = useRef<HTMLDivElement>(null);
  const focus = useUiStore((state) => state.timelineFocusId);
  const setFocus = useUiStore((state) => state.setTimelineFocus);
  const [selectedPlot, setSelectedPlot] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [lines, setLines] = useState<LineDraft[]>([]);
  const [assignments, setAssignments] = useState<AssignmentDraft[]>([]);
  const [mainLineId, setMainLineId] = useState("");
  const [selectedEditLine, setSelectedEditLine] = useState("");
  const [selectedEditPlot, setSelectedEditPlot] = useState<string | null>(null);
  const [deleteLine, setDeleteLine] = useState<string | null>(null);
  const [replacement, setReplacement] = useState("");
  const [lineReplacements, setLineReplacements] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [visibleRange, setVisibleRange] = useState(() => ({ top: 0, bottom: window.innerHeight }));
  const [canvasWidth, setCanvasWidth] = useState(1000);
  const [editorCanvasWidth, setEditorCanvasWidth] = useState(720);

  const storyKeyByPlot = useMemo(() => {
    const result = new Map<string, string>();
    snapshot.timeline.nodes.forEach((node) => {
      const current = result.get(node.plotId);
      if (!current || node.storySortKey < current) result.set(node.plotId, node.storySortKey);
    });
    snapshot.plots.forEach((plot, index) => {
      if (!result.has(plot.entityId)) result.set(plot.entityId, rank(index + 1));
    });
    return result;
  }, [snapshot.plots, snapshot.timeline.nodes]);
  const globalStoryOrder = useMemo(() => new Map(
    [...snapshot.plots]
      .sort((left, right) => (storyKeyByPlot.get(left.entityId) || "").localeCompare(storyKeyByPlot.get(right.entityId) || ""))
      .map((item, index) => [item.entityId, index + 1]),
  ), [snapshot.plots, storyKeyByPlot]);
  const allOrderedPlots = useMemo(() => [...snapshot.plots]
    .sort((left, right) => (storyKeyByPlot.get(left.entityId) || "").localeCompare(storyKeyByPlot.get(right.entityId) || "")),
  [snapshot.plots, storyKeyByPlot]);
  const visiblePlots = useMemo(() => allOrderedPlots
    .filter((plot) => !focus || snapshot.timeline.nodes.some((node) => node.plotId === plot.entityId && node.lineId === focus)),
  [allOrderedPlots, focus, snapshot.timeline.nodes]);
  const geometry = useMemo(() => buildTimelineGeometry(
    canvasWidth,
    allOrderedPlots.map((plot) => plot.entityId),
    snapshot.timeline.lines,
    snapshot.timeline.nodes,
    snapshot.timeline.mainLineId,
  ), [allOrderedPlots, canvasWidth, snapshot.timeline]);
  const visibleLineIds = useMemo(() => visibleTimelineTrackIds(geometry, visibleRange.top, visibleRange.bottom), [geometry, visibleRange]);
  const visibleTimelineLines = useMemo(() => snapshot.timeline.lines.filter((line) => visibleLineIds.has(line.entityId)), [snapshot.timeline.lines, visibleLineIds]);
  const renderedPlots = useMemo(() => visiblePlots.filter((plot) => {
    const y = geometry.plotY.get(plot.entityId);
    return y != null && y >= visibleRange.top - 160 && y <= visibleRange.bottom + 160;
  }), [geometry.plotY, visiblePlots, visibleRange]);
  const visibleLineNodeCount = (lineId: string) => snapshot.timeline.nodes.filter((node) => {
    if (node.lineId !== lineId) return false;
    const y = geometry.plotY.get(node.plotId);
    return y != null && y >= visibleRange.top - 24 && y <= visibleRange.bottom + 24;
  }).length;
  const editorOrderedAssignments = useMemo(() => [...assignments]
    .sort((left, right) => left.storySortKey.localeCompare(right.storySortKey)), [assignments]);
  const editorTimelineLines = useMemo<TimelineLine[]>(() => lines.map((line, index) => ({
    entityId: line.entityId,
    id: line.stableId,
    name: line.name,
    color: line.color,
    side: line.entityId === mainLineId ? "center" : line.side,
    sortKey: rank(index + 1),
    startPlotId: line.startPlotId,
    endPlotId: line.endPlotId,
    revision: 0,
  })), [lines, mainLineId]);
  const editorTimelineNodes = useMemo<TimelineNode[]>(() => editorOrderedAssignments.flatMap((assignment) => assignment.lineIds.map((lineId) => ({
    plotId: assignment.plotId,
    lineId,
    storySortKey: assignment.storySortKey,
  }))), [editorOrderedAssignments]);
  const editorGeometry = useMemo(() => buildTimelineGeometry(
    editorCanvasWidth,
    editorOrderedAssignments.map((assignment) => assignment.plotId),
    editorTimelineLines,
    editorTimelineNodes,
    mainLineId,
  ), [editorCanvasWidth, editorOrderedAssignments, editorTimelineLines, editorTimelineNodes, mainLineId]);

  useEffect(() => {
    const element = canvasWrapRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setCanvasWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const element = canvasWrapRef.current;
    if (!element) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const bounds = element.getBoundingClientRect();
      const top = Math.max(0, Math.min(geometry.height, -bounds.top));
      const bottom = Math.max(top, Math.min(geometry.height, top + window.innerHeight));
      setVisibleRange((current) => current.top === top && current.bottom === bottom ? current : { top, bottom });
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(update); };
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    update();
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [geometry.height]);
  useEffect(() => {
    if (focus && !visibleLineIds.has(focus)) setFocus(null);
  }, [focus, setFocus, visibleLineIds]);
  useEffect(() => {
    const element = editorTimelineScrollRef.current;
    if (!editing || !element) return;
    const observer = new ResizeObserver(([entry]) => setEditorCanvasWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, [editing]);
  useEffect(() => {
    const scroller = editorTimelineScrollRef.current;
    if (!editing || !scroller) return;
    const track = editorGeometry.tracks.find((item) => item.id === selectedEditLine);
    const targetY = selectedEditPlot ? editorGeometry.plotY.get(selectedEditPlot) : track?.startY;
    if (targetY == null) return;
    const frame = requestAnimationFrame(() => scroller.scrollTo({
      top: Math.max(0, targetY - scroller.clientHeight * .45),
      behavior: "auto",
    }));
    return () => cancelAnimationFrame(frame);
  }, [editing, editorGeometry, selectedEditLine, selectedEditPlot]);

  const beginEdit = () => {
    const nextLines = snapshot.timeline.lines.map((line) => ({
      entityId: line.entityId,
      stableId: line.id,
      persisted: true,
      name: line.name,
      color: line.color,
      side: line.side,
      startPlotId: line.startPlotId,
      endPlotId: line.endPlotId,
    }));
    const nextAssignments = snapshot.plots.map((plot, index) => {
      const nodes = snapshot.timeline.nodes.filter((node) => node.plotId === plot.entityId);
      return {
        plotId: plot.entityId,
        lineIds: [...new Set(nodes.map((node) => node.lineId))],
        storySortKey: nodes.map((node) => node.storySortKey).sort()[0] || rank(index + 1),
      };
    });
    const initialLine = focus && nextLines.some((line) => line.entityId === focus)
      ? focus
      : snapshot.timeline.mainLineId || nextLines[0]?.entityId || "";
    setLines(nextLines);
    setAssignments(nextAssignments);
    setMainLineId(snapshot.timeline.mainLineId || nextLines[0]?.entityId || "");
    setSelectedEditLine(initialLine);
    setSelectedEditPlot(nextAssignments.find((item) => item.lineIds.includes(initialLine))?.plotId || null);
    setLineReplacements({});
    setMessage("");
    setEditing(true);
  };
  const addLine = () => {
    const stableId = generatedLineId();
    const entityId = `timeline_line:${stableId}`;
    setLines((current) => [...current, {
      entityId,
      stableId,
      persisted: false,
      name: `新剧情线 ${current.length + 1}`,
      color: "#3ba878",
      side: "right",
      startPlotId: null,
      endPlotId: null,
    }]);
    setSelectedEditLine(entityId);
    setSelectedEditPlot(null);
  };
  const selectEditorLine = (lineId: string) => {
    setSelectedEditLine(lineId);
    setSelectedEditPlot(assignments
      .filter((item) => item.lineIds.includes(lineId))
      .sort((left, right) => left.storySortKey.localeCompare(right.storySortKey))[0]?.plotId || null);
  };
  const requestRemoveLine = (entityId: string) => {
    const target = lines.find((line) => line.entityId !== entityId)?.entityId || "";
    setDeleteLine(entityId);
    setReplacement(target);
  };
  const removeSelectedLine = () => {
    if (!deleteLine || !replacement || lines.length <= 1) return;
    setLines((current) => current.filter((line) => line.entityId !== deleteLine));
    setAssignments((current) => current.map((item) => {
      if (!item.lineIds.includes(deleteLine)) return item;
      return { ...item, lineIds: [...new Set(item.lineIds.map((id) => id === deleteLine ? replacement : id))] };
    }));
    setLineReplacements((current) => ({ ...current, [deleteLine]: replacement }));
    if (mainLineId === deleteLine) setMainLineId(replacement);
    if (selectedEditLine === deleteLine) setSelectedEditLine(replacement);
    setDeleteLine(null);
  };
  const changeLine = <K extends keyof LineDraft>(key: K, value: LineDraft[K]) => {
    setLines((current) => current.map((line) => line.entityId === selectedEditLine ? { ...line, [key]: value } : line));
    setMessage("");
  };
  const togglePlotLine = (plotId: string, lineId: string) => {
    setAssignments((current) => current.map((item) => {
      if (item.plotId !== plotId) return item;
      const present = item.lineIds.includes(lineId);
      if (present && item.lineIds.length === 1) return item;
      return { ...item, lineIds: present ? item.lineIds.filter((id) => id !== lineId) : [...item.lineIds, lineId] };
    }));
  };
  const moveStoryNode = (plotId: string, direction: -1 | 1) => {
    const visible = assignments
      .filter((item) => item.lineIds.includes(selectedEditLine))
      .sort((left, right) => left.storySortKey.localeCompare(right.storySortKey));
    const index = visible.findIndex((item) => item.plotId === plotId);
    const target = visible[index + direction];
    if (index < 0 || !target) return;
    const currentKey = visible[index].storySortKey;
    setAssignments((current) => current.map((item) => {
      if (item.plotId === plotId) return { ...item, storySortKey: target.storySortKey };
      if (item.plotId === target.plotId) return { ...item, storySortKey: currentKey };
      return item;
    }));
  };
  const save = async () => {
    if (!lines.length || !mainLineId || mutation.isPending) return;
    try {
      const result = await mutation.mutateAsync({
        path: "/timeline",
        method: "PUT",
        payload: {
          mainLineId,
          lineSpacing: snapshot.timeline.lineSpacing,
          topPadding: snapshot.timeline.topPadding,
          sidePadding: snapshot.timeline.sidePadding,
          pixelsPerStoryUnit: snapshot.timeline.pixelsPerStoryUnit,
          lines: lines.map((line) => ({
            entityId: line.persisted ? line.entityId : "",
            stableId: line.stableId,
            name: line.name,
            color: line.color,
            side: line.entityId === mainLineId ? "center" : line.side === "center" ? "right" : line.side,
            startPlotId: line.startPlotId,
            endPlotId: line.endPlotId,
          })),
          assignments: assignments.map((item) => ({
            plotId: item.plotId,
            lineIds: item.lineIds,
            storySortKey: item.storySortKey,
          })),
          lineReplacements,
        },
      });
      setMessage(result.warnings[0] || "时间线已保存");
      setFocus(selectedEditLine || null);
      setEditing(false);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    }
  };

  const plot = snapshot.plots.find((item) => item.entityId === selectedPlot);
  const plotDetail = useQuery({
    queryKey: ["entity", project, selectedPlot],
    queryFn: () => api.detail<Plot>(selectedPlot!),
    enabled: Boolean(selectedPlot && !snapshot.readonly),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const plotPreview = plot?.summary || plot?.body || plotDetail.data?.data.body || (plotDetail.isPending ? "_正在读取剧情预览…_" : plot?.bodyPreview) || "_还没有摘要。_";
  const selectedLine = lines.find((line) => line.entityId === selectedEditLine);
  const editNodes = assignments
    .filter((item) => item.lineIds.includes(selectedEditLine))
    .sort((left, right) => left.storySortKey.localeCompare(right.storySortKey));
  const editNodeIndex = editNodes.findIndex((item) => item.plotId === selectedEditPlot);
  const editPlot = snapshot.plots.find((item) => item.entityId === selectedEditPlot);
  const editAssignment = assignments.find((item) => item.plotId === selectedEditPlot);
  const deleteTarget = lines.find((line) => line.entityId === deleteLine);
  const deleteNodeCount = assignments.filter((item) => item.lineIds.includes(deleteLine || "")).length;
  return <section className="workspace-page timeline-page-new">
    <header className="page-header"><div><small>Story Time</small><h1>时间线</h1><p>纵向是故事发生顺序；剧情页中的篇章顺序是读者阅读顺序，两者互不改写。</p></div>{writable && <button className="icon-button" aria-label="编辑时间线" title="编辑时间线" onClick={beginEdit}><Icon name="edit" /></button>}</header>
    {message && <p className="page-message">{message}</p>}
    <div className="timeline-workspace">
      <aside className={`timeline-line-rail${writable ? " has-editor" : ""}`} aria-label="时间线图示">
        <div className="timeline-line-options" aria-label="当前可见剧情线">{visibleTimelineLines.map((line) => <button key={line.entityId} data-line-id={line.entityId} className={focus === line.entityId ? "is-active" : ""} type="button" title={`${line.name} · 当前可见 ${visibleLineNodeCount(line.entityId)} 个节点`} aria-pressed={focus === line.entityId} onClick={() => setFocus(focus === line.entityId ? null : line.entityId)}><span className="line-swatch" style={{ background: line.color }} /><strong>{line.name}</strong><small>{visibleLineNodeCount(line.entityId)}</small></button>)}</div>
      </aside>
      <div
        className="timeline-canvas-new"
        ref={canvasWrapRef}
        style={{ minHeight: `${geometry.height}px` }}
        onClick={(event) => {
          if ((event.target as HTMLElement).closest(".timeline-node-new, .timeline-plot-card")) return;
          const bounds = event.currentTarget.getBoundingClientRect();
          const x = event.clientX - bounds.left;
          const y = event.clientY - bounds.top;
          const nearest = geometry.tracks
            .filter((track) => (
              y >= track.startY - timelineTurnHeight(track.startSourceX, track.x)
              && y <= track.endY + timelineTurnHeight(track.x, track.endTargetX)
            ))
            .sort((left, right) => Math.abs(left.x - x) - Math.abs(right.x - x))[0];
          setFocus(nearest && Math.abs(nearest.x - x) <= 18 ? nearest.id : null);
        }}
      >
        <TimelineTrackCanvas geometry={geometry} focus={focus} />
        {geometry.tracks.filter((track) => track.isMain).map((track) => <span key={`${track.id}:origin`} className="timeline-origin" style={{ left: track.x, top: track.startY, "--line-color": track.color } as React.CSSProperties} title={`${track.name}起点`} />)}
        {renderedPlots.map((item) => {
          const nodes = snapshot.timeline.nodes.filter((node) => node.plotId === item.entityId);
          const lineId = focus || (nodes.some((node) => node.lineId === snapshot.timeline.mainLineId) ? snapshot.timeline.mainLineId : nodes[0]?.lineId);
          const track = geometry.tracks.find((candidate) => candidate.id === lineId) || geometry.tracks[0];
          const y = geometry.plotY.get(item.entityId) || TIMELINE_TOP;
          return <button key={item.entityId} className="timeline-node-new" aria-label={`查看剧情：${item.title}`} title={`${item.title} · 故事 ${globalStoryOrder.get(item.entityId)} · 阅读 ${item.sequence}`} style={{ top: y, left: track?.x || 350, "--node-color": track?.color || item.accent } as React.CSSProperties} onClick={(event) => { event.stopPropagation(); setSelectedPlot(item.entityId); }}><span /></button>;
        })}
        {plot && <aside className="timeline-plot-card" style={{ top: 30 }} onClick={(event) => event.stopPropagation()}><button className="icon-button" aria-label="关闭剧情卡片" onClick={() => setSelectedPlot(null)}><Icon name="close" /></button><small>剧情节点 · 故事 {globalStoryOrder.get(plot.entityId)} · 阅读 {plot.sequence}</small><h2>{plot.title}</h2><RenderedMarkdown source={plotPreview} className="timeline-plot-preview" /><button className="primary-action" onClick={() => { useUiStore.getState().selectPlot(plot.entityId); useUiStore.getState().navigate("story"); }}>进入完整文章</button></aside>}
      </div>
    </div>
    {editing && <div className="dialog-backdrop"><section className="timeline-editor-dialog is-structured" role="dialog" aria-modal="true" aria-label="编辑时间线"><header><div><small>Timeline Editor</small><h2>编辑时间线</h2><p>左侧显示完整故事时间；在右侧选择剧情线或篇章，左侧会自动定位。</p></div><button className="icon-button" aria-label="关闭" onClick={() => setEditing(false)}><Icon name="close" /></button></header>
      <div className="timeline-editor-body">
        <section className="timeline-editor-map"><header><strong>故事时间线</strong><small>{editorTimelineLines.length} 条线 · {editorOrderedAssignments.length} 篇</small></header><div className="timeline-editor-visual-scroll" ref={editorTimelineScrollRef}><div className="timeline-editor-visual-world" style={{ minHeight: `${editorGeometry.height}px` }} onClick={(event) => {
          if ((event.target as HTMLElement).closest(".timeline-editor-track-node")) return;
          const bounds = event.currentTarget.getBoundingClientRect();
          const x = event.clientX - bounds.left;
          const y = event.clientY - bounds.top;
          const nearest = editorGeometry.tracks
            .filter((track) => (
              y >= track.startY - timelineTurnHeight(track.startSourceX, track.x)
              && y <= track.endY + timelineTurnHeight(track.x, track.endTargetX)
            ))
            .sort((left, right) => Math.abs(left.x - x) - Math.abs(right.x - x))[0];
          if (nearest && Math.abs(nearest.x - x) <= 20) selectEditorLine(nearest.id);
        }}>
          <TimelineTrackCanvas geometry={editorGeometry} focus={selectedEditLine || null} />
          {editorGeometry.tracks.filter((track) => track.isMain).map((track) => <span key={`${track.id}:editor-origin`} className="timeline-origin" style={{ left: track.x, top: track.startY, "--line-color": track.color } as React.CSSProperties} />)}
          {editorOrderedAssignments.flatMap((assignment) => assignment.lineIds.map((lineId) => {
            const itemPlot = snapshot.plots.find((item) => item.entityId === assignment.plotId);
            const track = editorGeometry.tracks.find((item) => item.id === lineId);
            const line = lines.find((item) => item.entityId === lineId);
            const y = editorGeometry.plotY.get(assignment.plotId) || TIMELINE_TOP;
            if (!track || !itemPlot) return null;
            return <button key={`${assignment.plotId}:${lineId}`} className={`timeline-editor-track-node${selectedEditPlot === assignment.plotId && selectedEditLine === lineId ? " is-active" : ""}${selectedEditLine && selectedEditLine !== lineId ? " is-muted" : ""}`} data-plot-id={assignment.plotId} data-line-id={lineId} aria-label={`选择${line?.name || "剧情线"}的第${itemPlot.sequence}篇：${itemPlot.title}`} title={`${line?.name || "剧情线"} · 第 ${itemPlot.sequence} 篇 · ${itemPlot.title}`} style={{ left: track.x, top: y, "--node-color": line?.color || itemPlot.accent } as React.CSSProperties} onClick={(event) => { event.stopPropagation(); setSelectedEditLine(lineId); setSelectedEditPlot(assignment.plotId); }}><span /></button>;
          }))}
        </div></div></section>
        <aside className="timeline-editor-inspector">
          <section className="timeline-editor-toolbar"><div className="timeline-editor-selector-row"><label><span>当前剧情线</span><select value={selectedEditLine} onChange={(event) => selectEditorLine(event.target.value)}>{lines.map((line) => <option key={line.entityId} value={line.entityId}>{line.name}{line.entityId === mainLineId ? " · 主线" : ""}</option>)}</select></label><button className="icon-button" aria-label="插入剧情线" title="插入剧情线" onClick={addLine}><Icon name="plus" /></button></div><label><span>当前篇章</span><select value={selectedEditPlot || ""} disabled={!editNodes.length} onChange={(event) => setSelectedEditPlot(event.target.value || null)}><option value="">选择篇章</option>{editNodes.map((item, index) => { const itemPlot = snapshot.plots.find((plotItem) => plotItem.entityId === item.plotId); return <option key={item.plotId} value={item.plotId}>故事 {index + 1} · 阅读 {itemPlot?.sequence} · {itemPlot?.title}</option>; })}</select></label></section>
          <section><div className="section-heading"><h3>剧情线设置</h3><button className="icon-button is-danger" disabled={lines.length === 1} aria-label={`删除${selectedLine?.name || "剧情线"}`} title="删除剧情线" onClick={() => requestRemoveLine(selectedEditLine)}><Icon name="trash" /></button></div><div className="timeline-line-fields"><label><span>名称</span><input value={selectedLine?.name || ""} onChange={(event) => changeLine("name", event.target.value)} /></label><label><span>颜色</span><input type="color" value={selectedLine?.color || "#3f7fc1"} onChange={(event) => changeLine("color", event.target.value)} /></label><label><span>位置</span><select disabled={selectedEditLine === mainLineId} value={selectedEditLine === mainLineId ? "center" : selectedLine?.side || "right"} onChange={(event) => changeLine("side", event.target.value as LineDraft["side"])}><option value="left">左侧</option><option value="right">右侧</option><option value="center">主线</option></select></label><label className="main-line-choice"><input type="radio" checked={selectedEditLine === mainLineId} onChange={() => setMainLineId(selectedEditLine)} />设为主线</label></div></section>{editPlot && editAssignment ? <section><div className="section-heading"><div><h3>篇章详情</h3><small>故事位置 {editNodeIndex + 1} · 阅读第 {editPlot.sequence} 篇</small></div><div className="row-icon-actions"><button className="icon-button" disabled={editNodeIndex <= 0} aria-label={`上移${editPlot.title}`} title="故事时间提前" onClick={() => moveStoryNode(editPlot.entityId, -1)}><Icon name="up" /></button><button className="icon-button" disabled={editNodeIndex < 0 || editNodeIndex === editNodes.length - 1} aria-label={`下移${editPlot.title}`} title="故事时间延后" onClick={() => moveStoryNode(editPlot.entityId, 1)}><Icon name="down" /></button></div></div><h2>{editPlot.title}</h2><RenderedMarkdown source={editPlot.summary || editPlot.bodyPreview || "还没有摘要"} className="content-card-preview" /><h4>所属剧情线</h4><div className="timeline-membership-list">{lines.map((line) => <label key={line.entityId}><input type="checkbox" checked={editAssignment.lineIds.includes(line.entityId)} onChange={() => togglePlotLine(editPlot.entityId, line.entityId)} /><span className="line-swatch" style={{ background: line.color }} />{line.name}</label>)}</div><button className="text-action" onClick={() => { useUiStore.getState().selectPlot(editPlot.entityId); useUiStore.getState().navigate("story"); setEditing(false); }}>进入完整文章</button></section> : <section className="empty-state compact"><p>选择一条有节点的剧情线，或点击左侧时间线节点。</p></section>}</aside>
      </div>
      <footer><span>{message}</span><button className="primary-action" disabled={mutation.isPending} onClick={save}>{mutation.isPending ? "正在保存…" : "保存时间线"}</button></footer>
    </section><ConfirmDialog open={Boolean(deleteLine)} title={`删除“${deleteTarget?.name || "这条剧情线"}”？`} message={deleteNodeCount ? `其中 ${deleteNodeCount} 个节点会在同一事务中转移到接收剧情线。` : "剧情线会进入统一回收站保留 7 天。"} confirmLabel={deleteNodeCount ? "转移并删除" : "移入回收站"} danger confirmDisabled={!replacement} onCancel={() => setDeleteLine(null)} onConfirm={removeSelectedLine}><label className="confirm-field"><span>接收剧情线</span><select value={replacement} onChange={(event) => setReplacement(event.target.value)}>{lines.filter((line) => line.entityId !== deleteLine).map((line) => <option key={line.entityId} value={line.entityId}>{line.name}</option>)}</select></label></ConfirmDialog></div>}
  </section>;
}
