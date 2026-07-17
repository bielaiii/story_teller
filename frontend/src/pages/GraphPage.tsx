import { useEffect, useMemo, useRef, useState } from "react";
import type { Character, GraphData, Relationship } from "../api/types";
import { useRuntime } from "../api/runtime";
import { CollapsibleList } from "../components/CollapsibleList";
import { GraphEditor } from "../components/GraphEditor";
import { Icon } from "../components/Icon";
import { useUiStore } from "../state/ui";

export interface Point { x: number; y: number }

function graphDragInfluence(sourceId: string, characterIds: string[], relationships: Relationship[]): Map<string, number> {
  const neighbors = new Map(characterIds.map((id) => [id, [] as string[]]));
  for (const relationship of relationships) {
    if (!neighbors.has(relationship.from) || !neighbors.has(relationship.to)) continue;
    neighbors.get(relationship.from)!.push(relationship.to);
    neighbors.get(relationship.to)!.push(relationship.from);
  }
  const depth = new Map<string, number>([[sourceId, 0]]);
  const queue = [sourceId];
  while (queue.length) {
    const current = queue.shift()!;
    for (const next of neighbors.get(current) || []) {
      if (depth.has(next)) continue;
      depth.set(next, (depth.get(current) || 0) + 1);
      queue.push(next);
    }
  }
  return new Map(characterIds.map((id) => {
    if (id === sourceId) return [id, 0];
    const distance = depth.get(id);
    if (distance === 1) return [id, .48];
    if (distance === 2) return [id, .26];
    if (distance === 3) return [id, .14];
    return [id, .07];
  }));
}

