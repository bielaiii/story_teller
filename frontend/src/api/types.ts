export type EntityKind =
  | "character"
  | "plot"
  | "entry"
  | "fragment"
  | "relationship"
  | "timeline_line"
  | "chapter";

export interface ProjectInfo {
  id: string;
  title: string;
  eyebrow: string;
  revision: number;
  extra: Record<string, unknown>;
}

export interface Character {
  entityId: string;
  id: string;
  name: string;
  aliases: string[];
  markers: string[];
  facts: Record<string, string>;
  supplements: string[];
  corePersona?: Array<{ key: string; value: string }>;
  supplementPersona?: Array<{ key: string; value: string }>;
  narrativeRole: "主角" | "配角";
  characterScope: "主线人物" | "常驻人物" | "待定角色" | "一次性角色";
  side: "主角方" | "中立" | "反派方";
  mainPlotImpact: number;
  color: string;
  gradient: string;
  group: string;
  graphVisible: boolean | null;
  revision: number;
  introPreview: string;
  intro?: string;
  references?: string[];
  extra: Record<string, unknown>;
}

export interface Plot {
  entityId: string;
  id: string;
  title: string;
  chapterId: string;
  sortKey: string;
  sequence: number;
  summary: string;
  bodyPreview: string;
  body?: string;
  status: string;
  accent: string;
  key: boolean;
  climax: boolean;
  tags: string[];
  people: string[];
  entries: string[];
  lanes: string[];
  references?: string[];
  revision: number;
  extra: Record<string, unknown>;
}

export interface Entry {
  entityId: string;
  id: string;
  name: string;
  type: string;
  subtype: string;
  area: string;
  status: string;
  accent: string;
  aliases: string[];
  tags: string[];
  people: string[];
  references?: string[];
  bodyPreview: string;
  body?: string;
  revision: number;
  extra: Record<string, unknown>;
}

export interface Fragment {
  entityId: string;
  id: string;
  title: string;
  status: string;
  accent: string;
  tags: string[];
  bodyPreview: string;
  body?: string;
  references?: string[];
  revision: number;
  extra: Record<string, unknown>;
}

export interface Relationship {
  entityId: string;
  id: string;
  from: string;
  to: string;
  fromRole: string;
  toRole: string;
  label: string;
  type: string;
  color: string;
  revision: number;
  body?: string;
  references?: string[];
}

export interface Chapter {
  entityId: string;
  id: string;
  label: string;
  sortKey: string;
  revision: number;
}

export interface TimelineLine {
  entityId: string;
  id: string;
  name: string;
  color: string;
  side: "center" | "left" | "right";
  sortKey: string;
  startPlotId: string | null;
  endPlotId: string | null;
  revision: number;
}

export interface TimelineNode {
  plotId: string;
  lineId: string;
  storySortKey: string;
}

export interface Timeline {
  mainLineId: string;
  lineSpacing: number;
  topPadding: number;
  sidePadding: number;
  pixelsPerStoryUnit: number;
  lines: TimelineLine[];
  nodes: TimelineNode[];
}

export interface GraphSettings {
  project_id?: string;
  node_spacing?: number;
  initial_jitter?: number;
  relationship_distance?: number;
  leaf_distance_extra?: number;
  center_strength?: number;
  group_strength?: number;
  leaf_strength?: number;
  extra_json?: string;
}

export interface GraphNode {
  character_id: string;
  orbit_of: string | null;
  orbit_distance: number | null;
  orbit_angle: number | null;
  strength: number | null;
  anchor_x: number | null;
  anchor_y: number | null;
}

export interface GraphDistance {
  from_character_id: string;
  to_character_id: string;
  distance: number;
  strength: number;
}

export interface GraphCluster {
  id: string;
  label: string;
  centerX: number | null;
  centerY: number | null;
  radius: number | null;
  strength: number | null;
  members: string[];
}

export interface GraphData {
  settings: GraphSettings;
  nodes: GraphNode[];
  distances: GraphDistance[];
  clusters: GraphCluster[];
}

export interface ProjectSnapshot {
  project: ProjectInfo;
  characters: Character[];
  plots: Plot[];
  entries: Entry[];
  fragments: Fragment[];
  relationships: Relationship[];
  chapters: Chapter[];
  timeline: Timeline;
  graph: GraphData;
  readonly?: boolean;
}

export interface EntityDetail<T = unknown> {
  entityId: string;
  id: string;
  kind: EntityKind;
  title: string;
  revision: number;
  deletedAt: number | null;
  purgeAt: number | null;
  data: T;
}

export interface MetaResponse {
  apiVersion: number;
  schemaVersion: number;
  writable: boolean;
  project: string;
  projectRevision: number | null;
  features: string[];
  mutationToken: string;
  error: string;
  routes: Record<string, boolean>;
}

export type DeltaBucket =
  | "characters"
  | "plots"
  | "entries"
  | "fragments"
  | "relationships"
  | "timelineLines"
  | "chapters";

export interface MutationDelta {
  ok: true;
  fromRevision: number;
  projectRevision: number;
  changed: Partial<Record<DeltaBucket, Array<Record<string, unknown>>>>;
  removed: Partial<Record<DeltaBucket, string[]>>;
  structures?: { timeline?: Timeline; graph?: GraphData };
  operation: { id: number | null; canUndo: boolean; expiresAt?: number | null };
  warnings: string[];
  export: { status: string; revision?: number };
}

export interface TrashItem {
  entityId: string;
  id: string;
  kind: EntityKind;
  title: string;
  deletedAt: number;
  expiresAt: number;
  daysRemaining: number;
  canRestore: boolean;
}

export interface OperationItem {
  id: number;
  label: string;
  action: string;
  entityKind: string;
  createdAt: number;
  expiresAt: number;
  baseRevision: number;
  resultRevision: number;
  canUndo: boolean;
  undoBlockedReason: string;
  undone: boolean;
}
