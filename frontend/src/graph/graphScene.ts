import type { Character, Entry, EntryMember, Relationship } from "../api/types";
import { effectiveGraphLineMode } from "../api/relationshipPresentation";
import { CONTENT_COLOR_PALETTE } from "../theme/contentColors";

export interface Point {
  x: number;
  y: number;
}

export interface RelationshipCurveLane {
  control: Point;
  direction: "shared" | "forward" | "reverse";
}

export interface GraphSceneNode {
  character: Character;
  point: Point;
  related: boolean;
  selected: boolean;
  organizationRings: GraphOrganizationRing[];
  organizationOverflow: number;
}

export interface GraphOrganizationRing {
  organizationId: string;
  organizationName: string;
  role: string;
  color: string;
  radiusIndex: number;
}

export interface GraphScene {
  width: number;
  height: number;
  viewport: { x: number; y: number; scale: number };
  selected: string | null;
  nodes: GraphSceneNode[];
  relationships: Relationship[];
}

export interface GraphSceneMotion {
  active: boolean;
  mode: "idle" | "active";
  time: number;
  hoveredNodeId: string | null;
}

export function quadraticPoint(from: Point, control: Point, to: Point, progress: number): Point {
  const remaining = 1 - progress;
  return {
    x: remaining * remaining * from.x + 2 * remaining * progress * control.x + progress * progress * to.x,
    y: remaining * remaining * from.y + 2 * remaining * progress * control.y + progress * progress * to.y,
  };
}

export function graphMotionProgress(time: number, offset = 0, reverse = false): number {
  const progress = ((time / 2400 + offset) % 1 + 1) % 1;
  return reverse ? 1 - progress : progress;
}

export function relationshipCurveLanes(
  from: Point,
  to: Point,
  mode: "single" | "double" = "single",
): RelationshipCurveLane[] {
  const deltaX = to.x - from.x;
  const deltaY = to.y - from.y;
  const distance = Math.max(1, Math.hypot(deltaX, deltaY));
  const perpendicular = { x: -deltaY / distance, y: deltaX / distance };
  const midpoint = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
  const bend = Math.max(24, Math.min(56, distance * .15));
  if (mode === "double") {
    return [
      { control: { x: midpoint.x + perpendicular.x * bend, y: midpoint.y + perpendicular.y * bend }, direction: "forward" },
      { control: { x: midpoint.x - perpendicular.x * bend, y: midpoint.y - perpendicular.y * bend }, direction: "reverse" },
    ];
  }
  const sharedBend = Math.max(18, Math.min(42, distance * .11));
  return [{
    control: { x: midpoint.x + perpendicular.x * sharedBend, y: midpoint.y + perpendicular.y * sharedBend },
    direction: "shared",
  }];
}

function compactGraphLabel(value: string, maximum = 18): string {
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length > maximum ? `${compact.slice(0, maximum - 1)}…` : compact;
}

function stableMotionOffset(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) hash = Math.imul(hash ^ value.charCodeAt(index), 16777619);
  return (hash >>> 0) / 4294967295;
}

export function organizationRingLabel(
  organization: Pick<Entry, "name">,
  member: Pick<EntryMember, "role">,
): string {
  const name = organization.name.trim() || "未命名组织";
  const role = member.role?.trim() || "";
  return role ? `${name} · ${role}` : name;
}

export function organizationRingColors(
  organizations: Array<Pick<Entry, "entityId" | "accent">>,
): Map<string, string> {
  const colors = new Map<string, string>();
  const used = new Set<string>();
  for (const organization of [...organizations].sort((left, right) => left.entityId.localeCompare(right.entityId))) {
    const preferred = /^#[0-9a-f]{6}$/i.test(organization.accent || "") ? organization.accent.toLowerCase() : "";
    let color = preferred && !used.has(preferred) ? preferred : "";
    const start = Math.floor(stableMotionOffset(organization.entityId) * CONTENT_COLOR_PALETTE.length);
    for (let offset = 0; !color && offset < CONTENT_COLOR_PALETTE.length; offset += 1) {
      const candidate = CONTENT_COLOR_PALETTE[(start + offset) % CONTENT_COLOR_PALETTE.length];
      if (!used.has(candidate)) color = candidate;
    }
    color ||= preferred || CONTENT_COLOR_PALETTE[start];
    colors.set(organization.entityId, color);
    used.add(color);
  }
  return colors;
}