export function quadraticPoint(from: Point, control: Point, to: Point, progress: number): Point {
  const remaining = 1 - progress;
  return {
    x: remaining * remaining * from.x + 2 * remaining * progress * control.x + progress * progress * to.x,
    y: remaining * remaining * from.y + 2 * remaining * progress * control.y + progress * progress * to.y,
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

export function graphLayout(
  width: number,
  height: number,
  characters: Character[],
  graph: GraphData,
  relationships: Relationship[],
): Map<string, Point> {
  const visible = characters.filter((item) => item.graphVisible !== false && !["一次性角色", "待定角色"].includes(item.characterScope));
  const visibleIds = new Set(visible.map((item) => item.entityId));
  const center = { x: width / 2, y: height / 2 };
  const spacing = finite(graph.settings.node_spacing, 116);
  const relationDistance = finite(graph.settings.relationship_distance, 250);
  const centerStrength = finite(graph.settings.center_strength, 1);
  const groupStrength = finite(graph.settings.group_strength, 1);
  const nodeRules = new Map(graph.nodes.map((item) => [item.character_id, item]));
  const clusterCoordinates = graph.clusters.flatMap((item) => [item.centerX, item.centerY]).filter((value) => value != null).map(Number);
  const anchorCoordinates = graph.nodes.flatMap((item) => [item.anchor_x, item.anchor_y]).filter((value) => value != null).map(Number);
  const looksLikePercent = (values: number[]) => values.length > 0 && values.every((value) => Number.isFinite(value) && value >= 0 && value <= 100);
  const percentCoordinates = looksLikePercent(clusterCoordinates) || (anchorCoordinates.length >= 6 && looksLikePercent(anchorCoordinates));
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
  for (const point of points.values()) {
    point.x = Math.max(64, Math.min(width - 64, point.x));
    point.y = Math.max(64, Math.min(height - 64, point.y));
  }
  return points;
}

export default function GraphPage() {
  const { snapshot, writable } = useRuntime();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef(new Map<string, HTMLButtonElement>());
  const animatedPointsRef = useRef(new Map<string, Point>());
  const motionStartedRef = useRef(performance.now());
  const panRef = useRef<{ pointerId: number; x: number; y: number; originX: number; originY: number; moved: boolean } | null>(null);
  const nodeDragRef = useRef<{ id: string; pointerId: number; startX: number; startY: number; offsetX: number; offsetY: number; lastPoint: Point; moved: boolean } | null>(null);
  const pendingDragPointRef = useRef<{ id: string; point: Point; deltaX: number; deltaY: number; influence: Map<string, number> } | null>(null);
  const dragFrameRef = useRef(0);
  const dragInfluenceRef = useRef(new Map<string, number>());
  const dragSwayRef = useRef({ startedAt: 0, updatedAt: -Infinity, energy: 0, directionX: 1, directionY: 0 });
  const followerTargetsRef = useRef(new Map<string, Point>());
  const followerPointsRef = useRef(new Map<string, Point>());
  const followerVelocityRef = useRef(new Map<string, Point>());
  const suppressClickRef = useRef<{ id: string; until: number } | null>(null);
  const focusViewportRef = useRef<{ x: number; y: number; scale: number } | null>(null);
  const [size, setSize] = useState({ width: 1000, height: 680 });
  const [editing, setEditing] = useState(false);
  const [manualPoints, setManualPoints] = useState<Map<string, Point>>(() => new Map());
  const selected = useUiStore((state) => state.selectedGraphCharacterId);
  const select = useUiStore((state) => state.selectGraphCharacter);
  const viewport = useUiStore((state) => state.graphViewport);
  const setViewport = useUiStore((state) => state.setGraphViewport);
  const layoutPoints = useMemo(
    () => graphLayout(size.width, size.height, snapshot.characters, snapshot.graph, snapshot.relationships),
    [size, snapshot.characters, snapshot.graph, snapshot.relationships],
  );
  const points = useMemo(() => {
    const merged = new Map(layoutPoints);
    for (const [id, point] of manualPoints) if (merged.has(id)) merged.set(id, point);
    return merged;
  }, [layoutPoints, manualPoints]);
  const visible = useMemo(() => snapshot.characters.filter((item) => points.has(item.entityId)), [points, snapshot.characters]);
  const motionProfiles = useMemo(() => new Map(visible.map((item) => [item.entityId, {
    phase: noise(`${item.entityId}:motion`) * Math.PI * 2,
    speed: 1450 + noise(`${item.entityId}:speed`) * 700,
    pace: 1720 + noise(`${item.entityId}:pace`) * 760,
    amplitudeX: 4 + noise(`${item.entityId}:x`) * 3,
    amplitudeY: 3 + noise(`${item.entityId}:y`) * 3,
  }])), [visible]);
  const relationships = useMemo(() => {
    const visibleIds = new Set(visible.map((item) => item.entityId));
    return snapshot.relationships.filter((item) => visibleIds.has(item.from) && visibleIds.has(item.to));
  }, [snapshot.relationships, visible]);
  const relationshipMotion = useMemo(() => new Map(relationships.map((relation) => [relation.entityId, {
    duration: 1900 + noise(`${relation.entityId}:particle-speed`) * 1200,
    phase: noise(`${relation.entityId}:particle-phase`),
  }])), [relationships]);
  const selectedPerson = snapshot.characters.find((item) => item.entityId === selected);

  useEffect(() => {
    if (!wrapRef.current) return;
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(wrapRef.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => () => {
    if (dragFrameRef.current) cancelAnimationFrame(dragFrameRef.current);
    const state = useUiStore.getState();
    state.selectGraphCharacter(null);
    if (focusViewportRef.current) state.setGraphViewport(focusViewportRef.current);
  }, []);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    let lastPaint = 0;
    const draw = (now: number) => {
      frame = 0;
      if (!reducedMotion && lastPaint && now - lastPaint < 32) {
        frame = requestAnimationFrame(draw);
        return;
      }
      lastPaint = now;
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
      if (canvas.width !== Math.round(size.width * ratio) || canvas.height !== Math.round(size.height * ratio)) {
        canvas.width = Math.round(size.width * ratio);
        canvas.height = Math.round(size.height * ratio);
      }
      const elapsed = Math.max(0, now - motionStartedRef.current);
      const initialSway = reducedMotion ? 0 : Math.exp(-elapsed / 2200) * Math.min(12, finite(snapshot.graph.settings.initial_jitter, 70) * .08);
      const dragMotion = dragSwayRef.current;
      const dragAge = Math.max(0, now - dragMotion.updatedAt);
      const dragEnergy = reducedMotion ? 0 : dragMotion.energy * Math.exp(-dragAge / 560);
      const animated = animatedPointsRef.current;
      animated.clear();
      for (const item of visible) {
        const point = points.get(item.entityId);
        const profile = motionProfiles.get(item.entityId);
        if (!point || !profile) continue;
        const followerTarget = followerTargetsRef.current.get(item.entityId);
        let physicalPoint = point;
        if (nodeDragRef.current?.id === item.entityId) {
          physicalPoint = nodeDragRef.current.lastPoint;
        } else if (followerTarget) {
          const followerPoint = followerPointsRef.current.get(item.entityId) || { ...point };
          const velocity = followerVelocityRef.current.get(item.entityId) || { x: 0, y: 0 };
          const stiffness = nodeDragRef.current ? .115 : .085;
          const damping = nodeDragRef.current ? .76 : .8;
          velocity.x = (velocity.x + (followerTarget.x - followerPoint.x) * stiffness) * damping;
          velocity.y = (velocity.y + (followerTarget.y - followerPoint.y) * stiffness) * damping;
          followerPoint.x = Math.max(64, Math.min(size.width - 64, followerPoint.x + velocity.x));
          followerPoint.y = Math.max(64, Math.min(size.height - 64, followerPoint.y + velocity.y));
          followerPointsRef.current.set(item.entityId, followerPoint);
          followerVelocityRef.current.set(item.entityId, velocity);
          physicalPoint = followerPoint;
        }
        const driftX = reducedMotion ? 0 : Math.sin(now / profile.speed + profile.phase) * profile.amplitudeX;
        const driftY = reducedMotion ? 0 : Math.cos(now / profile.pace + profile.phase) * profile.amplitudeY;
        const follow = dragInfluenceRef.current.get(item.entityId) || 0;
        const swayAmount = nodeDragRef.current?.id === item.entityId ? 0 : dragEnergy * (.45 + Math.sqrt(follow) * 2.6);
        const swayTime = Math.max(0, now - dragMotion.startedAt);
        const swayWave = Math.sin(swayTime / 260 + profile.phase * .18);
        const returnWave = Math.cos(swayTime / 420 + profile.phase * .12);
        const perpendicularX = -dragMotion.directionY;
        const perpendicularY = dragMotion.directionX;
        const initialSwayX = initialSway * Math.sin(now / 380 + profile.phase * .45);
        const initialSwayY = initialSway * Math.cos(now / 420 + profile.phase * .4);
        const swayX = perpendicularX * swayWave * swayAmount + dragMotion.directionX * returnWave * swayAmount * .22;
        const swayY = perpendicularY * swayWave * swayAmount + dragMotion.directionY * returnWave * swayAmount * .22;
        const animatedPoint = { x: physicalPoint.x + driftX + initialSwayX + swayX, y: physicalPoint.y + driftY + initialSwayY + swayY };
        animated.set(item.entityId, animatedPoint);
        const element = nodeRefs.current.get(item.entityId);
        if (element) element.style.transform = `translate(-50%, -50%) translate(${animatedPoint.x - point.x}px, ${animatedPoint.y - point.y}px)`;
      }
      const context = canvas.getContext("2d");
      if (!context) return;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, size.width, size.height);
      context.save();
      context.translate(viewport.x, viewport.y);
      context.scale(viewport.scale, viewport.scale);
      for (const relation of relationships) {
        const from = animated.get(relation.from); const to = animated.get(relation.to);
        if (!from || !to) continue;
        const related = !selected || relation.from === selected || relation.to === selected;
        const control = {
          x: (from.x + to.x) / 2 - (to.y - from.y) / 7,
          y: (from.y + to.y) / 2 + (to.x - from.x) / 9,
        };
        context.beginPath(); context.moveTo(from.x, from.y);
        context.quadraticCurveTo(control.x, control.y, to.x, to.y);
        context.strokeStyle = relation.color; context.globalAlpha = related ? .72 : .09; context.lineWidth = related ? 2.8 : 1.4; context.stroke();
        const motion = relationshipMotion.get(relation.entityId);
        const progress = reducedMotion ? .5 : (now / (motion?.duration || 2400) + (motion?.phase || 0)) % 1;
        const particle = quadraticPoint(from, control, to, progress);
        context.globalAlpha = related ? .94 : .08;
        context.beginPath(); context.arc(particle.x, particle.y, 4.2, 0, Math.PI * 2); context.fillStyle = "rgba(255,253,247,.94)"; context.fill();
        context.beginPath(); context.arc(particle.x, particle.y, 2.55, 0, Math.PI * 2); context.fillStyle = relation.color; context.fill();
      }
      context.restore(); context.globalAlpha = 1;
      if (!reducedMotion && !document.hidden) frame = requestAnimationFrame(draw);
    };
    const resume = () => {
      if (!document.hidden && !reducedMotion && !frame) frame = requestAnimationFrame(draw);
    };
    draw(performance.now());
    document.addEventListener("visibilitychange", resume);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      document.removeEventListener("visibilitychange", resume);
    };
  }, [motionProfiles, points, relationshipMotion, relationships, selected, size, snapshot.graph.settings.initial_jitter, viewport, visible]);
  const center = (id: string) => {
    const point = animatedPointsRef.current.get(id) || points.get(id); if (!point) return;
    if (!selected) focusViewportRef.current = { ...viewport };
    select(id); setViewport({ ...viewport, x: size.width / 2 - point.x * viewport.scale, y: size.height / 2 - point.y * viewport.scale });
  };
  const clearFocus = () => {
    if (!selected) return;
    select(null);
    if (focusViewportRef.current) setViewport(focusViewportRef.current);
    focusViewportRef.current = null;
  };
  const pointFromClient = (clientX: number, clientY: number) => {
    const bounds = wrapRef.current?.getBoundingClientRect();
    if (!bounds) return null;
    return {
      x: (clientX - bounds.left - viewport.x) / viewport.scale,
      y: (clientY - bounds.top - viewport.y) / viewport.scale,
    };
  };
  const commitDraggedPoint = () => {
    const pending = pendingDragPointRef.current;
    pendingDragPointRef.current = null;
    if (!pending) return;
    for (const item of visible) {
      if (item.entityId === pending.id) continue;
      const baseTarget = followerTargetsRef.current.get(item.entityId)
        || followerPointsRef.current.get(item.entityId)
        || points.get(item.entityId);
      if (!baseTarget) continue;
      const influence = pending.influence.get(item.entityId) || .07;
      followerTargetsRef.current.set(item.entityId, {
        x: Math.max(64, Math.min(size.width - 64, baseTarget.x + pending.deltaX * influence)),
        y: Math.max(64, Math.min(size.height - 64, baseTarget.y + pending.deltaY * influence)),
      });
      if (!followerPointsRef.current.has(item.entityId)) followerPointsRef.current.set(item.entityId, { ...baseTarget });
      const velocity = followerVelocityRef.current.get(item.entityId) || { x: 0, y: 0 };
      velocity.x += pending.deltaX * influence * .055;
      velocity.y += pending.deltaY * influence * .055;
      followerVelocityRef.current.set(item.entityId, velocity);
    }
    followerTargetsRef.current.delete(pending.id);
    followerPointsRef.current.delete(pending.id);
    followerVelocityRef.current.delete(pending.id);
    setManualPoints((current) => {
      const next = new Map(current);
      next.set(pending.id, pending.point);
      return next;
    });
  };
  const queueDraggedPoint = (id: string, point: Point, deltaX: number, deltaY: number) => {
    const pending = pendingDragPointRef.current;
    pendingDragPointRef.current = pending?.id === id
      ? { ...pending, point, deltaX: pending.deltaX + deltaX, deltaY: pending.deltaY + deltaY }
      : { id, point, deltaX, deltaY, influence: dragInfluenceRef.current };
    if (dragFrameRef.current) return;
    dragFrameRef.current = requestAnimationFrame(() => {
      dragFrameRef.current = 0;
      commitDraggedPoint();
    });
  };
  const flushDraggedPoint = () => {
    if (dragFrameRef.current) cancelAnimationFrame(dragFrameRef.current);
    dragFrameRef.current = 0;
    commitDraggedPoint();
  };
  const onWheel: React.WheelEventHandler = (event) => {
    event.preventDefault();
    const bounds = event.currentTarget.getBoundingClientRect();
    const pointerX = event.clientX - bounds.left; const pointerY = event.clientY - bounds.top;
    const scale = Math.max(.45, Math.min(2.4, viewport.scale * (event.deltaY > 0 ? .9 : 1.1)));
    const worldX = (pointerX - viewport.x) / viewport.scale; const worldY = (pointerY - viewport.y) / viewport.scale;
    setViewport({ scale, x: pointerX - worldX * scale, y: pointerY - worldY * scale });
  };
  const relatedPlots = selected ? snapshot.plots.filter((plot) => plot.people.includes(selected)) : [];
  return <section className="workspace-page graph-page-new"><header className="page-header graph-page-header"><div><small>Relationship Map</small><h1>人物图谱</h1><p>拖动节点调整位置，拖动空白区域平移；布局规则可以直接在网页维护。</p></div><div className="graph-header-actions">{writable && <button className="icon-button" aria-label="编辑人物图谱" title="编辑图谱布局" onClick={() => setEditing(true)}><Icon name="settings" /></button>}</div></header><div
    className="graph-canvas"
    ref={wrapRef}
    onWheel={onWheel}
    onPointerDown={(event) => {
      if ((event.target as HTMLElement).closest(".graph-node, .graph-profile-card")) return;
      event.currentTarget.setPointerCapture(event.pointerId);
      panRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, originX: viewport.x, originY: viewport.y, moved: false };
    }}
    onPointerMove={(event) => {
      const pan = panRef.current;
      if (!pan || pan.pointerId !== event.pointerId) return;
      if (Math.hypot(event.clientX - pan.x, event.clientY - pan.y) > 4) pan.moved = true;
      setViewport({ ...viewport, x: pan.originX + event.clientX - pan.x, y: pan.originY + event.clientY - pan.y });
    }}
    onPointerUp={(event) => {
      const pan = panRef.current;
      if (!pan || pan.pointerId !== event.pointerId) return;
      panRef.current = null;
      if (!pan.moved) clearFocus();
    }}
    onPointerCancel={() => { panRef.current = null; }}
  ><canvas ref={canvasRef} /><div className="graph-node-layer" style={{ transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.scale})` }}>{visible.map((item) => { const point = points.get(item.entityId)!; const related = !selected || item.entityId === selected || relationships.some((link) => (link.from === selected && link.to === item.entityId) || (link.to === selected && link.from === item.entityId)); return <button key={item.entityId} data-entity-id={item.entityId} ref={(element) => { if (element) nodeRefs.current.set(item.entityId, element); else nodeRefs.current.delete(item.entityId); }} className={`graph-node${selected === item.entityId ? " is-selected" : ""}${related ? "" : " is-muted"}`} style={{ left: point.x, top: point.y, "--node-color": item.color } as React.CSSProperties} onPointerDown={(event) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    const pointer = pointFromClient(event.clientX, event.clientY);
    const current = followerPointsRef.current.get(item.entityId) || points.get(item.entityId);
    if (!pointer || !current) return;
    dragInfluenceRef.current = graphDragInfluence(item.entityId, visible.map((person) => person.entityId), relationships);
    const dragStartedAt = performance.now();
    dragSwayRef.current = { startedAt: dragStartedAt, updatedAt: dragStartedAt, energy: .15, directionX: 1, directionY: 0 };
    nodeDragRef.current = { id: item.entityId, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, offsetX: pointer.x - current.x, offsetY: pointer.y - current.y, lastPoint: current, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  }} onPointerMove={(event) => {
    const drag = nodeDragRef.current;
    if (!drag || drag.id !== item.entityId || drag.pointerId !== event.pointerId) return;
    if (Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) > 4) drag.moved = true;
    if (!drag.moved) return;
    const pointer = pointFromClient(event.clientX, event.clientY);
    if (!pointer) return;
    const nextPoint = {
      x: Math.max(64, Math.min(size.width - 64, pointer.x - drag.offsetX)),
      y: Math.max(64, Math.min(size.height - 64, pointer.y - drag.offsetY)),
    };
    const deltaX = nextPoint.x - drag.lastPoint.x;
    const deltaY = nextPoint.y - drag.lastPoint.y;
    drag.lastPoint = nextPoint;
    const distance = Math.hypot(deltaX, deltaY);
    const previousSway = dragSwayRef.current;
    const rawDirectionX = distance ? deltaX / distance : previousSway.directionX;
    const rawDirectionY = distance ? deltaY / distance : previousSway.directionY;
    const blendedDirectionX = previousSway.directionX * .68 + rawDirectionX * .32;
    const blendedDirectionY = previousSway.directionY * .68 + rawDirectionY * .32;
    const directionLength = Math.max(.001, Math.hypot(blendedDirectionX, blendedDirectionY));
    dragSwayRef.current = {
      startedAt: previousSway.startedAt,
      updatedAt: performance.now(),
      energy: .25 + Math.min(.7, distance / 26),
      directionX: blendedDirectionX / directionLength,
      directionY: blendedDirectionY / directionLength,
    };
    queueDraggedPoint(item.entityId, nextPoint, deltaX, deltaY);
  }} onPointerUp={(event) => {
    const drag = nodeDragRef.current;
    if (!drag || drag.id !== item.entityId || drag.pointerId !== event.pointerId) return;
    flushDraggedPoint();
    nodeDragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (drag.moved) suppressClickRef.current = { id: item.entityId, until: Date.now() + 300 };
  }} onPointerCancel={(event) => {
    const drag = nodeDragRef.current;
    if (!drag || drag.id !== item.entityId || drag.pointerId !== event.pointerId) return;
    flushDraggedPoint();
    nodeDragRef.current = null;
  }} onClick={() => {
    const suppressed = suppressClickRef.current;
    if (suppressed?.id === item.entityId && Date.now() < suppressed.until) {
      suppressClickRef.current = null;
      return;
    }
    suppressClickRef.current = null;
    center(item.entityId);
  }}><span style={{ background: item.gradient || item.color }}>{item.name.slice(0, 1)}</span><strong>{item.name}</strong></button>; })}</div>{selectedPerson && <aside className="graph-profile-card"><header><span className="avatar" style={{ background: selectedPerson.gradient || selectedPerson.color }}>{selectedPerson.name.slice(0, 1)}</span><div><small>人物档案</small><h2>{selectedPerson.name}</h2><p>{selectedPerson.narrativeRole} · {selectedPerson.side}</p></div><button className="icon-button" aria-label="进入人物详情" title="进入人物详情" onClick={() => { useUiStore.getState().selectCharacter(selectedPerson.entityId); useUiStore.getState().navigate("characters"); }}><Icon name="arrow" /></button></header><p>{selectedPerson.introPreview || "还没有人物设定"}</p><h3>相关剧情</h3><CollapsibleList items={relatedPlots} itemKey={(plot) => plot.entityId} resetKey={selectedPerson.entityId} label={`${selectedPerson.name}的相关剧情`} className="graph-plot-links" emptyText="还没有相关剧情" renderItem={(plot) => <button onClick={() => { useUiStore.getState().selectPlot(plot.entityId); useUiStore.getState().navigate("story"); }}><strong>{plot.title}</strong><small>第 {plot.sequence} 篇</small></button>} /></aside>}</div>{editing && <GraphEditor onClose={() => setEditing(false)} />}</section>;
}
