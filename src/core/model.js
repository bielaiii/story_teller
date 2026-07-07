let characters = [];
let plots = [];
let fragments = [];
let places = [];
let relationships = [];
let timelineModel = null;
let timelineRenderVersion = 0;
let timelineViewportFrame = 0;
let timelineViewportKey = "";
let graphAnimationFrame = 0;
let graphNodeEntryTimer = 0;
let graphSimulationActive = true;
let graphSimulationTicks = 0;
let graphStableFrames = 0;
let graphLastRenderTime = 0;
let timelineConfig = {};
let timelineConfigPath = "";
let timelineConfigPromise = null;
let timelineConfigLoaded = false;
let graphLayoutConfig = {};
let projectConfig = {};
let configDiagnostics = [];
let refactorCapability = null;
let refactorOperationId = "";
let refactorCapabilityProject = "";
const DATA_VERSION = "content-index-v1";
const DEFAULT_PROJECT_ID = "demo";
const PLOT_PAGE_SIZE = 9;
const FRAGMENT_PAGE_SIZE = 6;
const ENTRY_TYPES = ["组织", "势力", "地点", "物品", "事件背景", "规则"];
const AUTO_ROLE_MENTIONS = new Set(["男主", "女主"]);
const CHARACTER_SCOPE_OPTIONS = ["主线人物", "常驻人物", "待定角色", "一次性角色"];
const TEMPORARY_CHARACTER_SCOPES = new Set(["一次性角色", "临时角色", "待定角色"]);
const TIMELINE_VIEWPORT_BUFFER_Y = 520;
const TIMELINE_VIEWPORT_BUFFER_X = 220;
const TIMELINE_VIEWPORT_BUCKET = 180;
const GRAPH_EFFECT_FRAME_INTERVAL = 1000 / 30;
const GRAPH_STABLE_FRAME_TARGET = 48;
const GRAPH_MAX_SIMULATION_TICKS = 900;
const reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

async function yieldToMain() {
  if (globalThis.scheduler?.yield) {
    await globalThis.scheduler.yield();
    return;
  }
  await new Promise((resolve) => window.setTimeout(resolve, 0));
}

if ("scrollRestoration" in history) {
  history.scrollRestoration = "manual";
}

function safeProjectId(value) {
  const normalized = String(value || DEFAULT_PROJECT_ID).trim();
  return /^[a-zA-Z0-9_-]+$/.test(normalized) ? normalized : DEFAULT_PROJECT_ID;
}

function requestedProjectId() {
  const value = String(new URLSearchParams(window.location.search).get("project") || "").trim();
  return /^[a-zA-Z0-9_-]+$/.test(value) ? value : "";
}

function currentProjectId() {
  return projectConfig.id || requestedProjectId() || DEFAULT_PROJECT_ID;
}

function contentBasePath() {
  return `./content/${projectConfig.id || currentProjectId()}`;
}