export function graphRelationshipLabels(relation: Relationship, includeImpressions = true): string[] {
  if (effectiveGraphLineMode(relation) === "double") {
    const fallback = relation.label || relation.type || "关系";
    return [
      compactGraphLabel(includeImpressions ? (relation.fromImpression || relation.fromRole || fallback) : (relation.fromRole || relation.label || relation.type || fallback)),
      compactGraphLabel(includeImpressions ? (relation.toImpression || relation.toRole || fallback) : (relation.toRole || relation.label || relation.type || fallback)),
    ];
  }
  const label = relation.label || relation.type || (includeImpressions ? relation.fromImpression || relation.toImpression : "");
  return label ? [compactGraphLabel(label)] : [];
}

function hexRgb(value: string): [number, number, number] {
  const normalized = /^#[0-9a-f]{6}$/i.test(value) ? value : "#4f6fae";
  return [
    Number.parseInt(normalized.slice(1, 3), 16),
    Number.parseInt(normalized.slice(3, 5), 16),
    Number.parseInt(normalized.slice(5, 7), 16),
  ];
}

function rgba(color: string, alpha: number): string {
  const [red, green, blue] = hexRgb(color);
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function drawRoundedRect(context: CanvasRenderingContext2D, left: number, top: number, width: number, height: number, radius: number): void {
  const safeRadius = Math.min(radius, width / 2, height / 2);
  context.beginPath();
  context.moveTo(left + safeRadius, top);
  context.arcTo(left + width, top, left + width, top + height, safeRadius);
  context.arcTo(left + width, top + height, left, top + height, safeRadius);
  context.arcTo(left, top + height, left, top, safeRadius);
  context.arcTo(left, top, left + width, top, safeRadius);
  context.closePath();
}

function quadraticTangent(from: Point, control: Point, to: Point, progress: number): Point {
  return {
    x: 2 * (1 - progress) * (control.x - from.x) + 2 * progress * (to.x - control.x),
    y: 2 * (1 - progress) * (control.y - from.y) + 2 * progress * (to.y - control.y),
  };
}

function pointWithOverrides(point: Point, overrides?: Map<string, Point>, id?: string): Point {
  return id && overrides?.get(id) ? overrides.get(id)! : point;
}

export function createGraphScene(
  width: number,
  height: number,
  viewport: { x: number; y: number; scale: number },
  visible: Character[],
  points: Map<string, Point>,
  relationships: Relationship[],
  entries: Entry[],
  selected: string | null,
): GraphScene {
  const visibleIds = new Set(visible.map((item) => item.entityId));
  const visibleRelationships = relationships.filter((item) => visibleIds.has(item.from) && visibleIds.has(item.to));
  const organizationEntries = entries.filter((entry) => entry.type === "组织");
  const organizationColors = organizationRingColors(organizationEntries);
  const nodes = visible.flatMap((character) => {
    const point = points.get(character.entityId);
    if (!point) return [];
    const related = !selected || character.entityId === selected || visibleRelationships.some((relation) => (
      (relation.from === selected && relation.to === character.entityId)
      || (relation.to === selected && relation.from === character.entityId)
    ));
    const organizations = organizationEntries
      .filter((entry) => (entry.members || []).some((member) => member.characterId === character.entityId))
      .sort((left, right) => left.entityId.localeCompare(right.entityId));
    const organizationRings = organizations.slice(0, 3).map((organization, radiusIndex) => {
      const member = (organization.members || []).find((item) => item.characterId === character.entityId)!;
      return {
        organizationId: organization.entityId,
        organizationName: organization.name,
        role: member.role?.trim() || "",
        color: organizationColors.get(organization.entityId) || CONTENT_COLOR_PALETTE[0],
        radiusIndex,
      };
    });
    return [{
      character,
      point,
      related,
      selected: selected === character.entityId,
      organizationRings,
      organizationOverflow: Math.max(0, organizations.length - organizationRings.length),
    }];
  });
  return { width, height, viewport, selected, nodes, relationships: visibleRelationships };
}

export function graphScenePoint(
  scene: GraphScene,
  clientX: number,
  clientY: number,
  bounds: DOMRect,
  viewportOverride?: GraphScene["viewport"],
): Point {
  const viewport = viewportOverride || scene.viewport;
  return {
    x: (clientX - bounds.left - viewport.x) / viewport.scale,
    y: (clientY - bounds.top - viewport.y) / viewport.scale,
  };
}

export function hitTestGraphNode(scene: GraphScene, point: Point, radius = 36): GraphSceneNode | null {
  for (let index = scene.nodes.length - 1; index >= 0; index -= 1) {
    const node = scene.nodes[index];
    if (Math.hypot(node.point.x - point.x, node.point.y - point.y) <= radius) return node;
  }
  return null;
}

export function organizationRingGeometry(radiusIndex: number): { radius: number } {
  return { radius: 49 + radiusIndex * 17 };
}

function drawArcText(
  context: CanvasRenderingContext2D,
  text: string,
  center: Point,
  radius: number,
  color: string,
  arcOffset = 0,
): void {
  const label = compactGraphLabel(text, 22);
  if (!label) return;
  context.save();
  context.font = "600 10px system-ui, sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  const characters = [...label];
  const widths = characters.map((character) => context.measureText(character).width);
  const totalWidth = widths.reduce((sum, width) => sum + width, 0);
  const span = Math.min(2.48, Math.max(.92, totalWidth / radius * .96));
  const arcCenter = Math.PI * 1.5 + arcOffset;
  const start = arcCenter - span / 2;
  let cursor = 0;
  const glyphs = characters.map((character, index) => {
    const characterWidth = widths[index];
    const theta = start + (cursor + characterWidth / 2) / totalWidth * span;
    cursor += characterWidth;
    return {
      character,
      x: center.x + radius * Math.cos(theta),
      y: center.y + radius * Math.sin(theta),
      tangent: Math.atan2(Math.cos(theta), -Math.sin(theta)),
    };
  });
  // Draw the complete halo before any glyph fill. Drawing stroke + fill one
  // character at a time lets the next character's white stroke cover the
  // previous character on tight arcs, which looks like white debris in text.
  context.lineWidth = 4;
  context.strokeStyle = "rgba(255, 253, 247, .94)";
  for (const glyph of glyphs) {
    context.save();
    context.translate(glyph.x, glyph.y);
    context.rotate(glyph.tangent);
    context.strokeText(glyph.character, 0, 0);
    context.restore();
  }
  context.fillStyle = color;
  for (const glyph of glyphs) {
    context.save();
    context.translate(glyph.x, glyph.y);
    context.rotate(glyph.tangent);
    context.fillText(glyph.character, 0, 0);
    context.restore();
  }
  context.restore();
}

function drawOrganizationRings(
  context: CanvasRenderingContext2D,
  node: GraphSceneNode,
  point: Point,
): void {
  for (const ring of node.organizationRings) {
    const { radius } = organizationRingGeometry(ring.radiusIndex);
    const label = organizationRingLabel({ name: ring.organizationName }, { role: ring.role });
    context.save();
    context.strokeStyle = rgba(ring.color, node.related ? .78 : .18);
    context.lineWidth = node.selected ? 2.1 : 1.5;
    context.beginPath();
    context.arc(point.x, point.y, radius, 0, Math.PI * 2);
    context.stroke();
    context.restore();
    const arcOffset = [0, .34, -.34][ring.radiusIndex] || 0;
    drawArcText(context, label, point, radius, node.related ? ring.color : rgba(ring.color, .3), arcOffset);
  }
  if (node.organizationOverflow > 0) {
    context.save();
    context.font = "500 10px system-ui, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "top";
    context.fillStyle = node.related ? "rgba(76, 89, 112, .82)" : "rgba(76, 89, 112, .3)";
    context.fillText(`另外 ${node.organizationOverflow} 个组织`, point.x, point.y + 60);
    context.restore();
  }
}

function relationshipLabelProgress(from: Point, control: Point, to: Point, nodePoints: Point[], laneIndex: number): number {
  const candidates = laneIndex % 2 === 0 ? [.5, .38, .62, .25, .75] : [.5, .62, .38, .75, .25];
  const scored = candidates.map((progress) => {
    const point = quadraticPoint(from, control, to, progress);
    return {
      progress,
      clearance: Math.min(...nodePoints.map((nodePoint) => Math.hypot(point.x - nodePoint.x, point.y - nodePoint.y))),
    };
  });
  return scored.find((candidate) => candidate.clearance >= 92)?.progress
    || scored.sort((left, right) => right.clearance - left.clearance)[0].progress;
}

export function drawGraphScene(
  canvas: HTMLCanvasElement,
  scene: GraphScene,
  pointOverrides?: Map<string, Point>,
  viewportOverride?: GraphScene["viewport"],
): void {
  const context = canvas.getContext("2d");
  if (!context) return;
  const ratio = Math.min(window.devicePixelRatio || 1, 1.25);
  const pixelWidth = Math.max(1, Math.round(scene.width * ratio));
  const pixelHeight = Math.max(1, Math.round(scene.height * ratio));
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }
  const viewport = viewportOverride || scene.viewport;
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, scene.width, scene.height);
  context.save();
  context.translate(viewport.x, viewport.y);
  context.scale(viewport.scale, viewport.scale);

  const nodePoints = new Map(scene.nodes.map((node) => [
    node.character.entityId,
    pointWithOverrides(node.point, pointOverrides, node.character.entityId),
  ]));

  for (const node of scene.nodes) {
    drawOrganizationRings(context, node, nodePoints.get(node.character.entityId)!);
  }

  for (const relation of scene.relationships) {
    const from = nodePoints.get(relation.from);
    const to = nodePoints.get(relation.to);
    if (!from || !to) continue;
    const related = !scene.selected || relation.from === scene.selected || relation.to === scene.selected;
    const lineMode = effectiveGraphLineMode(relation);
    const lanes = relationshipCurveLanes(from, to, lineMode);
    const labels = graphRelationshipLabels(relation, viewport.scale >= .72);
    for (const [laneIndex, lane] of lanes.entries()) {
      context.beginPath();
      context.moveTo(from.x, from.y);
      context.quadraticCurveTo(lane.control.x, lane.control.y, to.x, to.y);
      context.strokeStyle = relation.color || "#4f6fae";
      context.globalAlpha = related ? .72 : .1;
      context.lineWidth = related ? (lineMode === "double" ? 2.2 : 2.8) : 1.4;
      context.stroke();
      if (!related) continue;
      if (lane.direction !== "shared") {
        const arrowProgress = lane.direction === "reverse" ? .36 : .64;
        const arrow = quadraticPoint(from, lane.control, to, arrowProgress);
        const tangent = quadraticTangent(from, lane.control, to, arrowProgress);
        const angle = Math.atan2(tangent.y, tangent.x) + (lane.direction === "reverse" ? Math.PI : 0);
        context.save();
        context.translate(arrow.x, arrow.y);
        context.rotate(angle);
        context.beginPath();
        context.moveTo(7, 0);
        context.lineTo(-4, -4);
        context.lineTo(-4, 4);
        context.closePath();
        context.fillStyle = relation.color || "#4f6fae";
        context.globalAlpha = .88;
        context.fill();
        context.restore();
      }
      const label = labels[laneIndex] || (lineMode === "single" ? labels[0] : "");
      if (!label) continue;
      const labelProgress = relationshipLabelProgress(from, lane.control, to, Array.from(nodePoints.values()), laneIndex);
      const labelPoint = quadraticPoint(from, lane.control, to, labelProgress);
      context.save();
      context.font = "600 11px system-ui, sans-serif";
      context.textAlign = "center";
      context.textBaseline = "middle";
      const textWidth = context.measureText(label).width;
      const paddingX = 7;
      context.globalAlpha = .9;
      context.fillStyle = "rgba(255, 253, 247, .94)";
      drawRoundedRect(context, labelPoint.x - textWidth / 2 - paddingX, labelPoint.y - 11, textWidth + paddingX * 2, 22, 11);
      context.fill();
      context.globalAlpha = .88;
      context.fillStyle = relation.color || "#4f6fae";
      context.fillText(label, labelPoint.x, labelPoint.y + .5);
      context.restore();
    }
  }

  for (const node of scene.nodes) {
    const point = nodePoints.get(node.character.entityId)!;
    const [red, green, blue] = hexRgb(node.character.color);
    const radius = node.selected ? 35 : 32;
    context.save();
    context.globalAlpha = node.related ? 1 : .2;
    context.shadowColor = node.selected ? "rgba(93, 78, 167, .3)" : "rgba(61, 91, 145, .16)";
    context.shadowBlur = node.selected ? 22 : 16;
    context.shadowOffsetY = 7;
    context.beginPath();
    context.arc(point.x, point.y, radius, 0, Math.PI * 2);
    context.fillStyle = "rgba(255, 253, 247, .98)";
    context.fill();
    context.shadowColor = "transparent";
    context.lineWidth = node.selected ? 3 : 2;
    context.strokeStyle = `rgb(${red}, ${green}, ${blue})`;
    context.stroke();
    context.beginPath();
    context.arc(point.x, point.y, 24, 0, Math.PI * 2);
    const gradient = context.createLinearGradient(point.x - 18, point.y - 20, point.x + 18, point.y + 22);
    gradient.addColorStop(0, `rgb(${Math.min(255, red + 42)}, ${Math.min(255, green + 42)}, ${Math.min(255, blue + 42)})`);
    gradient.addColorStop(.56, `rgb(${red}, ${green}, ${blue})`);
    gradient.addColorStop(1, `rgb(${Math.max(0, red - 26)}, ${Math.max(0, green - 26)}, ${Math.max(0, blue - 26)})`);
    context.fillStyle = gradient;
    context.fill();
    context.strokeStyle = "rgba(255, 255, 255, .35)";
    context.lineWidth = 1;
    context.stroke();
    context.font = "700 17px system-ui, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillStyle = "white";
    context.fillText(node.character.name.slice(0, 1), point.x, point.y + 1);
    context.font = "600 12px system-ui, sans-serif";
    context.textBaseline = "top";
    context.fillStyle = "rgba(30, 39, 58, .94)";
    context.fillText(node.character.name, point.x, point.y + radius + 6);
    context.restore();
  }
  context.restore();
  context.globalAlpha = 1;
}

