import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import type { Character, GraphData, Relationship } from "../api/types";
import { useProjectMutation, useRuntime } from "../api/runtime";
import { CollapsibleList } from "../components/CollapsibleList";
import { Icon } from "../components/Icon";
import {
  drawGraphMotionOverlay,
  drawGraphScene,
  graphRelationshipLabels,
  graphScenePoint,
  hitTestGraphNode,
  createGraphScene,
  quadraticPoint,
  relationshipCurveLanes,
} from "../graph/graphScene";
import type { GraphScene, GraphSceneMotion, Point } from "../graph/graphScene";
import { useUiStore } from "../state/ui";
import { avatarBackground } from "../theme/contentColors";

export { graphRelationshipLabels, quadraticPoint, relationshipCurveLanes } from "../graph/graphScene";

const GraphEditor = lazy(async () => ({ default: (await import("../components/GraphEditor")).GraphEditor }));

export function graphRelationshipsForFocus(relationships: Relationship[], selectedId: string | null): Relationship[] {
  return relationships.filter((item) => (item.graphScope || "core") === "core"
    || (item.graphScope === "focus" && Boolean(selectedId) && (item.from === selectedId || item.to === selectedId)));
}

export function graphMotionIsActive(now: number, activeUntil: number, reducedMotion = false): boolean {
  return !reducedMotion && now < activeUntil;
}

export function graphMotionFrameInterval(mode: "idle" | "active"): number {
  return mode === "idle" ? 1000 / 12 : 1000 / 30;
}

export function graphDragPoint(
  point: Point,
  width: number,
  height: number,
  viewport: { x: number; y: number; scale: number },
  screenMargin = 64,
): Point {
  const scale = Math.max(.001, viewport.scale);
  const minimumX = (screenMargin - viewport.x) / scale;
  const maximumX = (width - screenMargin - viewport.x) / scale;
  const minimumY = (screenMargin - viewport.y) / scale;
  const maximumY = (height - screenMargin - viewport.y) / scale;
  return {
    x: Math.max(minimumX, Math.min(maximumX, point.x)),
    y: Math.max(minimumY, Math.min(maximumY, point.y)),
  };
}

function finite(value: unknown, fallback: number): number {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function noise(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) hash = Math.imul(hash ^ value.charCodeAt(index), 16777619);
  return (hash >>> 0) / 4294967295;
}

function graphUsesPercentCoordinates(graph: GraphData): boolean {
  const clusterCoordinates = graph.clusters.flatMap((item) => [item.centerX, item.centerY]).filter((value) => value != null).map(Number);
  const anchorCoordinates = graph.nodes.flatMap((item) => [item.anchor_x, item.anchor_y]).filter((value) => value != null).map(Number);
  const looksLikePercent = (values: number[]) => values.length > 0 && values.every((value) => Number.isFinite(value) && value >= 0 && value <= 100);
  return looksLikePercent(clusterCoordinates) || (anchorCoordinates.length >= 6 && looksLikePercent(anchorCoordinates));
}