function resolveContentPath(path) {
  if (!path) return "";
  if (/^(https?:|data:|\/)/.test(path)) return path;
  const cleanPath = path.replace(/^\.\//, "");
  return `${contentBasePath()}/${cleanPath}`;
}

function chapterKeys() {
  return Array.isArray(projectConfig.chapters) && projectConfig.chapters.length
    ? projectConfig.chapters
    : ["act1", "act2", "act3"];
}

function chapterLabelMap(meta = {}) {
  return chapterKeys().reduce((labels, key) => {
    const suffix = key.slice(0, 1).toUpperCase() + key.slice(1);
    labels[key] = meta[`chapter${suffix}`] || meta[`chapter_${key}`] || key;
    return labels;
  }, {});
}

function normalizeFacts(value) {
  if (!value || Array.isArray(value) || typeof value !== "object") return [];
  return Object.entries(value)
    .map(([label, content]) => ({
      label: String(label || "").trim(),
      value: Array.isArray(content)
        ? content.filter((item) => item !== null && item !== undefined).join("、")
        : String(content ?? "").trim(),
    }))
    .filter((fact) => fact.label && fact.value);
}

function normalizeMainPlotImpact(value) {
  const impact = Number(value);
  return Number.isFinite(impact) ? Math.max(0, Math.min(100, impact)) : 0;
}

function normalizeCharacterScope(value, graphVisible = true) {
  const scope = String(value || "").trim();
  if (scope) return scope;
  return graphVisible === false ? "一次性角色" : "主线人物";
}

function isMainlineCharacterScope(scope) {
  return !TEMPORARY_CHARACTER_SCOPES.has(String(scope || "").trim());
}

function isTemporaryCharacter(person) {
  return Boolean(person && TEMPORARY_CHARACTER_SCOPES.has(String(person.characterScope || "").trim()));
}

function characterScopeLabel(person) {
  return normalizeCharacterScope(person?.characterScope);
}

function characterSidePriority(side) {
  return {
    主角方: 3,
    中立: 2,
    反派方: 1,
  }[side] || 0;
}

function compareCharacterPriority(a, b) {
  return b.mainPlotImpact - a.mainPlotImpact
    || characterSidePriority(b.side) - characterSidePriority(a.side)
    || a.name.localeCompare(b.name, "zh-CN")
    || a.id.localeCompare(b.id, "zh-CN", { numeric: true });
}

function sourceFilename(path) {
  return String(path || "").split("/").pop() || "";
}

function canonicalCharacterFilename(person) {
  return person?.id && person?.name ? `${person.id}-${person.name}.md` : "";
}

function canonicalRelationshipFilename(link) {
  const from = getCharacter(link?.from);
  const to = getCharacter(link?.to);
  return from && to
    ? `${from.id}-${from.name}__${to.id}-${to.name}.md`
    : "";
}

function relationshipEndpoint(value, role = "") {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return {
      id: characterId(value.id),
      role: String(value.role || "").trim(),
    };
  }
  return {
    id: characterId(value),
    role: String(role || "").trim(),
  };
}

function relationshipEndpoints(meta) {
  const people = Array.isArray(meta.people) ? meta.people : [];
  if (people.length) return people.map((person) => relationshipEndpoint(person));
  return [
    relationshipEndpoint(meta.from, meta.fromRole),
    relationshipEndpoint(meta.to, meta.toRole),
  ].filter((endpoint) => endpoint.id || endpoint.role);
}

function normalizeRelationship(meta, sourcePath) {
  const endpoints = relationshipEndpoints(meta);
  const [fromEndpoint = {}, toEndpoint = {}] = endpoints;
  return {
    ...meta,
    endpointCount: endpoints.length,
    from: fromEndpoint.id || "",
    to: toEndpoint.id || "",
    fromRole: String(fromEndpoint.role || "").trim(),
    toRole: String(toEndpoint.role || "").trim(),
    color: safeCssColor(meta.color, "#6676c7"),
    sourcePath,
  };
}