export function drawGraphMotionOverlay(
  canvas: HTMLCanvasElement,
  scene: GraphScene,
  pointOverrides?: Map<string, Point>,
  viewportOverride?: GraphScene["viewport"],
  motion?: GraphSceneMotion,
): void {
  const context = canvas.getContext("2d");
  if (!context) return;
  const ratio = Math.min(window.devicePixelRatio || 1, 1.25);
  const pixelWidth = Math.max(1, Math.round(scene.width * ratio));
  const pixelHeight = Math.max(1, Math.round(scene.height * ratio));
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, scene.width, scene.height);
  if (!motion?.active) return;

  const viewport = viewportOverride || scene.viewport;
  context.save();
  context.translate(viewport.x, viewport.y);
  context.scale(viewport.scale, viewport.scale);
  const nodePoints = new Map(scene.nodes.map((node) => [
    node.character.entityId,
    pointWithOverrides(node.point, pointOverrides, node.character.entityId),
  ]));
  const relationLimit = motion.mode === "idle" ? 8 : 18;

  for (const [relationIndex, relation] of scene.relationships.entries()) {
    const from = nodePoints.get(relation.from);
    const to = nodePoints.get(relation.to);
    const related = !scene.selected || relation.from === scene.selected || relation.to === scene.selected;
    if (!from || !to || !related || viewport.scale < .65) continue;
    if (motion.hoveredNodeId) {
      if (relation.from !== motion.hoveredNodeId && relation.to !== motion.hoveredNodeId) continue;
    } else if (relationIndex >= relationLimit) continue;

    const lineMode = effectiveGraphLineMode(relation);
    const lanes = relationshipCurveLanes(from, to, lineMode);
    for (const [laneIndex, lane] of lanes.entries()) {
      const progress = graphMotionProgress(
        motion.time,
        stableMotionOffset(`${relation.entityId || `${relation.from}:${relation.to}`}:${laneIndex}`),
        lane.direction === "reverse",
      );
      const particle = quadraticPoint(from, lane.control, to, progress);
      const idleMotion = motion.mode === "idle";
      context.save();
      context.globalAlpha = idleMotion ? .62 : .92;
      context.shadowColor = relation.color || "#4f6fae";
      context.shadowBlur = idleMotion ? 3 : 8;
      context.beginPath();
      context.arc(particle.x, particle.y, idleMotion ? 2.1 : 3.1, 0, Math.PI * 2);
      context.fillStyle = relation.color || "#4f6fae";
      context.fill();
      context.shadowColor = "transparent";
      context.lineWidth = 1;
      context.strokeStyle = "rgba(255, 255, 255, .9)";
      context.stroke();
      context.restore();
    }
  }

  if (motion.mode === "active") {
    for (const node of scene.nodes) {
      if (!node.selected && motion.hoveredNodeId !== node.character.entityId) continue;
      const point = nodePoints.get(node.character.entityId)!;
      const radius = node.selected ? 35 : 32;
      const pulse = .5 + Math.sin(motion.time / 230) * .5;
      context.save();
      context.beginPath();
      context.arc(point.x, point.y, radius + 8 + pulse * 3, 0, Math.PI * 2);
      context.strokeStyle = rgba(node.character.color, .28 + pulse * .28);
      context.lineWidth = 1.5 + pulse;
      context.shadowColor = rgba(node.character.color, .45);
      context.shadowBlur = 8 + pulse * 7;
      context.stroke();
      context.restore();
    }
  }
  context.restore();
  context.globalAlpha = 1;
}