export function graphLayout(
  width: number,
  height: number,
  characters: Character[],
  graph: GraphData,
  relationships: Relationship[],
): Map<string, Point> {
  const visible = characters.filter((item) => item.graphVisible);
  const visibleIds = new Set(visible.map((item) => item.entityId));
  const center = { x: width / 2, y: height / 2 };
  const spacing = finite(graph.settings.node_spacing, 116);
  const relationDistance = finite(graph.settings.relationship_distance, 250);
  const centerStrength = finite(graph.settings.center_strength, 1);
  const groupStrength = finite(graph.settings.group_strength, 1);
  const nodeRules = new Map(graph.nodes.map((item) => [item.character_id, item]));
  const percentCoordinates = graphUsesPercentCoordinates(graph);
  const coordinate = (value: unknown, extent: number, fallback: number) => {
    if (value == null || value === "") return fallback;
    const number = Number(value);
    if (!Number.isFinite(number)) return fallback;
    return percentCoordinates ? number / 100 * extent : number;
  };
  const clusters = graph.clusters.map((cluster, index) => {
    const angle = (index / Math.max(1, graph.clusters.length)) * Math.PI * 2 - Math.PI / 2;
    const fallbackRadius = graph.clusters.length <= 1 ? 0 : Math.min(width, height) * .27;
    return {
      ...cluster,
      point: {
        x: coordinate(cluster.centerX, width, center.x + Math.cos(angle) * fallbackRadius),
        y: coordinate(cluster.centerY, height, center.y + Math.sin(angle) * fallbackRadius),
      },
    };
  });
  const clusterFor = new Map<string, typeof clusters[number]>();
  for (const cluster of clusters) for (const member of cluster.members) if (visibleIds.has(member) && !clusterFor.has(member)) clusterFor.set(member, cluster);
  const fallbackGroups = [...new Set(visible.map((item) => item.group || "其他"))];
  const points = new Map<string, Point>();
  visible.forEach((item, index) => {
    const rule = nodeRules.get(item.entityId);
    const cluster = clusterFor.get(item.entityId);
    const groupIndex = fallbackGroups.indexOf(item.group || "其他");
    const groupAngle = (groupIndex / Math.max(1, fallbackGroups.length)) * Math.PI * 2 - Math.PI / 2;
    const groupRadius = fallbackGroups.length <= 1 ? 0 : Math.min(width, height) * .24;
    const target = cluster?.point || {
      x: center.x + Math.cos(groupAngle) * groupRadius,
      y: center.y + Math.sin(groupAngle) * groupRadius,
    };
    const angle = noise(`${item.entityId}:angle`) * Math.PI * 2;
    const radius = (index ? spacing * (.55 + noise(`${item.entityId}:radius`)) : 0);
    points.set(item.entityId, {
      x: rule?.anchor_x == null ? target.x + Math.cos(angle) * radius : coordinate(rule.anchor_x, width, target.x),
      y: rule?.anchor_y == null ? target.y + Math.sin(angle) * radius : coordinate(rule.anchor_y, height, target.y),
    });
  });
  const fixed = (id: string) => {
    const rule = nodeRules.get(id);
    return Boolean(rule && (rule.anchor_x != null || rule.anchor_y != null || rule.orbit_of));
  };
  const applyFixedRules = () => {
    for (const item of visible) {
      const rule = nodeRules.get(item.entityId);
      const point = points.get(item.entityId);
      if (!rule || !point) continue;
      if (rule.anchor_x != null) point.x = coordinate(rule.anchor_x, width, point.x);
      if (rule.anchor_y != null) point.y = coordinate(rule.anchor_y, height, point.y);
      const parent = rule.orbit_of ? points.get(rule.orbit_of) : null;
      if (parent) {
        const angle = finite(rule.orbit_angle, noise(item.entityId) * 360) * Math.PI / 180;
        const distance = finite(rule.orbit_distance, spacing * 1.35);
        point.x = parent.x + Math.cos(angle) * distance;
        point.y = parent.y + Math.sin(angle) * distance;
      }
    }
  };
  const explicit = graph.distances.filter((item) => visibleIds.has(item.from_character_id) && visibleIds.has(item.to_character_id));
  const explicitPairs = new Set(explicit.flatMap((item) => [`${item.from_character_id}\0${item.to_character_id}`, `${item.to_character_id}\0${item.from_character_id}`]));
  const links = [
    ...explicit.map((item) => ({ from: item.from_character_id, to: item.to_character_id, distance: finite(item.distance, relationDistance), strength: finite(item.strength, 1) })),
    ...relationships.filter((item) => visibleIds.has(item.from) && visibleIds.has(item.to) && !explicitPairs.has(`${item.from}\0${item.to}`)).map((item) => ({ from: item.from, to: item.to, distance: relationDistance, strength: 1 })),
  ];
  for (let iteration = 0; iteration < 36; iteration += 1) {
    for (let leftIndex = 0; leftIndex < visible.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < visible.length; rightIndex += 1) {
        const left = visible[leftIndex]; const right = visible[rightIndex];
        const a = points.get(left.entityId)!; const b = points.get(right.entityId)!;
        const dx = b.x - a.x || .001; const dy = b.y - a.y || .001;
        const distance = Math.max(1, Math.hypot(dx, dy));
        if (distance >= spacing) continue;
        const push = (spacing - distance) * .08;
        if (!fixed(left.entityId)) { a.x -= dx / distance * push; a.y -= dy / distance * push; }
        if (!fixed(right.entityId)) { b.x += dx / distance * push; b.y += dy / distance * push; }
      }
    }
    for (const link of links) {
      const from = points.get(link.from); const to = points.get(link.to);
      if (!from || !to) continue;
      const dx = to.x - from.x || .001; const dy = to.y - from.y || .001;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const pull = (distance - link.distance) * .018 * Math.min(5, link.strength);
      if (!fixed(link.from)) { from.x += dx / distance * pull; from.y += dy / distance * pull; }
      if (!fixed(link.to)) { to.x -= dx / distance * pull; to.y -= dy / distance * pull; }
    }
    for (const item of visible) {
      if (fixed(item.entityId)) continue;
      const point = points.get(item.entityId)!;
      const target = clusterFor.get(item.entityId)?.point || center;
      const attraction = clusterFor.has(item.entityId) ? groupStrength : centerStrength * .2;
      point.x += (target.x - point.x) * .0025 * attraction;
      point.y += (target.y - point.y) * .0025 * attraction;
      point.x = Math.max(50, Math.min(width - 50, point.x));
      point.y = Math.max(50, Math.min(height - 50, point.y));
    }
    applyFixedRules();
  }
  for (const item of visible) {
    if (fixed(item.entityId)) continue;
    const point = points.get(item.entityId)!;
    point.x = Math.max(64, Math.min(width - 64, point.x));
    point.y = Math.max(64, Math.min(height - 64, point.y));
  }
  return points;
}