function parseValue(value) {
  const trimmed = value.trim();
  if (trimmed.startsWith("[") && trimmed.endsWith("]")) {
    return trimmed
      .slice(1, -1)
      .split(",")
      .map((item) => parseValue(item))
      .filter((item) => item !== "");
  }
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) return Number(trimmed);
  return trimmed.replace(/^["']|["']$/g, "");
}

function characterId(value) {
  return value === undefined || value === null ? "" : String(value);
}

function characterIds(values) {
  return Array.isArray(values) ? values.map(characterId).filter(Boolean) : [];
}

function parseMarkdownFile(text) {
  const normalized = String(text || "").replace(/^\uFEFF/, "").replace(/\r\n/g, "\n");
  const match = normalized.match(/^---\n([\s\S]*?)\n---(?:\n|$)([\s\S]*)$/);
  if (!match) return { meta: {}, body: normalized.trim() };
  if (!window.jsyaml?.load) throw new Error("YAML 解析器没有正确加载");
  const compatibleFrontmatter = match[1].split("\n").map((line) => {
    const paletteField = line.match(/^(\s*palette:\s*)\[(.*#.*)\]\s*$/);
    if (paletteField) {
      const colors = paletteField[2].split(",").map((color) => {
        const trimmed = color.trim();
        return /^["']/.test(trimmed) ? trimmed : JSON.stringify(trimmed);
      });
      return `${paletteField[1]}[${colors.join(", ")}]`;
    }
    const cssField = line.match(/^(\s*(?:color|accent|gradient):\s*)(.+)$/);
    if (!cssField || !cssField[2].includes("#") || /^["']/.test(cssField[2].trim())) return line;
    return `${cssField[1]}${JSON.stringify(cssField[2].trim())}`;
  }).join("\n");
  const parsed = window.jsyaml.load(compatibleFrontmatter) || {};
  if (Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("Markdown frontmatter 必须是键值对象");
  }
  return { meta: parsed, body: match[2].trim() };
}

function buildMentionCandidates(records, termsForRecord) {
  const termCandidates = new Map();

  records.forEach((record) => {
    termsForRecord(record).forEach(({ value, priority }) => {
      const term = String(value || "").trim();
      if (term.length < 2) return;
      const candidates = termCandidates.get(term) || [];
      candidates.push({ id: record.id, term, priority });
      termCandidates.set(term, candidates);
    });
  });

  return [...termCandidates.entries()]
    .map(([term, candidates]) => {
      const highestPriority = Math.max(...candidates.map((candidate) => candidate.priority));
      const strongest = candidates.filter((candidate) => candidate.priority === highestPriority);
      const ids = [...new Set(strongest.map((candidate) => candidate.id))];
      return ids.length === 1 ? { id: ids[0], term, priority: highestPriority } : null;
    })
    .filter(Boolean)
    .sort((a, b) => b.term.length - a.term.length || b.priority - a.priority);
}

function characterMentionCandidates() {
  return buildMentionCandidates(characters, (person) => [
    { value: person.name, priority: 3 },
    ...(person.aliases || []).map((value) => ({ value, priority: 2 })),
    ...(person.markers || [])
      .filter((value) => AUTO_ROLE_MENTIONS.has(value))
      .map((value) => ({ value, priority: 1 })),
  ]);
}

function entryMentionCandidates() {
  return buildMentionCandidates(places, (place) => [
    { value: place.name, priority: 3 },
    ...(place.aliases || []).map((value) => ({ value, priority: 2 })),
  ]);
}

function mentionOccurrences(text, candidate) {
  const occurrences = [];
  const asciiTerm = /^[a-zA-Z0-9_-]+$/.test(candidate.term);
  let start = text.indexOf(candidate.term);

  while (start !== -1) {
    const end = start + candidate.term.length;
    const previous = text[start - 1] || "";
    const next = text[end] || "";
    const touchesAsciiWord = asciiTerm && (/[a-zA-Z0-9_-]/.test(previous) || /[a-zA-Z0-9_-]/.test(next));
    if (!touchesAsciiWord) occurrences.push({ ...candidate, start, end });
    start = text.indexOf(candidate.term, start + 1);
  }

  return occurrences;
}

function detectMentionedIds(text, candidates, records) {
  const occurrences = candidates
    .flatMap((candidate) => mentionOccurrences(text, candidate))
    .sort((a, b) => b.term.length - a.term.length || b.priority - a.priority || a.start - b.start);
  const claimedRanges = [];
  const detectedIds = new Set();

  occurrences.forEach((occurrence) => {
    const overlaps = claimedRanges.some((range) => occurrence.start < range.end && occurrence.end > range.start);
    if (overlaps) return;
    claimedRanges.push({ start: occurrence.start, end: occurrence.end });
    detectedIds.add(occurrence.id);
  });

  return records.filter((record) => detectedIds.has(record.id)).map((record) => record.id);
}

async function connectPlotReferences() {
  const peopleCandidates = characterMentionCandidates();
  const entryCandidates = entryMentionCandidates();
  const connectedPlots = [];
  for (let index = 0; index < plots.length; index += 1) {
    const plot = plots[index];
    const searchableText = `${plot.title || ""}\n${markdownPlainText(plot.text || "")}`;
    connectedPlots.push({
      ...plot,
      people: [...new Set([
        ...(plot.people || []),
        ...detectMentionedIds(searchableText, peopleCandidates, characters),
      ])],
      entries: [...new Set([
        ...(plot.entries || []),
        ...detectMentionedIds(searchableText, entryCandidates, places),
      ])],
    });
    if (index > 0 && index % 24 === 0) await yieldToMain();
  }
  plots = connectedPlots;
  await yieldToMain();
  characters = characters.map((person) => ({
    ...person,
    events: [...new Set([
      ...(person.events || []),
      ...plots.filter((plot) => plot.people.includes(person.id)).map((plot) => plot.id),
    ])],
  }));
  await yieldToMain();
  places = places.map((place) => ({
    ...place,
    plots: [...new Set([
      ...(place.plots || []),
      ...plots.filter((plot) => plot.entries.includes(place.id)).map((plot) => plot.id),
    ])],
  }));
}

function validateProjectConfiguration() {
  const diagnostics = [];
  const add = (level, title, detail, source) => diagnostics.push({ level, title, detail, source });
  const hasId = (records, id) => records.some((record) => String(record.id) === String(id));

  const checkDuplicateIds = (records, label) => {
    const groups = new Map();
    records.forEach((record) => {
      const id = String(record.id ?? "").trim();
      if (!id) {
        add("error", `${label}缺少 id`, `${record.name || record.title || "未命名条目"}没有可用的唯一编号。`, label);
        return;
      }
      const items = groups.get(id) || [];
      items.push(record);
      groups.set(id, items);
    });
    groups.forEach((items, id) => {
      if (items.length < 2) return;
      add(
        "error",
        `${label} id 重复：${id}`,
        items.map((item) => item.name || item.title || id).join("、"),
        label,
      );
    });
  };

  const checkAmbiguousTerms = (records, label) => {
    const groups = new Map();
    records.forEach((record) => {
      [record.name, ...(record.aliases || [])].forEach((value) => {
        const term = String(value || "").trim();
        if (!term) return;
        const items = groups.get(term) || [];
        items.push(record);
        groups.set(term, items);
      });
    });
    groups.forEach((items, term) => {
      const distinct = [...new Map(items.map((item) => [String(item.id), item])).values()];
      if (distinct.length < 2) return;
      add(
        "warning",
        `${label}称呼有歧义：${term}`,
        `同时指向${distinct.map((item) => item.name || item.id).join("、")}，自动识别时会跳过这个称呼。`,
        label,
      );
    });
  };

  checkDuplicateIds(characters, "人物");
  checkDuplicateIds(plots, "剧情");
  checkDuplicateIds(places, "设定");
  characters.forEach((person) => {
    if (person.id && !/^\d+$/.test(person.id)) {
      add("error", `人物 id 应为数字：${person.id}`, `${person.name || "未命名人物"}需要使用创建时分配的自增编号。`, "人物");
    }
  });
  checkAmbiguousTerms(characters, "人物");
  checkAmbiguousTerms(places, "设定");

  plots.forEach((plot) => {
    (plot.people || []).forEach((id) => {
      if (!hasId(characters, id)) {
        add("error", `剧情缺少人物档案：${id}`, `《${plot.title}》引用了不存在的人物 id。`, `剧情 ${plot.id}`);
      }
    });
    (plot.entries || []).forEach((id) => {
      if (!hasId(places, id)) {
        add("error", `剧情缺少设定档案：${id}`, `《${plot.title}》引用了不存在的设定 id。`, `剧情 ${plot.id}`);
      }
    });
  });

  characters.forEach((person) => {
    const expectedFilename = canonicalCharacterFilename(person);
    const currentFilename = sourceFilename(person.sourcePath);
    if (expectedFilename && currentFilename !== expectedFilename) {
      add(
        "error",
        `人物文件名与姓名不一致：${person.name}`,
        `当前为 ${currentFilename}，应改为 ${expectedFilename}。`,
        `人物 ${person.id}`,
      );
    }
    (person.events || []).forEach((id) => {
      if (!hasId(plots, id)) {
        add("error", `人物引用了不存在的剧情：${id}`, `${person.name}的 events 中存在失效编号。`, `人物 ${person.id}`);
      }
    });
  });

  places.forEach((place) => {
    (place.people || []).forEach((id) => {
      if (!hasId(characters, id)) {
        add("error", `设定缺少人物档案：${id}`, `${place.name}引用了不存在的人物 id。`, `设定 ${place.id}`);
      }
    });
    (place.plots || []).forEach((id) => {
      if (!hasId(plots, id)) {
        add("error", `设定引用了不存在的剧情：${id}`, `${place.name}的 plots 中存在失效编号。`, `设定 ${place.id}`);
      }
    });
  });

  relationships.forEach((relationship) => {
    if (relationship.endpointCount !== 2) {
      add(
        "error",
        "人物关系必须配置两个端点",
        `${relationship.label || relationship.type || "未命名关系"}的 people 必须恰好包含两个人物。`,
        "人物关系",
      );
    }
    ["from", "to"].forEach((field) => {
      if (!hasId(characters, relationship[field])) {
        add(
          "error",
          `关系缺少人物档案：${relationship[field]}`,
          `${relationship.label || relationship.type || "未命名关系"}的 ${field} 端点无效。`,
          "人物关系",
        );
      }
    });
    if (!relationship.fromRole || !relationship.toRole) {
      add(
        "warning",
        "人物关系缺少端点角色",
        `${relationship.label || relationship.type || "未命名关系"}应为双方分别填写 role。`,
        "人物关系",
      );
    }
    const expectedFilename = canonicalRelationshipFilename(relationship);
    const currentFilename = sourceFilename(relationship.sourcePath);
    if (expectedFilename && currentFilename !== expectedFilename) {
      add(
        "error",
        `关系文件名与人物姓名不一致：${relationship.label || relationship.type || "未命名关系"}`,
        `当前为 ${currentFilename}，应改为 ${expectedFilename}。`,
        "人物关系",
      );
    }
  });

  const timelineLines = new Set(Array.isArray(timelineConfig.lines) ? timelineConfig.lines : []);
  (timelineConfig.nodes || []).forEach((node) => {
    if (!hasId(plots, node.plotId)) {
      add("error", `时间线节点缺少剧情：${node.plotId}`, "节点的 plotId 没有对应剧情文件。", "时间线");
    }
    if (node.line && !timelineLines.has(node.line)) {
      add("error", `时间线缺少剧情线：${node.line}`, `剧情 ${node.plotId} 被放在未声明的剧情线上。`, "时间线");
    }
  });
  (timelineConfig.branches || []).forEach((branch) => {
    ["line", "startLine", "endLine"].forEach((field) => {
      if (branch[field] && !timelineLines.has(branch[field])) {
        add("error", `时间线缺少剧情线：${branch[field]}`, `${branch.line || "未命名分支"}的 ${field} 配置无效。`, "时间线");
      }
    });
  });

  const checkGraphMember = (id, source) => {
    if (!hasId(characters, id)) {
      add("error", `图谱缺少人物档案：${id}`, `${source}引用了不存在的人物 id。`, "图谱布局");
    }
  };
  [...(graphLayoutConfig.formations || []), ...(graphLayoutConfig.clusters || [])].forEach((group) => {
    (group.members || []).forEach((id) => checkGraphMember(id, group.label || group.id || "节点组"));
  });
  (graphLayoutConfig.distances || []).forEach((distance) => {
    checkGraphMember(distance.from, "节点距离");
    checkGraphMember(distance.to, "节点距离");
  });
  (graphLayoutConfig.nodes || []).forEach((node) => {
    checkGraphMember(node.id, "节点定位");
    if (node.orbitOf) checkGraphMember(node.orbitOf, `${node.id}的 orbitOf`);
  });

  return diagnostics.sort((a, b) => {
    const levelOrder = { error: 0, warning: 1, info: 2 };
    return levelOrder[a.level] - levelOrder[b.level] || a.source.localeCompare(b.source, "zh-CN");
  });
}

async function fetchText(path) {
  const separator = path.includes("?") ? "&" : "?";
  const response = await fetch(`${path}${separator}v=${DATA_VERSION}`);
  if (!response.ok) throw new Error(`无法加载 ${path}`);
  return response.text();
}

async function loadLocalContentIndex() {
  const response = await fetch(`/api/content-index?project=${encodeURIComponent(requestedProjectId())}`, {
    cache: "no-store",
  });
  if (!response.ok) throw new Error("本地内容扫描不可用");
  const result = await response.json();
  if (!result?.ok || !result.collections) throw new Error("本地内容扫描结果无效");
  return result;
}

async function loadStaticContentIndex() {
  const path = `${contentBasePath()}/content-index.json`;
  const response = await fetch(`${path}?v=${DATA_VERSION}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`无法加载 ${path}`);
  const result = await response.json();
  if (!result?.collections) throw new Error("静态内容索引无效");
  return result.collections;
}

function parseConfigBlocks(body, sectionName) {
  const lines = body.split("\n");
  const blocks = [];
  let inSection = false;
  let current = null;

  lines.forEach((line) => {
    const heading = line.match(/^##\s+(.+)$/);
    if (heading) {
      if (current) blocks.push(current);
      current = null;
      inSection = heading[1].trim() === sectionName;
      return;
    }
    if (!inSection || !line.trim()) return;
    const item = line.match(/^-\s+([^:]+):\s*(.+)$/);
    if (item) {
      if (current) blocks.push(current);
      current = { [item[1].trim()]: parseValue(item[2]) };
      return;
    }
    const field = line.match(/^\s+([^:]+):\s*(.+)$/);
    if (field && current) current[field[1].trim()] = parseValue(field[2]);
  });
  if (current) blocks.push(current);
  return blocks;
}

async function loadTimelineConfig(path) {
  if (!path) return {};
  const { meta, body } = parseMarkdownFile(await fetchText(path));
  return {
    ...meta,
    branches: parseConfigBlocks(body, "Branches"),
    nodes: parseConfigBlocks(body, "Nodes"),
  };
}

async function ensureTimelineConfig() {
  if (timelineConfigLoaded) return timelineConfig;
  if (!timelineConfigPromise) {
    timelineConfigPromise = loadTimelineConfig(timelineConfigPath);
  }
  timelineConfig = await timelineConfigPromise;
  timelineConfigLoaded = true;
  configDiagnostics = validateProjectConfiguration();
  return timelineConfig;
}

async function loadGraphLayoutConfig(path) {
  if (!path) return {};
  const { meta, body } = parseMarkdownFile(await fetchText(path));
  const formations = parseConfigBlocks(body, "Formations").map((formation) => ({
    ...formation,
    members: characterIds(formation.members),
    anchorNode: characterId(formation.anchorNode),
    bindMember: characterId(formation.bindMember),
    center: characterId(formation.center),
    north: characterId(formation.north),
    south: characterId(formation.south),
    west: characterId(formation.west),
    east: characterId(formation.east),
  }));
  const distances = parseConfigBlocks(body, "Distances").map((distance) => ({
    ...distance,
    from: characterId(distance.from),
    to: characterId(distance.to),
  }));
  const clusters = parseConfigBlocks(body, "Clusters").map((cluster) => ({
    ...cluster,
    members: characterIds(cluster.members),
  }));
  const nodes = parseConfigBlocks(body, "Nodes").map((node) => ({
    ...node,
    id: characterId(node.id),
    orbitOf: characterId(node.orbitOf),
  }));
  return {
    ...meta,
    formations,
    distances,
    clusters,
    nodes,
  };
}

async function loadMarkdownData() {
  projectConfig = {
    id: requestedProjectId() || DEFAULT_PROJECT_ID,
  };

  let contentIndex;
  try {
    const localIndex = await loadLocalContentIndex();
    projectConfig.id = safeProjectId(localIndex.project);
    contentIndex = localIndex.collections;
  } catch {
    contentIndex = await loadStaticContentIndex();
  }

  const manifestPath = `${contentBasePath()}/manifest.md`;
  const { meta: manifestMeta } = parseMarkdownFile(await fetchText(manifestPath));
  projectConfig = {
    ...projectConfig,
    title: manifestMeta.title || "小说剧情记录器",
    eyebrow: manifestMeta.eyebrow || "Story Teller",
    chapters: Array.isArray(manifestMeta.chapters) ? manifestMeta.chapters : ["act1", "act2", "act3"],
  };
  projectConfig.chapterLabels = chapterLabelMap(manifestMeta);

  const characterPaths = (contentIndex.characters || []).map(resolveContentPath);
  const plotPaths = (contentIndex.plots || []).map(resolveContentPath);
  const fragmentPaths = (contentIndex.fragments || []).map(resolveContentPath);
  const placePaths = (contentIndex.entries || []).map(resolveContentPath);
  const relationshipPaths = (contentIndex.relationships || []).map(resolveContentPath);
  const timelinePaths = (contentIndex.timeline || []).map(resolveContentPath);
  const graphLayoutPaths = (contentIndex.graphLayout || []).map(resolveContentPath);
  timelineConfigPath = timelinePaths[0] || "";
  timelineConfig = {};
  timelineConfigPromise = null;
  timelineConfigLoaded = false;

  const [
    loadedCharacters,
    loadedPlots,
    loadedFragments,
    loadedPlaces,
    loadedRelationships,
    loadedGraphLayoutConfig,
  ] = await Promise.all([
    Promise.all(characterPaths.map(async (path) => {
      const { meta, body } = parseMarkdownFile(await fetchText(path));
      return {
        ...meta,
        id: characterId(meta.id),
        sourcePath: path,
        intro: body,
        avatar: meta.avatar ? resolveContentPath(meta.avatar) : "",
        color: safeCssColor(meta.color, "#3f7fc1"),
        gradient: safeCssGradient(meta.gradient),
        events: Array.isArray(meta.events) ? meta.events : [],
        aliases: Array.isArray(meta.aliases) ? meta.aliases : [],
        markers: Array.isArray(meta.markers) ? meta.markers : (meta.marker ? [meta.marker] : []),
        facts: normalizeFacts(meta.facts),
        mainPlotImpact: normalizeMainPlotImpact(meta.mainPlotImpact),
        side: String(meta.side || "中立").trim(),
        characterScope: normalizeCharacterScope(meta.characterScope, meta.graphVisible),
        graphVisible: meta.graphVisible !== false,
      };
    })),
    Promise.all(plotPaths.map(async (path) => {
      const { meta, body } = parseMarkdownFile(await fetchText(path));
      return {
        ...meta,
        text: body,
        people: characterIds(meta.people),
        entries: Array.isArray(meta.entries) ? meta.entries : [],
        tags: Array.isArray(meta.tags) ? meta.tags : [],
        status: meta.status || "已接入",
        accent: safeCssColor(meta.accent, "#3f7fc1"),
      };
    })),
    Promise.all(fragmentPaths.map(async (path, index) => {
      const { meta, body } = parseMarkdownFile(await fetchText(path));
      return {
        ...meta,
        id: meta.id || `fragment-${index + 1}`,
        title: meta.title || "未命名碎片",
        text: body,
        tags: Array.isArray(meta.tags) ? meta.tags : [],
        status: meta.status || "灵感",
        accent: safeCssColor(meta.accent, "#7d6bd6"),
      };
    })),
    Promise.all(placePaths.map(async (path) => {
      const { meta, body } = parseMarkdownFile(await fetchText(path));
      return {
        ...meta,
        intro: body,
        people: characterIds(meta.people),
        plots: Array.isArray(meta.plots) ? meta.plots : [],
        aliases: Array.isArray(meta.aliases) ? meta.aliases : [],
        tags: Array.isArray(meta.tags) ? meta.tags : [],
        accent: safeCssColor(meta.accent || meta.color, "#3f7fc1"),
        type: meta.type || "设定",
        subtype: meta.subtype || "",
      };
    })),
    Promise.all(relationshipPaths.map(async (path) => {
      const { meta } = parseMarkdownFile(await fetchText(path));
      return normalizeRelationship(meta, path);
    })),
    loadGraphLayoutConfig(graphLayoutPaths[0]),
  ]);

  characters = loadedCharacters.sort(compareCharacterPriority);
  plots = loadedPlots.sort((a, b) => a.id - b.id);
  fragments = loadedFragments;
  places = loadedPlaces;
  relationships = loadedRelationships;
  graphLayoutConfig = loadedGraphLayoutConfig;
  await connectPlotReferences();
  await yieldToMain();
  configDiagnostics = validateProjectConfiguration();
}