export default function GraphPage() {
  const { snapshot, writable } = useRuntime();
  const mutation = useProjectMutation();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const motionCanvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<GraphScene | null>(null);
  const renderFrameRef = useRef(0);
  const renderTimerRef = useRef(0);
  const motionRef = useRef<{ activeUntil: number; hoveredNodeId: string | null }>({ activeUntil: 0, hoveredNodeId: null });
  const panRef = useRef<{ pointerId: number; x: number; y: number; originX: number; originY: number; moved: boolean } | null>(null);
  const nodeDragRef = useRef<{ id: string; pointerId: number; startX: number; startY: number; offsetX: number; offsetY: number; lastPoint: Point; moved: boolean } | null>(null);
  const focusViewportRef = useRef<{ x: number; y: number; scale: number } | null>(null);
  const [size, setSize] = useState({ width: 1000, height: 680 });
  const [editing, setEditing] = useState(false);
  const [manualPoints, setManualPoints] = useState<Map<string, Point>>(() => new Map());
  const [saveError, setSaveError] = useState("");
  const selected = useUiStore((state) => state.selectedGraphCharacterId);
  const select = useUiStore((state) => state.selectGraphCharacter);
  const viewport = useUiStore((state) => state.graphViewport);
  const setViewport = useUiStore((state) => state.setGraphViewport);
  const viewportRef = useRef(viewport);
  viewportRef.current = viewport;

  const layoutPoints = useMemo(
    () => graphLayout(size.width, size.height, snapshot.characters, snapshot.graph, snapshot.relationships.filter((item) => (item.graphScope || "core") === "core")),
    [size, snapshot.characters, snapshot.graph, snapshot.relationships],
  );
  const points = useMemo(() => {
    const merged = new Map(layoutPoints);
    for (const [id, point] of manualPoints) if (merged.has(id)) merged.set(id, point);
    return merged;
  }, [layoutPoints, manualPoints]);
  const visible = useMemo(() => snapshot.characters.filter((item) => points.has(item.entityId)), [points, snapshot.characters]);
  const relationships = useMemo(() => {
    const visibleIds = new Set(visible.map((item) => item.entityId));
    return graphRelationshipsForFocus(snapshot.relationships, selected)
      .filter((item) => visibleIds.has(item.from) && visibleIds.has(item.to));
  }, [selected, snapshot.relationships, visible]);
  const scene = useMemo(
    () => createGraphScene(size.width, size.height, viewport, visible, points, relationships, snapshot.entries, selected),
    [points, relationships, selected, size, snapshot.entries, viewport, visible],
  );
  sceneRef.current = scene;
  const selectedPerson = snapshot.characters.find((item) => item.entityId === selected);
  const selectedOrganizations = useMemo(() => selected
    ? snapshot.entries.filter((entry) => entry.type === "组织" && (entry.members || []).some((member) => member.characterId === selected)).map((entry) => ({
      entry,
      membership: (entry.members || []).find((member) => member.characterId === selected)!,
    }))
    : [], [selected, snapshot.entries]);
  const duplicateCharacterNames = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of snapshot.characters) counts.set(item.name, (counts.get(item.name) || 0) + 1);
    return new Set([...counts].filter(([, count]) => count > 1).map(([name]) => name));
  }, [snapshot.characters]);

  const drawCurrent = (
    overrides?: Map<string, Point>,
    viewportOverride = viewportRef.current,
  ) => {
    const canvas = canvasRef.current;
    const currentScene = sceneRef.current;
    if (canvas && currentScene) drawGraphScene(canvas, currentScene, overrides, viewportOverride);
  };
  const drawMotion = (
    overrides?: Map<string, Point>,
    viewportOverride = viewportRef.current,
    motion?: GraphSceneMotion,
  ) => {
    const canvas = motionCanvasRef.current;
    const currentScene = sceneRef.current;
    if (canvas && currentScene) drawGraphMotionOverlay(canvas, currentScene, overrides, viewportOverride, motion);
  };

  function queueRenderFrame(delay = 0) {
    if (renderFrameRef.current || renderTimerRef.current) return;
    if (delay > 0) {
      renderTimerRef.current = window.setTimeout(() => {
        renderTimerRef.current = 0;
        renderFrameRef.current = requestAnimationFrame(renderScheduledFrame);
      }, delay);
      return;
    }
    renderFrameRef.current = requestAnimationFrame(renderScheduledFrame);
  }

  function renderScheduledFrame(time: number) {
    renderFrameRef.current = 0;
    const drag = nodeDragRef.current;
    const pan = panRef.current;
    const interacting = Boolean(drag?.moved || pan?.moved);
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches || false;
    const motionActive = graphMotionIsActive(time, motionRef.current.activeUntil, reducedMotion);
    const motionEnabled = document.visibilityState !== "hidden" && !reducedMotion;
    const mode = interacting || motionActive ? "active" : "idle";
    const overrides = drag ? new Map([[drag.id, drag.lastPoint]]) : undefined;
    if (interacting) drawCurrent(overrides, viewportRef.current);
    drawMotion(overrides, viewportRef.current, motionEnabled ? {
      active: true,
      mode,
      time,
      hoveredNodeId: motionRef.current.hoveredNodeId,
    } : undefined);
    if (interacting || motionActive || motionEnabled) queueRenderFrame(graphMotionFrameInterval(mode));
  }

  function scheduleRender(duration = 0) {
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches || false;
    if (duration > 0 && !reducedMotion) {
      motionRef.current.activeUntil = Math.max(motionRef.current.activeUntil, performance.now() + duration);
    }
    if (renderTimerRef.current) {
      window.clearTimeout(renderTimerRef.current);
      renderTimerRef.current = 0;
    }
    queueRenderFrame();
  }

  useEffect(() => {
    if (!wrapRef.current) return;
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(wrapRef.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    drawCurrent();
    scheduleRender(selected ? 1400 : 900);
  }, [scene]);
  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        if (renderFrameRef.current) cancelAnimationFrame(renderFrameRef.current);
        if (renderTimerRef.current) window.clearTimeout(renderTimerRef.current);
        renderFrameRef.current = 0;
        renderTimerRef.current = 0;
        drawMotion();
        return;
      }
      scheduleRender();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
  }, []);
  useEffect(() => () => {
    if (renderFrameRef.current) cancelAnimationFrame(renderFrameRef.current);
    if (renderTimerRef.current) window.clearTimeout(renderTimerRef.current);
    const state = useUiStore.getState();
    state.selectGraphCharacter(null);
    if (focusViewportRef.current) state.setGraphViewport(focusViewportRef.current);
  }, []);

  const previewViewport = (next: typeof viewport) => {
    viewportRef.current = next;
    scheduleRender();
  };
  const commitViewport = (next: typeof viewport) => {
    viewportRef.current = next;
    setViewport(next);
    drawCurrent(undefined, next);
  };
  const center = (id: string, pointOverride?: Point) => {
    const point = pointOverride || points.get(id);
    if (!point) return;
    const currentViewport = viewportRef.current;
    if (!selected) focusViewportRef.current = { ...currentViewport };
    select(id);
    commitViewport({
      ...currentViewport,
      x: size.width / 2 - point.x * currentViewport.scale,
      y: size.height / 2 - point.y * currentViewport.scale,
    });
  };
  const clearFocus = () => {
    if (!selected) return;
    select(null);
    if (focusViewportRef.current) commitViewport(focusViewportRef.current);
    focusViewportRef.current = null;
  };
  const pointFromClient = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    const currentScene = sceneRef.current;
    if (!canvas || !currentScene) return null;
    return graphScenePoint(currentScene, clientX, clientY, canvas.getBoundingClientRect(), viewportRef.current);
  };
  const stageDraggedPoint = (id: string, point: Point) => {
    setManualPoints((current) => {
      const next = new Map(current);
      next.set(id, point);
      return next;
    });
  };
  const persistDraggedPoint = async (id: string, point: Point) => {
    if (!writable) return;
    setSaveError("");
    const percentCoordinates = graphUsesPercentCoordinates(snapshot.graph);
    const anchorX = percentCoordinates ? point.x / Math.max(1, size.width) * 100 : point.x;
    const anchorY = percentCoordinates ? point.y / Math.max(1, size.height) * 100 : point.y;
    const nodes = new Map(snapshot.graph.nodes.map((item) => [item.character_id, item]));
    const current = nodes.get(id);
    nodes.set(id, {
      character_id: id,
      orbit_of: null,
      orbit_distance: current?.orbit_distance ?? null,
      orbit_angle: current?.orbit_angle ?? null,
      strength: current?.strength ?? null,
      anchor_x: anchorX,
      anchor_y: anchorY,
    });
    try {
      await mutation.mutateAsync({
        path: "/graph",
        method: "PUT",
        payload: {
          nodes: [...nodes.values()].map((item) => ({
            characterId: item.character_id,
            orbitOf: item.orbit_of,
            orbitDistance: item.orbit_distance,
            orbitAngle: item.orbit_angle,
            strength: item.strength,
            anchorX: item.anchor_x,
            anchorY: item.anchor_y,
          })),
        },
      });
      setManualPoints((currentPoints) => {
        const next = new Map(currentPoints);
        next.delete(id);
        return next;
      });
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "位置保存失败");
    }
  };
  const onWheel: React.WheelEventHandler<HTMLCanvasElement> = (event) => {
    event.preventDefault();
    const bounds = event.currentTarget.getBoundingClientRect();
    const pointerX = event.clientX - bounds.left;
    const pointerY = event.clientY - bounds.top;
    const currentViewport = viewportRef.current;
    const scale = Math.max(.45, Math.min(2.4, currentViewport.scale * (event.deltaY > 0 ? .9 : 1.1)));
    const worldX = (pointerX - currentViewport.x) / currentViewport.scale;
    const worldY = (pointerY - currentViewport.y) / currentViewport.scale;
    commitViewport({ scale, x: pointerX - worldX * scale, y: pointerY - worldY * scale });
    scheduleRender(900);
  };
  const onPointerDown: React.PointerEventHandler<HTMLCanvasElement> = (event) => {
    if (event.button !== 0 || mutation.isPending) return;
    const point = pointFromClient(event.clientX, event.clientY);
    const currentScene = sceneRef.current;
    if (!point || !currentScene) return;
    const node = hitTestGraphNode(currentScene, point);
    event.currentTarget.setPointerCapture(event.pointerId);
    scheduleRender(1200);
    if (node) {
      nodeDragRef.current = {
        id: node.character.entityId,
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        offsetX: point.x - node.point.x,
        offsetY: point.y - node.point.y,
        lastPoint: { ...node.point },
        moved: false,
      };
      return;
    }
    const currentViewport = viewportRef.current;
    panRef.current = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      originX: currentViewport.x,
      originY: currentViewport.y,
      moved: false,
    };
  };
  const onPointerMove: React.PointerEventHandler<HTMLCanvasElement> = (event) => {
    const drag = nodeDragRef.current;
    if (drag && drag.pointerId === event.pointerId) {
      if (Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) > 4) drag.moved = true;
      if (!drag.moved) return;
      const point = pointFromClient(event.clientX, event.clientY);
      if (!point) return;
      drag.lastPoint = graphDragPoint({
        x: point.x - drag.offsetX,
        y: point.y - drag.offsetY,
      }, size.width, size.height, viewportRef.current);
      scheduleRender();
      return;
    }
    const pan = panRef.current;
    if (pan && pan.pointerId === event.pointerId) {
      if (Math.hypot(event.clientX - pan.x, event.clientY - pan.y) > 4) pan.moved = true;
      previewViewport({ ...viewportRef.current, x: pan.originX + event.clientX - pan.x, y: pan.originY + event.clientY - pan.y });
      scheduleRender(700);
      return;
    }
    const point = pointFromClient(event.clientX, event.clientY);
    const currentScene = sceneRef.current;
    motionRef.current.hoveredNodeId = point && currentScene
      ? hitTestGraphNode(currentScene, point)?.character.entityId || null
      : null;
    scheduleRender(900);
  };
  const onPointerUp: React.PointerEventHandler<HTMLCanvasElement> = (event) => {
    const drag = nodeDragRef.current;
    if (drag && drag.pointerId === event.pointerId) {
      nodeDragRef.current = null;
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
      if (drag.moved) {
        stageDraggedPoint(drag.id, drag.lastPoint);
        void persistDraggedPoint(drag.id, drag.lastPoint);
      } else {
        center(drag.id, drag.lastPoint);
      }
      drawCurrent();
      scheduleRender(1100);
      return;
    }
    const pan = panRef.current;
    if (!pan || pan.pointerId !== event.pointerId) return;
    panRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (pan.moved) commitViewport(viewportRef.current);
    else clearFocus();
    scheduleRender(900);
  };
  const onPointerCancel: React.PointerEventHandler<HTMLCanvasElement> = (event) => {
    const drag = nodeDragRef.current;
    if (drag && drag.pointerId === event.pointerId) {
      nodeDragRef.current = null;
      if (drag.moved) {
        stageDraggedPoint(drag.id, drag.lastPoint);
        void persistDraggedPoint(drag.id, drag.lastPoint);
      }
      drawCurrent();
      scheduleRender(700);
      return;
    }
    if (panRef.current?.moved) commitViewport(viewportRef.current);
    panRef.current = null;
    scheduleRender(500);
  };
  const onPointerLeave: React.PointerEventHandler<HTMLCanvasElement> = () => {
    motionRef.current.hoveredNodeId = null;
    scheduleRender(180);
  };
  const relatedPlots = selected ? snapshot.plots.filter((plot) => plot.people.includes(selected)) : [];
  return <section className="workspace-page graph-page-new"><header className="page-header graph-page-header"><div><small>Relationship Map</small><h1>人物图谱</h1><p>拖动节点调整位置，拖动空白区域平移；布局规则可以直接在网页维护。</p></div><div className="graph-header-actions">{writable && <button className="icon-button" aria-label="编辑人物图谱" title="编辑图谱布局" onClick={() => setEditing(true)}><Icon name="settings" /></button>}</div></header><div className="graph-canvas" ref={wrapRef}><canvas
    ref={canvasRef}
    className="graph-scene-canvas"
    role="application"
    aria-label="人物关系图谱，可拖动人物节点或平移画布"
    tabIndex={0}
    onWheel={onWheel}
    onPointerDown={onPointerDown}
    onPointerMove={onPointerMove}
    onPointerUp={onPointerUp}
    onPointerCancel={onPointerCancel}
    onPointerEnter={() => scheduleRender(900)}
    onPointerLeave={onPointerLeave}
  /><canvas ref={motionCanvasRef} className="graph-motion-canvas" aria-hidden="true" />{selectedPerson && <aside className="graph-profile-card"><header><span className="avatar" style={{ background: avatarBackground(selectedPerson) }}>{selectedPerson.name.slice(0, 1)}</span><div><small>人物档案{duplicateCharacterNames.has(selectedPerson.name) ? ` · ID ${selectedPerson.id}` : ""}</small><h2>{selectedPerson.name}</h2><p>{selectedPerson.narrativeRole} · {selectedPerson.side}</p></div><button className="icon-button" aria-label="进入人物详情" title="进入人物详情" onClick={() => { useUiStore.getState().selectCharacter(selectedPerson.entityId); useUiStore.getState().navigate("characters"); }}><Icon name="arrow" /></button></header><p>{selectedPerson.introPreview || "还没有人物设定"}</p>{selectedOrganizations.length > 0 && <section className="graph-organization-memberships"><h3>组织身份</h3><div>{selectedOrganizations.map(({ entry, membership }) => <p key={entry.entityId}><strong>{entry.name}</strong><small>{membership.role || "未填写身份"}</small></p>)}</div></section>}<h3>相关剧情</h3><CollapsibleList items={relatedPlots} itemKey={(plot) => plot.entityId} resetKey={selectedPerson.entityId} label={`${selectedPerson.name}的相关剧情`} className="graph-plot-links" emptyText="还没有相关剧情" renderItem={(plot) => <button onClick={() => { useUiStore.getState().selectPlot(plot.entityId); useUiStore.getState().navigate("story"); }}><strong>{plot.title}</strong><small>第 {plot.sequence} 篇</small></button>} /></aside>}{saveError && <span className="graph-save-error" role="alert">{saveError}</span>}</div>{editing && <Suspense fallback={<div className="dialog-backdrop"><section className="recovery-loading">正在准备图谱编辑器…</section></div>}><GraphEditor onClose={() => setEditing(false)} /></Suspense>}</section>;
}
