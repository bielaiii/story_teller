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
const TIMELINE_VIEWPORT_BUFFER_Y = 280;
const TIMELINE_VIEWPORT_BUFFER_X = 120;
const TIMELINE_VIEWPORT_BUCKET = 140;
const GRAPH_EFFECT_FRAME_INTERVAL = 1000 / 30;
const GRAPH_STABLE_FRAME_TARGET = 72;
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

function normalizeRelationship(meta) {
  const endpoints = Array.isArray(meta.people) ? meta.people : [];
  const [fromEndpoint = {}, toEndpoint = {}] = endpoints;
  return {
    ...meta,
    endpointCount: endpoints.length,
    from: characterId(fromEndpoint.id),
    to: characterId(toEndpoint.id),
    fromRole: String(fromEndpoint.role || "").trim(),
    toRole: String(toEndpoint.role || "").trim(),
    color: safeCssColor(meta.color, "#65717d"),
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
        intro: body,
        avatar: meta.avatar ? resolveContentPath(meta.avatar) : "",
        color: safeCssColor(meta.color, "#457b9d"),
        gradient: safeCssGradient(meta.gradient),
        events: Array.isArray(meta.events) ? meta.events : [],
        aliases: Array.isArray(meta.aliases) ? meta.aliases : [],
        markers: Array.isArray(meta.markers) ? meta.markers : (meta.marker ? [meta.marker] : []),
        facts: normalizeFacts(meta.facts),
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
        accent: safeCssColor(meta.accent, "#457b9d"),
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
        accent: safeCssColor(meta.accent, "#8a5cf6"),
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
        accent: safeCssColor(meta.accent || meta.color, "#457b9d"),
        type: meta.type || "设定",
        subtype: meta.subtype || "",
      };
    })),
    Promise.all(relationshipPaths.map(async (path) => {
      const { meta } = parseMarkdownFile(await fetchText(path));
      return normalizeRelationship(meta);
    })),
    loadGraphLayoutConfig(graphLayoutPaths[0]),
  ]);

  characters = loadedCharacters;
  plots = loadedPlots.sort((a, b) => a.id - b.id);
  fragments = loadedFragments;
  places = loadedPlaces;
  relationships = loadedRelationships;
  graphLayoutConfig = loadedGraphLayoutConfig;
  await connectPlotReferences();
  await yieldToMain();
  configDiagnostics = validateProjectConfiguration();
}

const state = {
  selected: "",
  selectedCharacter: "",
  selectedPlotId: null,
  hasSelection: false,
  chapter: "all",
  plotStatus: "all",
  plotTags: [],
  fragmentTags: [],
  plotPage: 1,
  fragmentPage: 1,
  highlightPlotId: null,
  view: "graph",
  dragging: null,
  panning: null,
  suppressClickId: "",
  suppressClickUntil: 0,
  graphScale: 1,
  graphPanX: 0,
  graphPanY: 0,
  search: "",
  group: "all",
  relationType: "all",
  characterSearch: "",
  placeSearch: "",
  entryType: "all",
  entryTags: [],
  selectedPlace: "",
  globalSearch: "",
  highlightedReferenceType: "",
  highlightedReferenceId: "",
  detailReturnContext: null,
  plotReadingPositions: {},
  timelineReversed: false,
  width: 0,
  height: 0,
};

const graphWrap = document.querySelector("#graphWrap");
const graphGpuCanvas = document.querySelector("#graphGpuCanvas");
const graphFallbackCanvas = document.querySelector("#graphFallbackCanvas");
function createGraphRenderer() {
  if (!graphGpuCanvas || !graphFallbackCanvas || !window.GraphRenderer) return null;
  try {
    return new window.GraphRenderer(graphGpuCanvas, graphFallbackCanvas);
  } catch (error) {
    console.info("Graph effects unavailable; character nodes will still render.", error);
    return null;
  }
}
const graphRenderer = createGraphRenderer();
const nodeLayer = document.querySelector("#nodeLayer");
const storyEyebrow = document.querySelector("#storyEyebrow");
const storyTitle = document.querySelector("#storyTitle");
const chapterSwitch = document.querySelector("#chapterSwitch");
const plotStrip = document.querySelector("#plotStrip");
const plotPagination = document.querySelector("#plotPagination");
const statusFilter = document.querySelector("#statusFilter");
const tagFilter = document.querySelector("#tagFilter");
const fragmentBoard = document.querySelector("#fragmentBoard");
const fragmentPagination = document.querySelector("#fragmentPagination");
const fragmentTagFilter = document.querySelector("#fragmentTagFilter");
const plotPeopleRail = document.querySelector("#plotPeopleRail");
const plotDetail = document.querySelector("#plotDetail");
const eventList = document.querySelector("#eventList");
const personName = document.querySelector("#personName");
const personIntro = document.querySelector("#personIntro");
const personAvatar = document.querySelector("#selectedAvatar");
const profileFloat = document.querySelector("#profileFloat");
const graphSearch = document.querySelector("#graphSearch");
const groupFilter = document.querySelector("#groupFilter");
const relationFilter = document.querySelector("#relationFilter");
const timelineList = document.querySelector("#timelineList");
const timelineDirectionBtn = document.querySelector("#timelineDirectionBtn");
const timelineLegend = document.querySelector("#timelineLegend");
const characterList = document.querySelector("#characterList");
const characterDetail = document.querySelector("#characterDetail");
const profileDetailBtn = document.querySelector("#profileDetailBtn");
const characterSearch = document.querySelector("#characterSearch");
const placeList = document.querySelector("#placeList");
const placeDetail = document.querySelector("#placeDetail");
const placeSearch = document.querySelector("#placeSearch");
const entryTypeFilter = document.querySelector("#entryTypeFilter");
const entryTagFilter = document.querySelector("#entryTagFilter");
const globalSearch = document.querySelector("#globalSearch");
const globalSearchResults = document.querySelector("#globalSearchResults");
const diagnosticSummary = document.querySelector("#diagnosticSummary");
const diagnosticList = document.querySelector("#diagnosticList");
const diagnosticNavCount = document.querySelector("#diagnosticNavCount");
const diagnosticRefreshBtn = document.querySelector("#diagnosticRefreshBtn");
const refactorWorkspace = document.querySelector("#refactorWorkspace");
const refactorMode = document.querySelector("#refactorMode");
const refactorType = document.querySelector("#refactorType");
const refactorTarget = document.querySelector("#refactorTarget");
const refactorNewName = document.querySelector("#refactorNewName");
const refactorPreviewBtn = document.querySelector("#refactorPreviewBtn");
const refactorUndoBtn = document.querySelector("#refactorUndoBtn");
const refactorPreview = document.querySelector("#refactorPreview");
const refactorPreviewSummary = document.querySelector("#refactorPreviewSummary");
const refactorChangeList = document.querySelector("#refactorChangeList");
const refactorCancelBtn = document.querySelector("#refactorCancelBtn");
const refactorApplyBtn = document.querySelector("#refactorApplyBtn");

function initial(name) {
  return name.slice(0, 1);
}

function avatarContent(person) {
  if (person.avatar) {
    return `<img src="${escapeHtml(safeImageUrl(person.avatar))}" alt="${escapeHtml(person.name)}" loading="lazy" decoding="async" />`;
  }
  return `<span class="avatar-text">${escapeHtml(person.name)}</span>`;
}

function characterMarkers(person) {
  return Array.isArray(person?.markers) ? person.markers.filter(Boolean) : [];
}

function characterFactSearchValues(person) {
  return (person?.facts || []).flatMap((fact) => [fact.label, fact.value]);
}

function markerTone(marker) {
  const semanticTones = {
    男主: "#2563a8",
    女主: "#c95f92",
    主角: "#2a9d8f",
    主角团: "#d58a35",
    反派: "#9d3f3f",
    中立: "#65717d",
    关键人物: "#457b9d",
    家人: "#6a994e",
    家属: "#6a994e",
    对手: "#b05c48",
    支线: "#7558b7",
    支线主角: "#7558b7",
    规则: "#b77c18",
    反派群像: "#9d3f3f",
  };
  if (semanticTones[marker]) return semanticTones[marker];

  const palette = ["#457b9d", "#2a9d8f", "#c66b8c", "#b77c18", "#6a994e", "#7558b7"];
  const hash = [...String(marker)].reduce((total, character) => (
    ((total * 31) + character.codePointAt(0)) >>> 0
  ), 0);
  return palette[hash % palette.length];
}

function markerBadges(person, limit = Infinity) {
  const markers = characterMarkers(person).slice(0, limit);
  if (!markers.length) return "";
  return `
    <span class="character-markers">
      ${markers.map((marker) => `<span class="marker-badge" style="--marker:${markerTone(marker)}">${escapeHtml(marker)}</span>`).join("")}
    </span>
  `;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function safeCssColor(value, fallback = "#65717d") {
  const color = String(value || "").trim();
  if (!color || /[;{}"'<>]/.test(color) || !globalThis.CSS?.supports?.("color", color)) return fallback;
  return color;
}

function safeCssGradient(value, fallback = "linear-gradient(135deg, #8fa3b5, #52606d)") {
  const gradient = String(value || "").trim();
  if (
    !gradient
    || /[;{}"'<>]/.test(gradient)
    || !/^(?:linear|radial)-gradient\(/i.test(gradient)
    || !globalThis.CSS?.supports?.("background-image", gradient)
  ) return fallback;
  return gradient;
}

function safeImageUrl(value, resolveRelative = false) {
  const source = String(value || "").trim();
  if (!source) return "";
  if (/^data:/i.test(source)) {
    return /^data:image\/(?:png|jpe?g|gif|webp|avif);/i.test(source) ? source : "";
  }
  if (/^(?:https?:|\/|#)/i.test(source)) return source;
  return resolveRelative ? resolveContentPath(source) : source;
}

function slugifyHeading(text, index) {
  const base = String(text || "")
    .trim()
    .toLowerCase()
    .replace(/[^\p{Letter}\p{Number}]+/gu, "-")
    .replace(/^-+|-+$/g, "");
  return base || `section-${index + 1}`;
}

const markdownRenderer = window.markdownit?.({
  html: false,
  breaks: true,
  linkify: true,
  typographer: false,
});

if (markdownRenderer) {
  markdownRenderer.renderer.rules.table_open = () => '<div class="markdown-table-wrap"><table class="markdown-table">';
  markdownRenderer.renderer.rules.table_close = () => "</table></div>";
  const defaultLinkOpen = markdownRenderer.renderer.rules.link_open
    || ((tokens, index, options, environment, renderer) => renderer.renderToken(tokens, index, options));
  markdownRenderer.renderer.rules.link_open = (tokens, index, options, environment, renderer) => {
    const href = tokens[index].attrGet("href") || "";
    if (/^https?:/i.test(href)) {
      tokens[index].attrSet("target", "_blank");
      tokens[index].attrSet("rel", "noopener noreferrer");
    }
    return defaultLinkOpen(tokens, index, options, environment, renderer);
  };
}

function renderMarkdownContent(text) {
  const source = String(text || "").trim();
  if (!source) return { html: "<p>暂无正文。</p>", toc: [] };
  if (!markdownRenderer) throw new Error("Markdown 解析器没有正确加载");
  const toc = [];
  const headingCounts = new Map();
  const tokens = markdownRenderer.parse(source, {});
  tokens.forEach((token, index) => {
    (token.children || []).filter((child) => child.type === "image").forEach((image) => {
      image.attrSet("src", safeImageUrl(image.attrGet("src"), true));
      image.attrSet("loading", "lazy");
      image.attrSet("decoding", "async");
    });
    if (token.type !== "heading_open") return;
    const depth = Number(token.tag.slice(1)) || 1;
    const title = tokens[index + 1]?.content?.trim() || `章节 ${toc.length + 1}`;
    const baseId = slugifyHeading(title, toc.length);
    const count = headingCounts.get(baseId) || 0;
    headingCounts.set(baseId, count + 1);
    const id = count ? `${baseId}-${count + 1}` : baseId;
    const renderedTag = depth <= 2 ? "h3" : depth === 3 ? "h4" : "h5";
    token.tag = renderedTag;
    token.attrSet("id", id);
    const closing = tokens.slice(index + 1).find((candidate) => candidate.type === "heading_close");
    if (closing) closing.tag = renderedTag;
    toc.push({ id, title, level: depth <= 2 ? 2 : 3 });
  });
  return { html: markdownRenderer.renderer.render(tokens, markdownRenderer.options, {}), toc };
}

function renderMarkdownBody(text) {
  return renderMarkdownContent(text).html;
}

function markdownPlainText(text) {
  if (!String(text || "").trim()) return "";
  const container = document.createElement("div");
  container.innerHTML = renderMarkdownContent(text).html;
  container.querySelectorAll("br").forEach((breakElement) => breakElement.replaceWith(" "));
  const blocks = [...container.querySelectorAll("h1, h2, h3, h4, h5, h6, p, li, pre, th, td")]
    .map((element) => String(element.textContent || "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
  return (blocks.length ? blocks.join(" ") : String(container.textContent || ""))
    .replace(/\s+/g, " ")
    .trim();
}

function markdownExcerpt(text, limit = 86) {
  const plainText = markdownPlainText(text);
  if (plainText.length <= limit) return plainText;
  return `${plainText.slice(0, limit).trimEnd()}...`;
}

function plotExcerpt(plot) {
  return markdownExcerpt(plot.text);
}

function tagBadges(tags = []) {
  if (!tags.length) return "";
  return `
    <span class="tag-badges">
      ${tags.map((tag) => `<span class="tag-badge">${escapeHtml(tag)}</span>`).join("")}
    </span>
  `;
}

function statusBadge(status) {
  if (!status) return "";
  return `<span class="status-badge" data-status="${escapeHtml(status)}">${escapeHtml(status)}</span>`;
}

function plotRibbon(plot) {
  if (plot.climax) return { label: "高潮", tone: "climax" };
  if (plot.key) return { label: "关键", tone: "key" };
  if (plot.status === "草稿") return { label: "草稿", tone: "draft" };
  return null;
}

function allPlotTags() {
  return [...new Set(plots.flatMap((plot) => plot.tags || []))];
}

function allFragmentTags() {
  return [...new Set(fragments.flatMap((fragment) => fragment.tags || []))];
}

function allEntryTags() {
  return [...new Set(places.flatMap((place) => place.tags || []))];
}

function selectedTags(selected, allTags) {
  return selected.filter((tag) => allTags.includes(tag));
}

function visibleSelectedTags(selected, allTags) {
  const activeTags = selectedTags(selected, allTags);
  return !activeTags.length || activeTags.length === allTags.length ? allTags : activeTags;
}

function matchesSelectedTags(itemTags = [], selected, allTags) {
  const activeTags = selectedTags(selected, allTags);
  if (!activeTags.length || activeTags.length === allTags.length) return true;
  return itemTags.some((tag) => activeTags.includes(tag));
}

function nextSelectedTags(selected, allTags, tag) {
  const activeTags = selectedTags(selected, allTags);
  if (!activeTags.length || activeTags.length === allTags.length) return [tag];
  return activeTags.includes(tag)
    ? activeTags.filter((item) => item !== tag)
    : [...activeTags, tag];
}

function renderChipFilter({ container, label, items, selected, mode = "single", onChange }) {
  if (!container) return;
  if (!items.length) {
    container.innerHTML = "";
    return;
  }
  const activeItems = mode === "multi" ? visibleSelectedTags(selected, items) : [];
  container.innerHTML = `
    <span class="filter-label">${escapeHtml(label)}</span>
    ${mode === "single" ? `<button class="filter-chip ${selected === "all" ? "is-active" : ""}" data-value="all" type="button">全部</button>` : ""}
    ${items.map((item) => `
      <button class="filter-chip ${
        mode === "multi" ? (activeItems.includes(item) ? "is-active" : "") : (selected === item ? "is-active" : "")
      }" data-value="${escapeHtml(item)}" type="button">${escapeHtml(item)}</button>
    `).join("")}
  `;
  container.querySelectorAll("[data-value]").forEach((button) => {
    button.addEventListener("click", () => onChange(button.dataset.value, activeItems));
  });
}

function renderCardRibbon(plot) {
  const ribbon = plotRibbon(plot);
  return ribbon ? `<span class="plot-ribbon is-${ribbon.tone}">${ribbon.label}</span>` : "";
}

function storyCardClass(plot, extra = "") {
  return `${extra} ${plot.key ? "is-key" : ""} ${plot.climax ? "is-climax" : ""} ${plot.status === "草稿" ? "is-draft" : ""}`.trim();
}

function renderStoryCardContent(plot, { heading = "h4", titlePrefix = "", summary = plotExcerpt(plot), includeTags = true } = {}) {
  const safeHeading = heading === "strong" ? "strong" : "h4";
  const title = `${titlePrefix}${plot.title}`;
  return `
    ${renderCardRibbon(plot)}
    <${safeHeading}>${escapeHtml(title)}</${safeHeading}>
    <div class="plot-meta-line">
      ${plot.status === "草稿" ? "" : statusBadge(plot.status)}
      ${includeTags ? tagBadges(plot.tags) : ""}
    </div>
    <p>${escapeHtml(summary)}</p>
  `;
}

function clampPage(page, totalPages) {
  return Math.max(1, Math.min(totalPages || 1, page || 1));
}

function pagedItems(items, page, pageSize) {
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const currentPage = clampPage(page, totalPages);
  const start = (currentPage - 1) * pageSize;
  return {
    currentPage,
    totalPages,
    items: items.slice(start, start + pageSize),
  };
}

function renderPagination(container, currentPage, totalPages, onChange) {
  if (!container) return;
  if (totalPages <= 1) {
    container.innerHTML = "";
    return;
  }
  const startPage = Math.max(1, currentPage - 3);
  const endPage = Math.min(totalPages, currentPage + 3);
  const pages = Array.from({ length: endPage - startPage + 1 }, (_, index) => startPage + index);
  container.innerHTML = `
    <button class="pagination-btn" data-page="${currentPage - 1}" type="button" ${currentPage === 1 ? "disabled" : ""}>上一页</button>
    <div class="pagination-pages">
      ${pages.map((page) => `
        <button class="pagination-btn ${page === currentPage ? "is-active" : ""}" data-page="${page}" type="button">${page}</button>
      `).join("")}
    </div>
    <button class="pagination-btn" data-page="${currentPage + 1}" type="button" ${currentPage === totalPages ? "disabled" : ""}>下一页</button>
    <form class="pagination-jump">
      <span>${currentPage}/${totalPages}</span>
      <input type="number" min="1" max="${totalPages}" value="${currentPage}" aria-label="跳转页码" />
      <button class="pagination-btn" type="submit">跳转</button>
    </form>
  `;
  container.querySelectorAll(".pagination-btn[data-page]").forEach((button) => {
    button.addEventListener("click", () => onChange(clampPage(Number(button.dataset.page), totalPages)));
  });
  container.querySelector(".pagination-jump")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const value = Number(event.currentTarget.querySelector("input")?.value);
    onChange(clampPage(value, totalPages));
  });
}

function getCharacter(id) {
  return characters.find((person) => person.id === id);
}

function relationshipPerspective(link, personId) {
  const isFrom = link.from === personId;
  return {
    otherId: isFrom ? link.to : link.from,
    selfRole: isFrom ? link.fromRole : link.toRole,
    otherRole: isFrom ? link.toRole : link.fromRole,
  };
}

function characterRelationshipSearchValues(person) {
  return relationships
    .filter((link) => link.from === person?.id || link.to === person?.id)
    .flatMap((link) => {
      const perspective = relationshipPerspective(link, person.id);
      return [
        getCharacter(perspective.otherId)?.name,
        perspective.selfRole,
        perspective.otherRole,
        link.label,
        link.type,
      ];
    });
}

function getPlace(id) {
  return places.find((place) => place.id === id);
}

function entrySymbolClass(type) {
  return {
    地点: "is-location",
    物品: "is-object",
    组织: "is-organization",
    势力: "is-faction",
    事件背景: "is-event",
    规则: "is-rule",
  }[type] || "is-entry";
}

function personMatchesSearch(person) {
  if (!state.search) return true;
  const keyword = state.search.toLowerCase();
  const relatedPlots = plots.filter((plot) => plot.people.includes(person.id));
  return [
    person.name,
    person.id,
    person.group,
    person.intro,
    ...characterMarkers(person),
    ...characterFactSearchValues(person),
    ...characterRelationshipSearchValues(person),
    ...relatedPlots.map((plot) => `${plot.title} ${plot.text}`),
  ]
    .filter(Boolean)
    .some((text) => String(text).toLowerCase().includes(keyword));
}

function isVisiblePerson(person) {
  const groupMatch = state.group === "all" || person.group === state.group;
  return groupMatch && personMatchesSearch(person);
}

function isVisibleRelationship(link) {
  const a = getCharacter(link.from);
  const b = getCharacter(link.to);
  if (!a || !b) return false;
  const typeMatch = state.relationType === "all" || link.type === state.relationType;
  return typeMatch && isVisiblePerson(a) && isVisiblePerson(b);
}

function renderGraphFilters() {
  const groups = [...new Set(characters.map((person) => person.group).filter(Boolean))];
  const relationTypes = [...new Set(relationships.map((link) => link.type).filter(Boolean))];

  groupFilter.innerHTML = '<option value="all">全部分组</option>' + groups
    .map((group) => `<option value="${escapeHtml(group)}">${escapeHtml(group)}</option>`)
    .join("");
  relationFilter.innerHTML = '<option value="all">全部关系</option>' + relationTypes
    .map((type) => `<option value="${escapeHtml(type)}">${escapeHtml(type)}</option>`)
    .join("");
}

function renderProjectChrome() {
  document.title = projectConfig.title ? `${projectConfig.title}记录器` : "小说剧情记录器";
  if (storyEyebrow) storyEyebrow.textContent = projectConfig.eyebrow || "Story Teller";
  if (storyTitle) storyTitle.textContent = projectConfig.title || "小说剧情记录器";
}

function renderDiagnostics() {
  if (!diagnosticSummary || !diagnosticList) return;
  const errors = configDiagnostics.filter((item) => item.level === "error").length;
  const warnings = configDiagnostics.filter((item) => item.level === "warning").length;

  if (diagnosticNavCount) {
    diagnosticNavCount.textContent = String(configDiagnostics.length);
    diagnosticNavCount.classList.toggle("is-hidden", configDiagnostics.length === 0);
  }

  diagnosticSummary.innerHTML = `
    <div class="diagnostic-stat is-total">
      <span>检查结果</span>
      <strong>${configDiagnostics.length ? `${configDiagnostics.length} 项` : "全部正常"}</strong>
    </div>
    <div class="diagnostic-stat is-error">
      <span>需要修复</span>
      <strong>${errors}</strong>
    </div>
    <div class="diagnostic-stat is-warning">
      <span>需要确认</span>
      <strong>${warnings}</strong>
    </div>
  `;

  diagnosticList.innerHTML = configDiagnostics.length
    ? configDiagnostics.map((item) => `
        <article class="diagnostic-item is-${item.level}">
          <span class="diagnostic-level">${item.level === "error" ? "错误" : "提醒"}</span>
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <p>${escapeHtml(item.detail)}</p>
          </div>
          <small>${escapeHtml(item.source)}</small>
        </article>
      `).join("")
    : `
      <div class="diagnostic-clean">
        <strong>配置关系完整</strong>
        <p>没有发现重复编号、失效引用、歧义称呼或缺失档案。</p>
      </div>
    `;
}

function refactorRecords() {
  return refactorType?.value === "entry" ? places : characters;
}

function setRefactorBusy(busy) {
  [refactorType, refactorTarget, refactorNewName, refactorPreviewBtn, refactorUndoBtn, refactorCancelBtn, refactorApplyBtn]
    .filter(Boolean)
    .forEach((element) => {
      element.disabled = busy
        || (!refactorCapability?.writable && element !== refactorCancelBtn)
        || (element === refactorApplyBtn && !refactorOperationId);
    });
}

function closeRefactorPreview() {
  refactorOperationId = "";
  refactorPreview?.classList.add("is-hidden");
  if (refactorPreviewSummary) refactorPreviewSummary.innerHTML = "";
  if (refactorChangeList) refactorChangeList.innerHTML = "";
}

function refreshRefactorTargets() {
  if (!refactorTarget) return;
  const records = [...refactorRecords()].sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
  refactorTarget.innerHTML = records
    .map((record) => `<option value="${escapeHtml(record.id)}">${escapeHtml(record.name)}</option>`)
    .join("");
  refactorTarget.disabled = !refactorCapability?.writable || records.length === 0;
  if (refactorNewName) {
    refactorNewName.value = "";
    refactorNewName.placeholder = records.length ? `将“${records[0].name}”改为…` : "当前类型没有档案";
  }
  closeRefactorPreview();
}

function updateRefactorTargetHint() {
  const selected = refactorRecords().find((record) => String(record.id) === refactorTarget?.value);
  if (refactorNewName) {
    refactorNewName.value = "";
    refactorNewName.placeholder = selected ? `将“${selected.name}”改为…` : "输入新名称";
  }
  closeRefactorPreview();
}

function setRefactorUnavailable(message) {
  refactorCapability = null;
  refactorCapabilityProject = currentProjectId();
  if (refactorMode) {
    refactorMode.textContent = "只读模式";
    refactorMode.className = "refactor-mode is-readonly";
  }
  if (refactorPreviewSummary) {
    refactorPreviewSummary.innerHTML = `<strong>无法修改本地文件</strong><span>${escapeHtml(message)}</span>`;
  }
  refactorPreview?.classList.remove("is-hidden");
  refactorChangeList?.replaceChildren();
  refactorUndoBtn?.classList.add("is-hidden");
  setRefactorBusy(false);
}

async function refactorApi(path, body) {
  const options = body
    ? {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Story-Teller-Token": refactorCapability?.token || "",
        },
        body: JSON.stringify(body),
      }
    : {};
  const response = await fetch(path, options);
  const contentType = response.headers.get("Content-Type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error("当前是公开只读部署；请使用项目自带的本地启动命令");
  }
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error(result.error || "本地操作失败");
  return result;
}

async function initializeRefactorWorkspace(force = false) {
  if (!refactorWorkspace) return;
  const project = currentProjectId();
  if (!force && refactorCapability?.writable && refactorCapabilityProject === project) return;
  if (refactorMode) {
    refactorMode.textContent = "正在连接本地服务";
    refactorMode.className = "refactor-mode";
  }
  setRefactorBusy(true);
  try {
    const capability = await refactorApi(`/api/capabilities?project=${encodeURIComponent(project)}`);
    refactorCapability = capability;
    refactorCapabilityProject = project;
    if (refactorMode) {
      refactorMode.textContent = "本地可写";
      refactorMode.className = "refactor-mode is-writable";
    }
    refactorUndoBtn?.classList.toggle("is-hidden", !capability.canUndo);
    if (refactorUndoBtn && capability.undoLabel) {
      refactorUndoBtn.textContent = `撤销：${capability.undoLabel}`;
    }
    refreshRefactorTargets();
    setRefactorBusy(false);
  } catch (error) {
    setRefactorUnavailable(error.message);
  }
}

function renderRefactorError(message) {
  if (refactorPreviewSummary) {
    refactorPreviewSummary.innerHTML = `<strong>没有应用任何修改</strong><span>${escapeHtml(message)}</span>`;
  }
  refactorChangeList?.replaceChildren();
  refactorPreview?.classList.remove("is-hidden");
}

async function previewRefactor() {
  const newName = refactorNewName?.value.trim() || "";
  if (!newName) {
    renderRefactorError("请先输入新名称");
    refactorNewName?.focus();
    return;
  }
  setRefactorBusy(true);
  try {
    const result = await refactorApi("/api/refactor/preview", {
      project: currentProjectId(),
      type: refactorType.value,
      id: refactorTarget.value,
      newName,
    });
    refactorOperationId = result.operationId;
    refactorPreviewSummary.innerHTML = `
      <strong>${escapeHtml(result.oldName)} → ${escapeHtml(result.newName)}</strong>
      <span>${result.fileCount} 个文件，${result.matchCount} 处修改</span>
    `;
    refactorChangeList.innerHTML = result.samples.length
      ? result.samples.map((sample) => `
          <article class="refactor-change">
            <small>${escapeHtml(sample.file)} · 第 ${sample.line} 行</small>
            <del>${escapeHtml(sample.before)}</del>
            <ins>${escapeHtml(sample.after)}</ins>
          </article>
        `).join("")
      : '<p class="refactor-no-change">没有找到需要修改的引用。</p>';
    refactorPreview.classList.remove("is-hidden");
  } catch (error) {
    refactorOperationId = "";
    renderRefactorError(error.message);
  } finally {
    setRefactorBusy(false);
  }
}

async function applyRefactor() {
  if (!refactorOperationId) return;
  setRefactorBusy(true);
  try {
    await refactorApi("/api/refactor/apply", { operationId: refactorOperationId });
    window.location.reload();
  } catch (error) {
    renderRefactorError(error.message);
    setRefactorBusy(false);
  }
}

async function undoRefactor() {
  setRefactorBusy(true);
  try {
    await refactorApi("/api/refactor/undo", { project: currentProjectId() });
    window.location.reload();
  } catch (error) {
    renderRefactorError(error.message);
    setRefactorBusy(false);
  }
}

async function requestDiagnosticsRender() {
  if (!timelineConfigLoaded && diagnosticList) {
    diagnosticList.innerHTML = '<div class="diagnostic-clean"><strong>正在检查配置</strong><p>时间线配置会在这里按需加载。</p></div>';
  }
  try {
    await Promise.all([ensureTimelineConfig(), initializeRefactorWorkspace()]);
    if (state.view === "diagnostics") renderDiagnostics();
  } catch (error) {
    if (diagnosticList) {
      diagnosticList.innerHTML = `<div class="diagnostic-clean"><strong>配置检查失败</strong><p>${escapeHtml(error.message)}</p></div>`;
    }
  }
}

function renderChapterSwitch() {
  if (!chapterSwitch) return;
  const chapterButtons = chapterKeys().map((chapter) => `
    <button class="chapter-btn ${state.chapter === chapter ? "is-active" : ""}" data-chapter="${escapeHtml(chapter)}" type="button">
      ${escapeHtml(chapterName(chapter))}
    </button>
  `).join("");
  chapterSwitch.innerHTML = `
    <button class="chapter-btn ${state.chapter === "all" ? "is-active" : ""}" data-chapter="all" type="button">全部</button>
    ${chapterButtons}
    <button class="chapter-btn ${state.chapter === "key" ? "is-active" : ""}" data-chapter="key" type="button">关键剧情</button>
    <button class="chapter-btn ${state.chapter === "climax" ? "is-active" : ""}" data-chapter="climax" type="button">高潮剧情</button>
  `;
  chapterSwitch.querySelectorAll(".chapter-btn").forEach((button) => {
    button.addEventListener("click", () => {
      setChapterFilter(button.dataset.chapter);
      state.plotPage = 1;
      renderStoryFilters();
      renderPlots();
    });
  });
}

function renderStoryFilters() {
  const statuses = [...new Set(plots.map((plot) => plot.status).filter(Boolean))];
  renderChipFilter({
    container: statusFilter,
    label: "状态",
    items: statuses,
    selected: state.plotStatus,
    onChange: (value) => {
      state.plotStatus = value;
      state.plotPage = 1;
      renderStoryFilters();
      renderPlots();
    },
  });

  const tags = allPlotTags();
  renderChipFilter({
    container: tagFilter,
    label: "标签",
    items: tags,
    selected: state.plotTags,
    mode: "multi",
    onChange: (value) => {
      state.plotTags = nextSelectedTags(state.plotTags, tags, value);
      state.plotPage = 1;
      renderStoryFilters();
      renderPlots();
    },
  });
}

function renderPlots() {
  const visible = plots.filter((plot) => {
    const chapterMatch = state.chapter === "all"
      || (state.chapter === "key" && plot.key)
      || (state.chapter === "climax" && plot.climax)
      || plot.chapter === state.chapter;
    const statusMatch = state.plotStatus === "all" || plot.status === state.plotStatus;
    const tagMatch = matchesSelectedTags(plot.tags || [], state.plotTags, allPlotTags());
    return chapterMatch && statusMatch && tagMatch;
  });
  const page = pagedItems(visible, state.plotPage, PLOT_PAGE_SIZE);
  state.plotPage = page.currentPage;
  plotStrip.innerHTML = page.items.length ? page.items
    .map((plot, index) => `
      <button class="${storyCardClass(plot, `plot-card ${state.highlightPlotId === plot.id ? "is-highlighted" : ""}`)}" data-plot-id="${escapeHtml(plot.id)}" type="button" style="--accent:${escapeHtml(plot.accent)}; animation-delay:${index * 55}ms">
        <div class="plot-index">${escapeHtml(plot.id)}</div>
        <div>${renderStoryCardContent(plot)}</div>
      </button>
    `)
    .join("") : '<p class="empty-state">没有匹配的剧情。</p>';
  document.querySelectorAll(".plot-card").forEach((card) => {
    card.addEventListener("click", () => openPlotDetail(Number(card.dataset.plotId)));
  });
  renderPagination(plotPagination, page.currentPage, page.totalPages, (nextPage) => {
    state.plotPage = nextPage;
    renderPlots();
  });
}

function renderFragmentFilters() {
  if (!fragmentTagFilter) return;
  const tags = allFragmentTags();
  renderChipFilter({
    container: fragmentTagFilter,
    label: "标签",
    items: tags,
    selected: state.fragmentTags,
    mode: "multi",
    onChange: (value) => {
      state.fragmentTags = nextSelectedTags(state.fragmentTags, tags, value);
      state.fragmentPage = 1;
      renderFragmentFilters();
      renderFragments();
    },
  });
}

function renderFragments() {
  if (!fragmentBoard) return;
  const visible = fragments.filter((fragment) => (
    matchesSelectedTags(fragment.tags || [], state.fragmentTags, allFragmentTags())
  ));
  const page = pagedItems(visible, state.fragmentPage, FRAGMENT_PAGE_SIZE);
  state.fragmentPage = page.currentPage;
  fragmentBoard.innerHTML = page.items.length ? page.items.map((fragment, index) => `
    <article class="fragment-card" id="fragment-${escapeHtml(fragment.id)}" style="--accent:${escapeHtml(fragment.accent)}; animation-delay:${index * 55}ms">
      <div class="fragment-head">
        <span class="status-badge">${escapeHtml(fragment.status || "灵感")}</span>
        ${tagBadges(fragment.tags)}
      </div>
      <h3>${escapeHtml(fragment.title)}</h3>
      <div class="fragment-body">${renderMarkdownBody(fragment.text)}</div>
    </article>
  `).join("") : '<p class="empty-state">没有匹配的碎片。</p>';
  renderPagination(fragmentPagination, page.currentPage, page.totalPages, (nextPage) => {
    state.fragmentPage = nextPage;
    renderFragments();
  });
}

function plotBadges(plot) {
  return `
    ${plot.key ? '<span class="plot-badge is-key">关键剧情</span>' : ""}
    ${plot.climax ? '<span class="plot-badge is-climax">高潮剧情</span>' : ""}
  `;
}

function chapterName(chapter) {
  return projectConfig.chapterLabels?.[chapter] || chapter || "未分幕";
}

function plotNavigation(plot) {
  const scopedPlots = chapterKeys().includes(state.chapter)
    ? plots.filter((item) => item.chapter === state.chapter)
    : plots;
  const currentIndex = scopedPlots.findIndex((item) => item.id === plot.id);
  return {
    prev: currentIndex > 0 ? scopedPlots[currentIndex - 1] : null,
    next: currentIndex >= 0 && currentIndex < scopedPlots.length - 1 ? scopedPlots[currentIndex + 1] : null,
  };
}

function connectorGeometry(connector) {
  const span = Math.abs(connector.y2 - connector.y1);
  const r = Math.min(connector.radius, Math.max(8, span / 5));
  const topY = Math.min(connector.y1, connector.y2);
  const bottomY = Math.max(connector.y1, connector.y2);
  const topRailY = topY + r * 1.45;
  const bottomRailY = bottomY - r * 1.45;
  return {
    radius: r,
    topY,
    bottomY,
    topRailY,
    bottomRailY,
    branchTopY: topRailY + r,
    branchBottomY: bottomRailY - r,
  };
}

function asTimelineRatio(value, fallback = 0) {
  if (value === undefined || value === null || value === "") return fallback;
  const raw = String(value).trim();
  if (raw === "start") return 0;
  if (raw === "end") return 1;
  const numeric = raw.endsWith("%") ? Number(raw.slice(0, -1)) / 100 : Number(raw);
  if (!Number.isFinite(numeric)) return fallback;
  const ratio = numeric > 1 ? numeric / 100 : numeric;
  return Math.max(0, Math.min(1, ratio));
}

function timelineVisualRatio(value, fallback = 0) {
  const ratio = asTimelineRatio(value, fallback);
  return state.timelineReversed ? 1 - ratio : ratio;
}

function timelinePercentLabel(ratio) {
  return `${Math.round(ratio * 100)}%`;
}

function timelineRangesOverlap(first, second) {
  return first.start < second.end && second.start < first.end;
}

function timelineDensityLength(nodeConfigs, minimumGap = 24) {
  const positionsByLine = new Map();
  nodeConfigs.forEach((node) => {
    if (!node.line || node.linePosition === undefined) return;
    if (!positionsByLine.has(node.line)) positionsByLine.set(node.line, []);
    positionsByLine.get(node.line).push(asTimelineRatio(node.linePosition));
  });

  let requiredLength = 0;
  positionsByLine.forEach((positions) => {
    positions.sort((a, b) => a - b);
    for (let index = 1; index < positions.length; index += 1) {
      const gap = positions[index] - positions[index - 1];
      if (gap > 0.002) requiredLength = Math.max(requiredLength, minimumGap / gap);
    }
  });
  return Math.min(12000, Math.ceil(requiredLength));
}

function generatedTimelineColor(index) {
  const hues = [206, 329, 151, 36, 257, 184, 4, 96, 284, 222];
  const hue = hues[index % hues.length];
  const lightness = index >= hues.length ? 42 + ((index - hues.length) % 3) * 4 : 46;
  return `hsl(${hue} 58% ${lightness}%)`;
}

function assignTimelineColors(lines, branchConfigs, connectors, palette, mainLineName) {
  const colorMap = new Map();
  const basePalette = palette.length
    ? palette.map((color, index) => safeCssColor(color, generatedTimelineColor(index)))
    : ["#1d9bf0", "#c95f92", "#3f9b72", "#d58a35", "#7868c7", "#2d9ca0", "#c9685f", "#71869d"];
  colorMap.set(mainLineName, basePalette[0] || "#1d9bf0");
  const branchConfigByLine = new Map(branchConfigs.map((item) => [item.line, item]));
  const connectorRanges = connectors
    .map((connector) => ({
      lane: connector.lane,
      start: Math.min(connector.y1, connector.y2),
      end: Math.max(connector.y1, connector.y2),
    }))
    .sort((a, b) => lines.indexOf(a.lane) - lines.indexOf(b.lane));

  connectorRanges.forEach((range) => {
    const branchConfig = branchConfigByLine.get(range.lane);
    if (branchConfig?.color) {
      colorMap.set(range.lane, safeCssColor(branchConfig.color, generatedTimelineColor(colorMap.size)));
      return;
    }
    const usedColors = new Set(connectorRanges
      .filter((item) => item.lane !== range.lane && colorMap.has(item.lane) && timelineRangesOverlap(range, item))
      .map((item) => colorMap.get(item.lane)));
    let color = basePalette.find((item, index) => index > 0 && !usedColors.has(item));
    let colorIndex = 0;
    while (!color) {
      const generated = generatedTimelineColor(colorIndex);
      if (!usedColors.has(generated)) color = generated;
      colorIndex += 1;
    }
    colorMap.set(range.lane, color);
  });

  lines.forEach((lane, index) => {
    if (!colorMap.has(lane)) colorMap.set(lane, basePalette[index % basePalette.length] || generatedTimelineColor(index));
  });
  return colorMap;
}

function timelineNodeConfigFor(plotId) {
  return (timelineConfig.nodes || []).find((item) => Number(item.plotId) === Number(plotId)) || {};
}

function timelinePlotTitle(plot) {
  return timelineNodeConfigFor(plot.id).displayTitle || plot.title;
}

function timelinePlotSummary(plot) {
  return timelineNodeConfigFor(plot.id).displaySummary || plot.text;
}

function timelinePlotChapter(plot) {
  return timelineNodeConfigFor(plot.id).displayChapter || chapterName(plot.chapter);
}

function timelinePlotPriority(plot, nodeConfig = {}) {
  if (nodeConfig.showSummary || nodeConfig.featured) return 6;
  if (plot.climax) return 5;
  if (plot.key) return 4;
  if (plot.status === "已接入") return 2;
  return 1;
}

function selectTimelineSummaryItems(items, lanes, mainLineName) {
  if (!items.length) return [];
  const selected = new Map();
  const add = (item) => {
    if (item) selected.set(Number(item.plot.id), item);
  };

  items
    .filter((item) => item.priority >= 4)
    .forEach(add);
  add(items[0]);
  add(items[items.length - 1]);

  lanes.forEach((lane) => {
    const laneItems = items.filter((item) => item.position.lane === lane);
    if (!laneItems.length) return;
    const preferred = laneItems
      .slice()
      .sort((a, b) => b.priority - a.priority || Math.abs(0.5 - a.position.storyRatio) - Math.abs(0.5 - b.position.storyRatio))[0];
    if (lane !== mainLineName || preferred.priority >= 4) add(preferred);
  });

  const targetCount = Math.min(12, Math.max(7, Math.ceil(items.length / 8)));
  const step = Math.max(1, Math.floor(items.length / targetCount));
  for (let index = Math.floor(step / 2); selected.size < targetCount && index < items.length; index += step) {
    add(items[index]);
  }

  const minGap = items.length > 36 ? 118 : 96;
  const ranked = [...selected.values()].sort((a, b) => b.priority - a.priority || a.position.y - b.position.y);
  const filtered = [];
  ranked.forEach((item) => {
    const near = filtered.find((picked) => picked.side === item.side && Math.abs(picked.position.y - item.position.y) < minGap);
    if (!near) filtered.push(item);
  });

  return filtered.sort((a, b) => a.position.y - b.position.y);
}

function updateTimelineDirectionButton() {
  if (!timelineDirectionBtn) return;
  timelineDirectionBtn.textContent = state.timelineReversed ? "顶端：结尾" : "顶端：开始";
  timelineDirectionBtn.setAttribute("aria-pressed", String(state.timelineReversed));
}

function scrollPageToTop() {
  window.requestAnimationFrame(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    timelineList?.scrollTo({ top: 0, left: 0, behavior: "auto" });
  });
}

function resolvedBranchTrack(branchConfig, occupiedTracks) {
  const side = branchConfig.side === "left" ? "left" : "right";
  let track = Math.max(1, Number(branchConfig.trackFromMain ?? branchConfig.distance ?? 1) || 1);
  const key = () => `${side}:${track}`;
  while (occupiedTracks.has(key())) track += 1;
  occupiedTracks.add(key());
  return track;
}

async function renderTimeline() {
  const renderVersion = ++timelineRenderVersion;
  if (!timelineConfigLoaded) {
    timelineList.innerHTML = '<div class="timeline-loading">正在按需加载时间线配置…</div>';
    await ensureTimelineConfig();
    if (renderVersion !== timelineRenderVersion || state.view !== "timeline") return;
  }
  updateTimelineDirectionButton();
  if (
    timelineModel
    && timelineModel.reversed === state.timelineReversed
    && document.querySelector(".timeline-board")
  ) {
    scheduleTimelineViewportRender(true);
    return;
  }
  timelineList.innerHTML = '<div class="timeline-loading">正在整理当前可见的剧情线…</div>';
  await yieldToMain();
  if (renderVersion !== timelineRenderVersion || state.view !== "timeline") return;

  const mainLineName = timelineConfig.mainLine || "主线";
  const lines = Array.isArray(timelineConfig.lines) && timelineConfig.lines.length
    ? timelineConfig.lines
    : [mainLineName];
  const branchConfigs = timelineConfig.branches || [];
  const lineSpacing = Math.max(72, Number(timelineConfig.lineSpacing || 72) || 72);
  const topPadding = timelineConfig.topPadding || 54;
  const sidePadding = timelineConfig.sidePadding || 34;
  const palette = Array.isArray(timelineConfig.palette) && timelineConfig.palette.length
    ? timelineConfig.palette.map((color, index) => safeCssColor(color, generatedTimelineColor(index)))
    : ["#1d9bf0", "#c95f92", "#3f9b72", "#d58a35", "#7868c7", "#2d9ca0", "#c9685f", "#71869d"];
  const branchConfigByLine = new Map(branchConfigs.map((item) => [item.line, item]));
  const nodeConfigByPlot = new Map((timelineConfig.nodes || []).map((item) => [Number(item.plotId), item]));
  let timelineColorMap = new Map();
  const baseLineColor = (line) => palette[Math.max(0, lines.indexOf(line)) % palette.length];
  const lineColor = (line) => safeCssColor(timelineColorMap.get(line) || baseLineColor(line), "#65717d");
  const occupiedTracks = new Set();
  const branchTrackByLine = new Map(branchConfigs.map((branchConfig) => [
    branchConfig.line,
    resolvedBranchTrack(branchConfig, occupiedTracks),
  ]));
  const lineTrack = (branchConfig) => branchTrackByLine.get(branchConfig?.line) || 1;
  const storyUnitPixels = Math.max(560, Number(timelineConfig.pixelsPerStoryUnit || 860) || 860);
  const branchDisplayLength = (branchConfig) => {
    if (branchConfig?.displayLength !== undefined) return Math.max(260, Number(branchConfig.displayLength) || 420);
    if (branchConfig?.visualLength !== undefined) return Math.max(260, Number(branchConfig.visualLength) * storyUnitPixels || 420);
    return 460;
  };
  const nodeGap = Math.max(40, Number(timelineConfig.nodeGap || 56) || 56);
  const mainDisplayLength = Math.max(680, timelineDensityLength(timelineConfig.nodes || []), ...branchConfigs
    .map((branchConfig) => branchDisplayLength(branchConfig) * 1.8), ...branchConfigs
    .filter((branchConfig) => (branchConfig.startLine || mainLineName) === mainLineName && (branchConfig.endLine || mainLineName) === mainLineName)
    .map((branchConfig) => {
      const start = asTimelineRatio(branchConfig.startPosition, 0);
      const end = asTimelineRatio(branchConfig.endPosition, 1);
      const span = Math.max(0.08, Math.abs(end - start));
      return (branchDisplayLength(branchConfig) + 140) / span;
    }), plots.length * nodeGap);
  const configuredOffsets = branchConfigs.map((branchConfig) => ({
    side: branchConfig.side === "left" ? "left" : "right",
    offset: lineTrack(branchConfig),
  }));
  const maxLeftOffset = Math.max(0, ...configuredOffsets.filter((item) => item.side === "left").map((item) => item.offset));
  const maxRightOffset = Math.max(0, ...configuredOffsets.filter((item) => item.side !== "left").map((item) => item.offset));
  const mainX = sidePadding + maxLeftOffset * lineSpacing + lineSpacing / 2;
  const graphWidth = (maxLeftOffset + maxRightOffset + 1) * lineSpacing + sidePadding * 2;
  const lineX = (line) => {
    if (line === mainLineName) return mainX;
    const branchConfig = branchConfigByLine.get(line);
    if (branchConfig) {
      const direction = branchConfig.side === "left" ? -1 : 1;
      return mainX + direction * lineTrack(branchConfig) * lineSpacing;
    }
    return mainX;
  };
  const graphHeight = topPadding * 2 + mainDisplayLength;
  const fallbackPlotPosition = (index) => plots.length <= 1 ? 0 : index / (plots.length - 1);
  const plotY = (index) => topPadding + timelineVisualRatio(fallbackPlotPosition(index), 0) * mainDisplayLength;
  const plotLaneNames = (plot) => plot.lanes || [plot.lane || mainLineName];
  const connectorByLane = new Map();
  const resolvingLanes = new Set();
  const mainLine = {
    lane: mainLineName,
    color: lineColor(mainLineName),
    x: lineX(mainLineName),
    y1: topPadding,
    y2: topPadding + mainDisplayLength,
  };

  const resolveConnector = (lane) => {
    if (connectorByLane.has(lane)) return connectorByLane.get(lane);
    const branchConfig = branchConfigByLine.get(lane);
    if (!branchConfig || resolvingLanes.has(lane)) return null;
    resolvingLanes.add(lane);

    const resolveLine = (lineLane) => {
      if (lineLane === mainLineName) return mainLine;
      const connector = resolveConnector(lineLane);
      if (!connector) {
        return {
          lane: lineLane,
          color: lineColor(lineLane),
          x: lineX(lineLane),
          y1: topPadding,
          y2: topPadding + mainDisplayLength,
        };
      }
      const geometry = connectorGeometry(connector);
      const branchLineConfig = branchConfigByLine.get(lineLane);
      return {
        lane: lineLane,
        color: lineColor(lineLane),
        x: connector.x2,
        y1: geometry.branchTopY,
        y2: geometry.branchBottomY,
      };
    };

    const resolvePoint = (lineLane, position, fallbackRatio) => {
      const line = resolveLine(lineLane);
      const ratio = timelineVisualRatio(position, fallbackRatio);
      return {
        x: line.x,
        y: line.y1 + (line.y2 - line.y1) * ratio,
        color: line.color,
        lane: lineLane,
      };
    };

    const sourceLane = branchConfig.startLine || mainLineName;
    const targetLane = branchConfig.endLine || mainLineName;
    const sourcePoint = resolvePoint(sourceLane, branchConfig.startPosition, 0);
    const targetPoint = resolvePoint(targetLane, branchConfig.endPosition, 1);
    const branchX = lineX(lane);
    const radius = branchConfig.radius || Math.min(28, Math.max(14, Math.max(Math.abs(branchX - sourcePoint.x), Math.abs(branchX - targetPoint.x)) * 0.28));
    const connector = {
      lane,
      sourceLane,
      targetLane,
      x1: sourcePoint.x,
      x2: branchX,
      x3: targetPoint.x,
      y1: sourcePoint.y,
      y2: targetPoint.y,
      radius,
      firstColor: sourcePoint.color,
      lastColor: lineColor(lane),
      targetColor: targetPoint.color,
    };
    connectorByLane.set(lane, connector);
    resolvingLanes.delete(lane);
    return connector;
  };

  const connectorLines = branchConfigs
    .map((branchConfig) => resolveConnector(branchConfig.line))
    .filter(Boolean);
  await yieldToMain();
  if (renderVersion !== timelineRenderVersion || state.view !== "timeline") return;
  timelineColorMap = assignTimelineColors(lines, branchConfigs, connectorLines, palette, mainLineName);
  mainLine.color = lineColor(mainLineName);
  connectorLines.forEach((connector) => {
    connector.firstColor = lineColor(connector.sourceLane);
    connector.lastColor = lineColor(connector.lane);
    connector.targetColor = lineColor(connector.targetLane);
  });

  const laneLines = lines.map((lane) => {
    if (lane === mainLineName) return mainLine;
    const connector = connectorByLane.get(lane);
    if (connector) {
      const geometry = connectorGeometry(connector);
      return {
        lane,
        color: lineColor(lane),
        x: connector.x2,
        y1: geometry.branchTopY,
        y2: geometry.branchBottomY,
      };
    }
    return {
      lane,
      color: lineColor(lane),
      x: lineX(lane),
      y1: topPadding,
      y2: topPadding + mainDisplayLength,
    };
  });

  const timelineNodePosition = (plot, index) => {
    const nodeConfig = nodeConfigByPlot.get(Number(plot.id));
    const primaryLane = nodeConfig?.line || plotLaneNames(plot)[0] || mainLineName;
    const fallbackRatio = plots.length <= 1 ? 0 : index / (plots.length - 1);
    const storyRatio = asTimelineRatio(nodeConfig?.linePosition, primaryLane === mainLineName ? fallbackRatio : 0.5);
    if (primaryLane === mainLineName) {
      return {
        x: lineX(mainLineName),
        y: nodeConfig?.linePosition !== undefined
          ? mainLine.y1 + (mainLine.y2 - mainLine.y1) * timelineVisualRatio(nodeConfig.linePosition)
          : plotY(index),
        lane: primaryLane,
        storyRatio,
      };
    }
    const connector = connectorLines.find((item) => item.lane === primaryLane);
    if (!connector) return { x: lineX(primaryLane), y: plotY(index), lane: primaryLane, storyRatio };
    const geometry = connectorGeometry(connector);
    const progress = timelineVisualRatio(nodeConfig?.linePosition, 0.5);
    return {
      x: connector.x2,
      y: geometry.branchTopY + (geometry.branchBottomY - geometry.branchTopY) * progress,
      lane: primaryLane,
      storyRatio,
    };
  };

  const positionedPlots = plots.map((plot, index) => {
    const nodeConfig = nodeConfigByPlot.get(Number(plot.id)) || {};
    const position = timelineNodePosition(plot, index);
    const nodeColor = lineColor(position.lane);
    const laneSide = position.lane === mainLineName
      ? (index % 2 === 0 ? "left" : "right")
      : (branchConfigByLine.get(position.lane)?.side === "left" ? "left" : "right");
    return {
      plot,
      index,
      nodeConfig,
      position,
      nodeColor,
      side: laneSide,
      priority: timelinePlotPriority(plot, nodeConfig),
    };
  });
  await yieldToMain();
  if (renderVersion !== timelineRenderVersion || state.view !== "timeline") return;

  const summaryItems = selectTimelineSummaryItems(positionedPlots, lines, mainLineName);
  const summaryIds = new Set(summaryItems.map((item) => Number(item.plot.id)));
  const legendLines = laneLines
    .filter((line) => line.lane !== mainLineName && connectorLines.some((connector) => connector.lane === line.lane));

  timelineModel = {
    width: graphWidth,
    height: graphHeight,
    mainLineName,
    lanes: lines,
    laneLines,
    connectors: connectorLines,
    positionedPlots,
    summaryItems,
    summaryIds,
    legendLines,
    focusLane: "",
    reversed: state.timelineReversed,
    visibleRange: null,
    viewportSettled: false,
  };
  timelineViewportKey = "";

  timelineList.innerHTML = `
    <div class="timeline-board ${plots.length > 36 ? "is-dense" : ""}" style="--timeline-height:${graphHeight}px; --map-width:${graphWidth}px">
      <div class="timeline-side timeline-side-left"></div>
      <div class="timeline-map">
        <div class="timeline-canvas" id="timelineCanvasWrap" style="width:${graphWidth}px; height:${graphHeight}px" aria-label="剧情线画布">
          <canvas class="timeline-drawing" id="timelineDrawing" aria-hidden="true"></canvas>
          <div class="timeline-node-layer" id="timelineNodeLayer"></div>
        </div>
      </div>
      <div class="timeline-side timeline-side-right"></div>
    </div>
  `;
  if (timelineLegend) timelineLegend.innerHTML = "";

  document.querySelector("#timelineCanvasWrap")?.addEventListener("click", handleTimelineCanvasClick);
  document.querySelector(".timeline-board")?.addEventListener("click", handleTimelineBoardClick);
  scheduleTimelineViewportRender(true);
}

function requestTimelineRender() {
  renderTimeline().catch((error) => {
    if (state.view === "timeline") {
      timelineList.innerHTML = `<div class="timeline-loading">时间线加载失败：${escapeHtml(error.message)}</div>`;
    }
    console.error(error);
  });
}

function timelineNodeMarkup(item) {
  const { plot, position, nodeColor, priority } = item;
  const positionLabel = `${position.lane} · ${timelinePercentLabel(position.storyRatio)}`;
  const nodeClass = [
    "timeline-node",
    "timeline-node-focus",
    priority >= 4 || timelineModel.summaryIds.has(Number(plot.id)) ? "is-featured" : "is-minor",
    plot.climax ? "is-climax" : "",
    plot.key ? "is-key" : "",
    timelineModel.focusLane && timelineModel.focusLane === position.lane ? "is-focused" : "",
    timelineModel.focusLane && timelineModel.focusLane !== position.lane ? "is-muted-by-focus" : "",
  ].filter(Boolean).join(" ");
  return `<button class="${nodeClass}" data-plot-id="${escapeHtml(plot.id)}" data-lane="${escapeHtml(position.lane)}" type="button" aria-label="${escapeHtml(timelinePlotTitle(plot))}，${escapeHtml(positionLabel)}" title="${escapeHtml(positionLabel)}" style="--accent:${escapeHtml(nodeColor)}; left:${position.x}px; top:${position.y}px">
    <span class="timeline-dot" aria-hidden="true"></span>
    <span class="timeline-node-tip">${escapeHtml(positionLabel)}</span>
  </button>`;
}

function timelineSummaryMarkup(item) {
  const { plot, position, nodeColor } = item;
  const hiddenByFocus = timelineModel.focusLane && timelineModel.focusLane !== position.lane;
  const stableClass = timelineModel.viewportSettled ? "is-stable" : "";
  return `
    <button class="timeline-summary-card timeline-jump ${stableClass} ${hiddenByFocus ? "is-hidden-by-focus" : ""}" data-plot-id="${escapeHtml(plot.id)}" data-primary-lane="${escapeHtml(position.lane)}" type="button" style="--accent:${escapeHtml(nodeColor)}; --card-y:${Math.round(position.y)}px">
      <span>${escapeHtml(timelinePlotChapter(plot))} · ${escapeHtml(plot.id)}</span>
      <strong>${escapeHtml(timelinePlotTitle(plot))}</strong>
      <p>${escapeHtml(markdownExcerpt(timelinePlotSummary(plot), 120))}</p>
      <small class="timeline-read-hint">阅读全文</small>
    </button>
  `;
}

function timelineVisibleRange() {
  if (!timelineModel || state.view !== "timeline") return null;
  const canvasWrap = document.querySelector("#timelineCanvasWrap");
  const canvasRect = canvasWrap?.getBoundingClientRect();
  const listRect = timelineList?.getBoundingClientRect();
  if (!canvasRect || !listRect || canvasRect.width <= 0 || canvasRect.height <= 0) return null;

  const clipTop = Math.max(0, listRect.top);
  const clipBottom = Math.min(window.innerHeight, listRect.bottom);
  const clipLeft = Math.max(0, listRect.left);
  const clipRight = Math.min(window.innerWidth, listRect.right);
  const visibleTop = Math.max(clipTop, canvasRect.top);
  const visibleBottom = Math.min(clipBottom, canvasRect.bottom);
  const visibleLeft = Math.max(clipLeft, canvasRect.left);
  const visibleRight = Math.min(clipRight, canvasRect.right);
  if (visibleBottom <= visibleTop || visibleRight <= visibleLeft) return null;

  const scaleX = timelineModel.width / canvasRect.width;
  const scaleY = timelineModel.height / canvasRect.height;
  return {
    top: (visibleTop - canvasRect.top) * scaleY,
    bottom: (visibleBottom - canvasRect.top) * scaleY,
    left: (visibleLeft - canvasRect.left) * scaleX,
    right: (visibleRight - canvasRect.left) * scaleX,
  };
}

function bufferedTimelineRange(range) {
  if (!timelineModel || !range) return null;
  const snapDown = (value) => Math.floor(value / TIMELINE_VIEWPORT_BUCKET) * TIMELINE_VIEWPORT_BUCKET;
  const snapUp = (value) => Math.ceil(value / TIMELINE_VIEWPORT_BUCKET) * TIMELINE_VIEWPORT_BUCKET;
  return {
    top: Math.max(0, snapDown(range.top - TIMELINE_VIEWPORT_BUFFER_Y)),
    bottom: Math.min(timelineModel.height, snapUp(range.bottom + TIMELINE_VIEWPORT_BUFFER_Y)),
    left: Math.max(0, snapDown(range.left - TIMELINE_VIEWPORT_BUFFER_X)),
    right: Math.min(timelineModel.width, snapUp(range.right + TIMELINE_VIEWPORT_BUFFER_X)),
  };
}

function bindTimelineViewportEvents() {
  document.querySelectorAll(".timeline-jump, .timeline-node-focus").forEach((item) => {
    item.addEventListener("click", (event) => {
      event.stopPropagation();
      openPlotDetail(Number(item.dataset.plotId));
    });
  });
}

function renderTimelineViewport(force = false) {
  if (!timelineModel || state.view !== "timeline") return;
  const range = timelineVisibleRange();
  const renderRange = bufferedTimelineRange(range);
  const nodeLayer = document.querySelector("#timelineNodeLayer");
  const leftSide = document.querySelector(".timeline-side-left");
  const rightSide = document.querySelector(".timeline-side-right");
  if (!range || !renderRange || !nodeLayer || !leftSide || !rightSide) {
    suspendTimelineViewport();
    return;
  }

  const key = [
    Math.round(renderRange.top),
    Math.round(renderRange.bottom),
    Math.round(renderRange.left),
    Math.round(renderRange.right),
    timelineModel.focusLane,
  ].join(":");
  timelineModel.visibleRange = range;
  if (!force && key === timelineViewportKey) {
    updateTimelineLegend(range);
    return;
  }
  timelineViewportKey = key;

  const visibleNodes = timelineModel.positionedPlots.filter(({ position }) => (
    position.y + 18 >= renderRange.top
    && position.y - 18 <= renderRange.bottom
    && position.x + 18 >= renderRange.left
    && position.x - 18 <= renderRange.right
  ));
  const visibleSummaries = timelineModel.summaryItems.filter(({ position }) => (
    position.y + 96 >= renderRange.top && position.y - 96 <= renderRange.bottom
  ));

  nodeLayer.innerHTML = visibleNodes.map(timelineNodeMarkup).join("");
  leftSide.innerHTML = visibleSummaries.filter((item) => item.side === "left").map(timelineSummaryMarkup).join("");
  rightSide.innerHTML = visibleSummaries.filter((item) => item.side !== "left").map(timelineSummaryMarkup).join("");
  timelineModel.viewportSettled = true;
  bindTimelineViewportEvents();
  drawTimelineCanvas(renderRange);
  updateTimelineLegend(range);
}

function scheduleTimelineViewportRender(force = false) {
  if (force) timelineViewportKey = "";
  if (timelineViewportFrame || state.view !== "timeline") return;
  timelineViewportFrame = window.requestAnimationFrame(() => {
    timelineViewportFrame = 0;
    renderTimelineViewport(force);
  });
}

function suspendTimelineViewport() {
  if (timelineViewportFrame) {
    window.cancelAnimationFrame(timelineViewportFrame);
    timelineViewportFrame = 0;
  }
  document.querySelector("#timelineNodeLayer")?.replaceChildren();
  document.querySelector(".timeline-side-left")?.replaceChildren();
  document.querySelector(".timeline-side-right")?.replaceChildren();
  document.querySelector("#timelineFloat")?.remove();
  if (timelineModel) timelineModel.focusLane = "";
  const canvas = document.querySelector("#timelineDrawing");
  if (canvas) {
    canvas.width = 0;
    canvas.height = 0;
    canvas.style.width = "0px";
    canvas.style.height = "0px";
  }
  if (timelineLegend) timelineLegend.innerHTML = "";
  timelineViewportKey = "";
}

function drawRoundedConnector(ctx, connector) {
  const sourcePoint = { x: connector.x1, y: connector.y1, color: connector.firstColor };
  const targetPoint = { x: connector.x3 ?? connector.x1, y: connector.y2, color: connector.targetColor || connector.firstColor };
  const topPoint = sourcePoint.y <= targetPoint.y ? sourcePoint : targetPoint;
  const bottomPoint = sourcePoint.y <= targetPoint.y ? targetPoint : sourcePoint;
  const topDirection = Math.sign(connector.x2 - topPoint.x) || 1;
  const bottomDirection = Math.sign(bottomPoint.x - connector.x2) || -topDirection;
  const { radius: r, topRailY, bottomRailY, branchTopY, branchBottomY } = connectorGeometry(connector);

  const topGradient = ctx.createLinearGradient(topPoint.x, topRailY, connector.x2, topRailY);
  topGradient.addColorStop(0, topPoint.color);
  topGradient.addColorStop(1, connector.lastColor);
  ctx.beginPath();
  ctx.moveTo(topPoint.x, topPoint.y);
  ctx.quadraticCurveTo(topPoint.x, topRailY, topPoint.x + topDirection * r, topRailY);
  ctx.lineTo(connector.x2 - topDirection * r, topRailY);
  ctx.quadraticCurveTo(connector.x2, topRailY, connector.x2, topRailY + r);
  ctx.strokeStyle = topGradient;
  ctx.stroke();

  ctx.beginPath();
  ctx.moveTo(connector.x2, branchTopY);
  ctx.lineTo(connector.x2, branchBottomY);
  ctx.strokeStyle = connector.lastColor;
  ctx.stroke();

  const bottomGradient = ctx.createLinearGradient(connector.x2, bottomRailY, bottomPoint.x, bottomRailY);
  bottomGradient.addColorStop(0, connector.lastColor);
  bottomGradient.addColorStop(1, bottomPoint.color);
  ctx.beginPath();
  ctx.moveTo(connector.x2, branchBottomY);
  ctx.quadraticCurveTo(connector.x2, bottomRailY, connector.x2 + bottomDirection * r, bottomRailY);
  ctx.lineTo(bottomPoint.x - bottomDirection * r, bottomRailY);
  ctx.quadraticCurveTo(bottomPoint.x, bottomRailY, bottomPoint.x, bottomPoint.y);
  ctx.strokeStyle = bottomGradient;
  ctx.stroke();
}

function drawTimelineCanvas(range = timelineVisibleRange()) {
  const canvas = document.querySelector("#timelineDrawing");
  if (!canvas || !timelineModel || !range) return;
  const drawLeft = Math.max(0, Math.floor(range.left));
  const drawRight = Math.min(timelineModel.width, Math.ceil(range.right));
  const drawTop = Math.max(0, Math.floor(range.top));
  const drawBottom = Math.min(timelineModel.height, Math.ceil(range.bottom));
  const drawWidth = Math.max(1, drawRight - drawLeft);
  const drawHeight = Math.max(1, drawBottom - drawTop);
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.ceil(drawWidth * ratio);
  canvas.height = Math.ceil(drawHeight * ratio);
  canvas.style.left = `${drawLeft}px`;
  canvas.style.top = `${drawTop}px`;
  canvas.style.width = `${drawWidth}px`;
  canvas.style.height = `${drawHeight}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, -drawLeft * ratio, -drawTop * ratio);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";

  timelineModel.laneLines.filter((line) => (
    line.lane === timelineModel.mainLineName
    && line.x + 16 >= drawLeft
    && line.x - 16 <= drawRight
    && Math.max(line.y1, line.y2) >= drawTop
    && Math.min(line.y1, line.y2) <= drawBottom
  )).forEach((line) => {
    const isFocused = timelineModel.focusLane === line.lane;
    ctx.save();
    ctx.globalAlpha = timelineModel.focusLane && !isFocused ? 0.18 : 0.84;
    ctx.strokeStyle = line.color;
    ctx.lineWidth = isFocused ? 12 : 7;
    ctx.shadowColor = isFocused ? "rgba(25, 33, 42, 0.26)" : "rgba(31, 46, 58, 0.12)";
    ctx.shadowBlur = isFocused ? 16 : 8;
    ctx.beginPath();
    ctx.moveTo(line.x, Math.max(drawTop, Math.min(line.y1, line.y2)));
    ctx.lineTo(line.x, Math.min(drawBottom, Math.max(line.y1, line.y2)));
    ctx.stroke();
    ctx.restore();
  });

  timelineModel.connectors.filter((connector) => {
    const minX = Math.min(connector.x1, connector.x2, connector.x3 ?? connector.x1);
    const maxX = Math.max(connector.x1, connector.x2, connector.x3 ?? connector.x1);
    const minY = Math.min(connector.y1, connector.y2);
    const maxY = Math.max(connector.y1, connector.y2);
    return maxX + 20 >= drawLeft && minX - 20 <= drawRight && maxY + 20 >= drawTop && minY - 20 <= drawBottom;
  }).forEach((connector) => {
    const isFocused = timelineModel.focusLane === connector.lane;
    const isRelated = connector.lane === timelineModel.focusLane;
    ctx.save();
    ctx.globalAlpha = timelineModel.focusLane && !isFocused && !isRelated ? 0.14 : 0.76;
    ctx.lineWidth = isFocused ? 8 : 5;
    ctx.shadowColor = isFocused ? "rgba(25, 33, 42, 0.24)" : "rgba(31, 46, 58, 0.1)";
    ctx.shadowBlur = isFocused ? 14 : 8;
    drawRoundedConnector(ctx, connector);
    ctx.restore();
  });
}

function updateTimelineLegend(range = timelineVisibleRange()) {
  if (!timelineModel || !timelineLegend) return;
  const visibleLines = new Set();
  if (range) {
    const overlapsView = (start, end) => Math.max(start, range.top) <= Math.min(end, range.bottom);
    timelineModel.laneLines.forEach((line) => {
      if (overlapsView(Math.min(line.y1, line.y2), Math.max(line.y1, line.y2))) visibleLines.add(line.lane);
    });
    timelineModel.connectors.forEach((connector) => {
      if (overlapsView(Math.min(connector.y1, connector.y2), Math.max(connector.y1, connector.y2))) visibleLines.add(connector.lane);
    });
  }

  const visibleLegendLines = timelineModel.legendLines.filter((line) => (
    timelineModel.focusLane ? line.lane === timelineModel.focusLane : visibleLines.has(line.lane)
  ));
  timelineLegend.innerHTML = visibleLegendLines.map((line) => `
    <span class="timeline-legend-item ${line.lane === timelineModel.focusLane ? "is-active" : ""}" data-line="${escapeHtml(line.lane)}" style="--accent:${escapeHtml(line.color)}">
      <i aria-hidden="true"></i>${escapeHtml(line.lane)}
    </span>
  `).join("");
  const visibleCount = visibleLegendLines.length;
  const legendRows = visibleCount <= 3
    ? Math.max(1, visibleCount)
    : Math.ceil(Math.sqrt(visibleCount));
  timelineLegend.style.setProperty("--legend-rows", legendRows);
  timelineLegend.classList.toggle("is-hidden", state.view !== "timeline" || visibleCount === 0);
}

function distanceToSegment(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  if (dx === 0 && dy === 0) return Math.hypot(px - x1, py - y1);
  const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

function connectorHitDistance(x, y, connector) {
  const { topRailY, bottomRailY, branchTopY, branchBottomY } = connectorGeometry(connector);
  const sourcePoint = { x: connector.x1, y: connector.y1 };
  const targetPoint = { x: connector.x3 ?? connector.x1, y: connector.y2 };
  const topPoint = sourcePoint.y <= targetPoint.y ? sourcePoint : targetPoint;
  const bottomPoint = sourcePoint.y <= targetPoint.y ? targetPoint : sourcePoint;
  return Math.min(
    distanceToSegment(x, y, topPoint.x, topRailY, connector.x2, topRailY),
    distanceToSegment(x, y, connector.x2, branchTopY, connector.x2, branchBottomY),
    distanceToSegment(x, y, connector.x2, bottomRailY, bottomPoint.x, bottomRailY),
    Math.hypot(x - topPoint.x, y - topPoint.y),
    Math.hypot(x - bottomPoint.x, y - bottomPoint.y),
  );
}

function handleTimelineCanvasClick(event) {
  if (!timelineModel) return;
  event.stopPropagation();
  const rect = event.currentTarget.getBoundingClientRect();
  const x = (event.clientX - rect.left) * (timelineModel.width / rect.width);
  const y = (event.clientY - rect.top) * (timelineModel.height / rect.height);
  const connector = timelineModel.connectors.find((item) => connectorHitDistance(x, y, item) < 14);
  if (connector) {
    showTimelineFloat({ dataset: { lane: connector.lane } });
    return;
  }
  const lane = timelineModel.laneLines.find((item) => (
    Math.abs(x - item.x) < 18 && y >= item.y1 - 8 && y <= item.y2 + 8
  ));
  if (lane) {
    showTimelineFloat({ dataset: { lane: lane.lane } });
    return;
  }
  hideTimelineFloat();
}

function handleTimelineBoardClick(event) {
  const interactiveTarget = event.target.closest(
    ".timeline-summary-card, .timeline-node, .timeline-float, #timelineCanvasWrap",
  );
  if (interactiveTarget) return;
  hideTimelineFloat();
}

function ensureTimelineFloat() {
  let float = document.querySelector("#timelineFloat");
  if (float) return float;
  float = document.createElement("div");
  float.className = "timeline-float";
  float.id = "timelineFloat";
  float.innerHTML = `
    <span id="timelineFloatLane"></span>
    <strong id="timelineFloatTitle"></strong>
    <p id="timelineFloatText"></p>
  `;
  document.querySelector(".timeline-board")?.append(float);
  return float;
}

function showTimelineFloat(target) {
  const float = ensureTimelineFloat();
  if (!float) return;
  const plot = plots.find((item) => item.id === Number(target.dataset.plotId));
  const lane = target.dataset.lane || "剧情线";
  const activeLane = lane.split(" / ").map((item) => item.trim()).filter(Boolean)[0] || lane;
  if (timelineModel) timelineModel.focusLane = plot ? activeLane : lane;
  scheduleTimelineViewportRender(true);
  document.querySelectorAll(".timeline-summary-card.is-hidden-by-focus").forEach((item) => item.classList.remove("is-hidden-by-focus"));
  document.querySelectorAll(".timeline-summary-card").forEach((item) => {
    const isRelated = plot
      ? item.dataset.plotId === String(plot.id)
      : item.dataset.primaryLane === lane;
    item.classList.toggle("is-hidden-by-focus", !isRelated);
  });
  document.querySelectorAll(".timeline-node").forEach((item) => {
    const isRelated = plot
      ? item.dataset.plotId === String(plot.id)
      : item.dataset.lane === lane;
    item.classList.toggle("is-muted-by-focus", !isRelated);
  });
  document.querySelector("#timelineFloatLane").textContent = plot ? activeLane : lane;
  document.querySelector("#timelineFloatTitle").textContent = plot ? timelinePlotTitle(plot) : "剧情流向";
  document.querySelector("#timelineFloatText").textContent = plot ? timelinePlotSummary(plot) : "这条剧情线连接了相关事件，点击节点可跳到完整剧情。";
}

function hideTimelineFloat() {
  document.querySelector("#timelineFloat")?.remove();
  if (timelineModel) timelineModel.focusLane = "";
  scheduleTimelineViewportRender(true);
  document.querySelectorAll(".timeline-summary-card.is-hidden-by-focus").forEach((item) => item.classList.remove("is-hidden-by-focus"));
  document.querySelectorAll(".timeline-node.is-muted-by-focus").forEach((item) => item.classList.remove("is-muted-by-focus"));
}

function setChapterFilter(chapter) {
  state.chapter = chapter;
  document.querySelectorAll(".chapter-btn").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.chapter === chapter);
  });
}

function rememberCurrentPlotPosition() {
  if (state.view !== "plot-detail" || state.selectedPlotId === null) return;
  state.plotReadingPositions[String(state.selectedPlotId)] = window.scrollY;
}

function restorePlotPosition(plotId) {
  const savedPosition = state.plotReadingPositions[String(plotId)];
  if (!Number.isFinite(savedPosition)) return;
  window.requestAnimationFrame(() => {
    window.scrollTo({ top: savedPosition, left: 0, behavior: "auto" });
    updateReadingProgress();
  });
}

function openPlotInStory(plotId) {
  const plot = plots.find((item) => item.id === plotId);
  if (!plot) return;
  rememberCurrentPlotPosition();
  state.detailReturnContext = null;
  state.highlightedReferenceType = "";
  state.highlightedReferenceId = "";
  state.highlightPlotId = plotId;
  setChapterFilter(plot.chapter);
  switchView("story");
  renderPlots();
  window.setTimeout(() => {
    document.querySelector(`[data-plot-id="${plotId}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, 60);
}

function openCharacterDetail(id, { preserveReturnContext = false } = {}) {
  const person = getCharacter(id);
  if (!person) return;
  rememberCurrentPlotPosition();
  if (!preserveReturnContext) state.detailReturnContext = null;
  state.selectedCharacter = id;
  state.characterSearch = "";
  if (characterSearch) characterSearch.value = "";
  switchView("characters");
  hideGlobalSearchResults();
}

function openPlaceDetail(id, { preserveReturnContext = false } = {}) {
  const place = getPlace(id);
  if (!place) return;
  rememberCurrentPlotPosition();
  if (!preserveReturnContext) state.detailReturnContext = null;
  state.selectedPlace = id;
  state.placeSearch = "";
  if (placeSearch) placeSearch.value = "";
  switchView("places");
  hideGlobalSearchResults();
}

function openPlotDetail(plotId, { preserveReturnContext = false } = {}) {
  const plot = plots.find((item) => item.id === plotId);
  if (!plot) return;
  rememberCurrentPlotPosition();
  if (!preserveReturnContext) state.detailReturnContext = null;
  if (Number(state.selectedPlotId) !== Number(plotId)) {
    state.highlightedReferenceType = "";
    state.highlightedReferenceId = "";
  }
  state.selectedPlotId = plotId;
  state.highlightPlotId = plotId;
  switchView("plot-detail");
  hideGlobalSearchResults();
  restorePlotPosition(plotId);
}

function openPlotReferenceDetail(type, id) {
  rememberCurrentPlotPosition();
  state.detailReturnContext = {
    plotId: Number(state.selectedPlotId),
    scrollY: window.scrollY,
    highlightedReferenceType: state.highlightedReferenceType,
    highlightedReferenceId: state.highlightedReferenceId,
  };
  if (type === "character") openCharacterDetail(id, { preserveReturnContext: true });
  if (type === "place") openPlaceDetail(id, { preserveReturnContext: true });
}

function returnToPlotContext() {
  const context = state.detailReturnContext;
  if (!context) return;
  state.highlightedReferenceType = context.highlightedReferenceType;
  state.highlightedReferenceId = context.highlightedReferenceId;
  state.plotReadingPositions[String(context.plotId)] = context.scrollY;
  openPlotDetail(context.plotId, { preserveReturnContext: true });
}

function detailReturnButton() {
  if (!state.detailReturnContext) return "";
  const plot = plots.find((item) => Number(item.id) === Number(state.detailReturnContext.plotId));
  return `
    <button class="return-to-plot-btn" type="button">
      <span aria-hidden="true">←</span>
      <span>返回《${escapeHtml(plot?.title || "原章节")}》</span>
    </button>
  `;
}

function globalSearchText() {
  return state.globalSearch.trim().toLowerCase();
}

function matchesKeyword(values, keyword) {
  return values
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(keyword));
}

function globalSearchMatches() {
  const keyword = globalSearchText();
  if (!keyword) return [];
  const characterResults = characters
    .filter((person) => matchesKeyword([
      person.name,
      person.id,
      person.group,
      person.intro,
      ...characterMarkers(person),
      ...characterFactSearchValues(person),
      ...characterRelationshipSearchValues(person),
    ], keyword))
    .map((person) => ({
      type: "character",
      id: person.id,
      title: person.name,
      meta: `人物 · ${person.group || "未分组"}`,
      text: person.intro,
    }));

  const plotResults = plots
    .filter((plot) => matchesKeyword([
      plot.title,
      plot.text,
      plot.status,
      chapterName(plot.chapter),
      ...(plot.people || []).map((id) => getCharacter(id)?.name || id),
      ...(plot.entries || []).map((id) => getPlace(id)?.name || id),
      ...(plot.lanes || []),
      ...(plot.tags || []),
    ], keyword))
    .map((plot) => ({
      type: "plot",
      id: plot.id,
      title: plot.title,
      meta: `剧情 · ${chapterName(plot.chapter)} · ${plot.status || "未标记"} · ${plot.id}`,
      text: plotExcerpt(plot),
    }));

  const placeResults = places
    .filter((place) => matchesKeyword([
      place.name,
      place.id,
      place.type,
      place.subtype,
      place.area,
      place.intro,
      ...(place.aliases || []),
      ...(place.people || []).map((id) => getCharacter(id)?.name || id),
    ], keyword))
    .map((place) => ({
      type: "place",
      id: place.id,
      title: place.name,
      meta: `设定 · ${place.type || "未分类"} · ${place.area || "未分区"}`,
      text: place.intro,
    }));

  const fragmentResults = fragments
    .filter((fragment) => matchesKeyword([
      fragment.title,
      fragment.text,
      fragment.status,
      ...(fragment.tags || []),
    ], keyword))
    .map((fragment) => ({
      type: "fragment",
      id: fragment.id,
      title: fragment.title,
      meta: `碎片 · ${fragment.status || "灵感"}`,
      text: String(fragment.text || "").replace(/\s+/g, " ").slice(0, 86),
    }));

  const relationshipResults = relationships
    .filter((link) => {
      const from = getCharacter(link.from);
      const to = getCharacter(link.to);
      return matchesKeyword([
        link.label,
        link.type,
        link.fromRole,
        link.toRole,
        from?.name,
        to?.name,
        link.from,
        link.to,
      ], keyword);
    })
    .map((link, index) => {
      const from = getCharacter(link.from);
      const to = getCharacter(link.to);
      return {
        type: "relationship",
        id: index,
        from: link.from,
        to: link.to,
        title: `${from?.name || link.from} ↔ ${to?.name || link.to}`,
        meta: `关系 · ${link.label || link.type || "未分类"}`,
        text: link.type || "",
      };
    });

  return [...characterResults, ...placeResults, ...plotResults, ...fragmentResults, ...relationshipResults].slice(0, 9);
}

function hideGlobalSearchResults() {
  globalSearchResults?.classList.add("is-hidden");
}

function renderGlobalSearchResults() {
  if (!globalSearchResults) return;
  const results = globalSearchMatches();
  if (!state.globalSearch.trim()) {
    globalSearchResults.innerHTML = "";
    hideGlobalSearchResults();
    return;
  }
  if (!results.length) {
    globalSearchResults.innerHTML = '<p class="global-search-empty">没有找到匹配内容</p>';
    globalSearchResults.classList.remove("is-hidden");
    return;
  }
  globalSearchResults.innerHTML = results.map((result) => `
    <button class="global-search-result" type="button" data-type="${escapeHtml(result.type)}" data-id="${escapeHtml(result.id)}" data-from="${escapeHtml(result.from || "")}" data-to="${escapeHtml(result.to || "")}">
      <span>${escapeHtml(result.meta)}</span>
      <strong>${escapeHtml(result.title)}</strong>
      <small>${escapeHtml(markdownExcerpt(result.text || "", 86))}</small>
    </button>
  `).join("");
  globalSearchResults.classList.remove("is-hidden");
  document.querySelectorAll(".global-search-result").forEach((button) => {
    button.addEventListener("click", () => {
      const type = button.dataset.type;
      if (type === "character") openCharacterDetail(button.dataset.id);
      if (type === "place") openPlaceDetail(button.dataset.id);
      if (type === "plot") openPlotDetail(Number(button.dataset.id));
      if (type === "fragment") {
        switchView("fragments");
        window.setTimeout(() => {
          document.querySelector(`#fragment-${CSS.escape(button.dataset.id)}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
        }, 80);
      }
      if (type === "relationship") {
        switchView("graph");
        selectPerson(button.dataset.from);
      }
      if (globalSearch) globalSearch.value = "";
      state.globalSearch = "";
      hideGlobalSearchResults();
    });
  });
}

function plotReferenceTerms(type, id) {
  const candidates = type === "character" ? characterMentionCandidates() : entryMentionCandidates();
  return candidates
    .filter((candidate) => String(candidate.id) === String(id))
    .map((candidate) => candidate.term)
    .sort((a, b) => b.length - a.length);
}

function plotReferenceColor(type, id) {
  if (type === "character") return getCharacter(id)?.color || "#2a9d8f";
  return getPlace(id)?.accent || "#457b9d";
}

function applyPlotReferenceHighlights() {
  const { highlightedReferenceType: type, highlightedReferenceId: id } = state;
  const body = document.querySelector(".plot-detail-body");
  if (!body || !type || !id) return;
  const terms = plotReferenceTerms(type, id);
  if (!terms.length) return;

  const pattern = new RegExp(terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "g");
  const textNodes = [];
  const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node) {
    if (!node.parentElement?.closest("mark, pre, code")) textNodes.push(node);
    node = walker.nextNode();
  }

  textNodes.forEach((textNode) => {
    const text = textNode.nodeValue || "";
    pattern.lastIndex = 0;
    if (!pattern.test(text)) return;
    pattern.lastIndex = 0;
    const fragment = document.createDocumentFragment();
    let cursor = 0;
    text.replace(pattern, (match, offset) => {
      fragment.append(text.slice(cursor, offset));
      const mark = document.createElement("mark");
      mark.className = "plot-reference-mark";
      mark.style.setProperty("--reference-color", plotReferenceColor(type, id));
      mark.textContent = match;
      fragment.append(mark);
      cursor = offset + match.length;
      return match;
    });
    fragment.append(text.slice(cursor));
    textNode.replaceWith(fragment);
  });
}

function togglePlotReference(type, id) {
  const isActive = state.highlightedReferenceType === type && String(state.highlightedReferenceId) === String(id);
  state.highlightedReferenceType = isActive ? "" : type;
  state.highlightedReferenceId = isActive ? "" : id;
  const scrollY = window.scrollY;
  renderPlotDetail();
  window.requestAnimationFrame(() => {
    window.scrollTo({ top: scrollY, left: 0, behavior: "auto" });
    updateReadingProgress();
  });
}

function configureFloatingReadingTools(plot, navigation) {
  const readingTools = document.querySelector("#readingProgress");
  const progressMeter = document.querySelector("#readingProgressMeter");
  const backButton = document.querySelector("#floatingPlotBack");
  const prevButton = document.querySelector("#floatingPlotPrev");
  const nextButton = document.querySelector("#floatingPlotNext");
  if (!readingTools || !progressMeter || !backButton || !prevButton || !nextButton) return;

  readingTools.classList.remove("is-hidden");
  readingTools.style.setProperty("--accent", plot.accent);
  readingTools.style.setProperty("--reading-progress", "0%");
  progressMeter.setAttribute("aria-label", "阅读进度 0%");
  progressMeter.setAttribute("aria-valuenow", "0");
  readingTools.querySelectorAll(".reading-progress-value").forEach((value) => {
    value.textContent = "0%";
  });
  document.querySelector("#floatingPlotChapter").textContent = `${chapterName(plot.chapter)} · ${plot.id}`;

  backButton.onclick = () => openPlotInStory(plot.id);
  prevButton.disabled = !navigation.prev;
  nextButton.disabled = !navigation.next;
  document.querySelector("#floatingPlotPrevTitle").textContent = navigation.prev?.title || "没有上一章";
  document.querySelector("#floatingPlotNextTitle").textContent = navigation.next?.title || "没有下一章";
  prevButton.onclick = navigation.prev ? () => openPlotDetail(navigation.prev.id) : null;
  nextButton.onclick = navigation.next ? () => openPlotDetail(navigation.next.id) : null;
}

function renderPlotDetail() {
  const plot = plots.find((item) => item.id === Number(state.selectedPlotId)) || plots[0];
  if (!plot || !plotDetail || !plotPeopleRail) return;
  const plotPeople = plot.people.map((id) => ({ id, person: getCharacter(id) }));
  const plotPlaces = (plot.entries || []).map((id) => ({ id, place: getPlace(id) }));
  const navigation = plotNavigation(plot);
  const markdown = renderMarkdownContent(plot.text);
  const summary = markdownExcerpt(plot.summary || plot.text, 180);
  configureFloatingReadingTools(plot, navigation);

  plotPeopleRail.innerHTML = `
    <section class="plot-rail-section">
      <p class="eyebrow">Cast</p>
      <h2>出场人物</h2>
      <div class="plot-people-list">
        ${plotPeople.map(({ id, person }) => {
          if (!person) {
            return `
              <div class="plot-person-item">
                <span class="mini-avatar" style="--avatar-gradient:linear-gradient(135deg, #9aa6b2, #65717d)">${escapeHtml(id).slice(0, 2)}</span>
                <span>
                  <strong>${escapeHtml(id)}</strong>
                  <small>未在人物列表中</small>
                </span>
              </div>
            `;
          }
          return `
            <div class="plot-reference-row ${
              state.highlightedReferenceType === "character" && state.highlightedReferenceId === person.id ? "is-active" : ""
            }" style="--accent:${escapeHtml(person.color)}">
              <button class="plot-person-item plot-reference-toggle" data-reference-type="character" data-id="${escapeHtml(person.id)}" type="button" aria-pressed="${
                state.highlightedReferenceType === "character" && state.highlightedReferenceId === person.id
              }">
                <span class="mini-avatar" style="--avatar-gradient:${escapeHtml(person.gradient)}">${avatarContent(person)}</span>
                <span>
                  <strong>${escapeHtml(person.name)}</strong>
                  <small>${escapeHtml(person.group || "未分组")}</small>
                </span>
              </button>
              <button class="plot-reference-open" data-reference-type="character" data-id="${escapeHtml(person.id)}" type="button" aria-label="查看${escapeHtml(person.name)}详情" title="查看人物详情">→</button>
            </div>
          `;
        }).join("") || '<p class="empty-state">这个剧情点还没有配置出场人物。</p>'}
      </div>
    </section>
    ${plotPlaces.length ? `
      <section class="plot-rail-section">
        <p class="eyebrow">Entries</p>
        <h2>关联设定</h2>
        <div class="plot-people-list">
          ${plotPlaces.map(({ id, place }) => {
            if (!place) {
              return `
                <div class="plot-place-item">
                  <span class="place-mini-symbol" style="--accent:#9aa6b2">${escapeHtml(id).slice(0, 2)}</span>
                  <span>
                    <strong>${escapeHtml(id)}</strong>
                    <small>未在设定档案中</small>
                  </span>
                </div>
              `;
            }
            return `
              <div class="plot-reference-row ${
                state.highlightedReferenceType === "place" && state.highlightedReferenceId === place.id ? "is-active" : ""
              }" style="--accent:${escapeHtml(place.accent)}">
                <button class="plot-place-item plot-reference-toggle" data-reference-type="place" data-id="${escapeHtml(place.id)}" type="button" aria-pressed="${
                  state.highlightedReferenceType === "place" && state.highlightedReferenceId === place.id
                }">
                  <span class="place-mini-symbol">${escapeHtml(place.name).slice(0, 2)}</span>
                  <span>
                    <strong>${escapeHtml(place.name)}</strong>
                    <small>${escapeHtml(place.type || "未分类")} · ${escapeHtml(place.area || "未分区")}</small>
                  </span>
                </button>
                <button class="plot-reference-open" data-reference-type="place" data-id="${escapeHtml(place.id)}" type="button" aria-label="查看${escapeHtml(place.name)}详情" title="查看设定详情">→</button>
              </div>
            `;
          }).join("")}
        </div>
      </section>
    ` : ""}
    ${markdown.toc.length ? `
      <section class="plot-rail-section">
        <p class="eyebrow">Contents</p>
        <h2>本章目录</h2>
        <nav class="plot-toc" aria-label="本章目录">
          ${markdown.toc.map((item) => `
            <a href="#${item.id}" class="plot-toc-item level-${item.level}">${escapeHtml(item.title)}</a>
          `).join("")}
        </nav>
      </section>
    ` : ""}
  `;

  plotDetail.innerHTML = `
    <div class="plot-detail-head" style="--accent:${escapeHtml(plot.accent)}">
      <h2>${escapeHtml(plot.title)}</h2>
      <p class="plot-detail-summary">${escapeHtml(summary)}</p>
      <div class="badge-line">
        ${statusBadge(plot.status)}
        ${tagBadges(plot.tags)}
        ${plotBadges(plot)}
      </div>
    </div>
    <div class="plot-detail-body" style="--accent:${escapeHtml(plot.accent)}">
      ${markdown.html}
    </div>
  `;

  document.querySelectorAll(".plot-toc-item").forEach((item) => {
    item.addEventListener("click", (event) => {
      event.preventDefault();
      document.querySelector(item.getAttribute("href"))?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
  applyPlotReferenceHighlights();
  document.querySelectorAll(".plot-reference-toggle").forEach((button) => {
    button.addEventListener("click", () => togglePlotReference(button.dataset.referenceType, button.dataset.id));
  });
  document.querySelectorAll(".plot-reference-open").forEach((button) => {
    button.addEventListener("click", () => openPlotReferenceDetail(button.dataset.referenceType, button.dataset.id));
  });
  window.requestAnimationFrame(updateReadingProgress);
}

function updateReadingProgress() {
  const progress = document.querySelector("#readingProgress");
  const progressMeter = document.querySelector("#readingProgressMeter");
  const body = document.querySelector(".plot-detail-body");
  if (!progress || !progressMeter || !body || state.view !== "plot-detail") return;

  const rect = body.getBoundingClientRect();
  const bodyTop = rect.top + window.scrollY;
  const bodyBottom = rect.bottom + window.scrollY;
  const start = bodyTop - Math.min(130, window.innerHeight * 0.18);
  const end = bodyBottom - window.innerHeight + Math.min(150, window.innerHeight * 0.2);
  const atPageEnd = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2;
  const ratio = atPageEnd
    ? 1
    : end <= start
      ? (window.scrollY >= start ? 1 : 0)
      : Math.max(0, Math.min(1, (window.scrollY - start) / (end - start)));
  const percent = Math.round(ratio * 100);

  progress.style.setProperty("--reading-progress", `${percent}%`);
  progressMeter.setAttribute("aria-label", `阅读进度 ${percent}%`);
  progressMeter.setAttribute("aria-valuenow", String(percent));
  progress.querySelectorAll(".reading-progress-value").forEach((value) => {
    value.textContent = `${percent}%`;
  });
}

function renderCharacterList() {
  const visibleCharacters = characters.filter((person) => {
    if (!state.characterSearch) return true;
    const keyword = state.characterSearch.toLowerCase();
    return [
      person.name,
      person.id,
      person.group,
      person.intro,
      ...characterMarkers(person),
      ...characterFactSearchValues(person),
      ...characterRelationshipSearchValues(person),
    ]
      .filter(Boolean)
      .some((text) => String(text).toLowerCase().includes(keyword));
  });

  if (visibleCharacters.length && !visibleCharacters.some((person) => person.id === state.selectedCharacter)) {
    state.selectedCharacter = visibleCharacters[0].id;
  }

  characterList.innerHTML = visibleCharacters
    .map((person) => `
      <button class="character-list-item ${person.id === state.selectedCharacter ? "is-active" : ""}" data-id="${escapeHtml(person.id)}" type="button">
        <span class="mini-avatar" style="--avatar-gradient:${escapeHtml(person.gradient)}">${avatarContent(person)}</span>
        <span>
          <strong>${escapeHtml(person.name)}</strong>
          <small>${escapeHtml(person.group || "未分组")}</small>
        </span>
      </button>
    `)
    .join("");

  if (!visibleCharacters.length) {
    characterList.innerHTML = '<p class="empty-state">没有找到匹配人物</p>';
  }

  document.querySelectorAll(".character-list-item").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedCharacter = button.dataset.id;
      renderCharacterList();
      renderCharacterDetail();
      scrollPageToTop();
    });
  });
}

function renderCharacterDetail() {
  const person = getCharacter(state.selectedCharacter) || characters[0];
  if (!person) {
    characterDetail.innerHTML = "";
    return;
  }

  const personPlots = plots.filter((plot) => plot.people.includes(person.id) || person.events.includes(plot.id));
  const personLinks = relationships.filter((link) => link.from === person.id || link.to === person.id);

  characterDetail.innerHTML = `
    ${detailReturnButton()}
    <div class="character-hero ${person.facts.length ? "has-facts" : ""}" style="--accent:${escapeHtml(person.color)}">
      <div class="character-avatar" style="--avatar-gradient:${escapeHtml(person.gradient)}">${avatarContent(person)}</div>
      <div class="character-copy">
        <p class="label">${escapeHtml(person.group || "未分组")}</p>
        <div class="character-title-row">
          <h2>${escapeHtml(person.name)}</h2>
          <button
            class="character-rename-trigger"
            type="button"
            aria-label="修改${escapeHtml(person.name)}的名字"
            title="修改角色名"
          >
            <span aria-hidden="true">✎</span>
          </button>
        </div>
        <div class="character-rename-editor is-hidden">
          <div class="character-rename-input-row">
            <input
              class="character-rename-input"
              type="text"
              maxlength="80"
              autocomplete="off"
              placeholder="输入新的角色名"
              aria-label="新的角色名"
            />
            <button class="character-rename-preview" type="button">预览修改</button>
            <button class="character-rename-cancel" type="button">取消</button>
          </div>
          <div class="character-rename-result" aria-live="polite"></div>
        </div>
        <p>${escapeHtml(person.intro)}</p>
        ${person.facts.length ? `
          <dl class="character-facts" aria-label="${escapeHtml(person.name)}的档案信息">
            ${person.facts.map((fact) => `
              <div class="character-fact">
                <dt>${escapeHtml(fact.label)}</dt>
                <dd>${escapeHtml(fact.value)}</dd>
              </div>
            `).join("")}
          </dl>
        ` : ""}
      </div>
      <aside class="character-marker-panel">
        ${markerBadges(person)}
      </aside>
    </div>

    <section class="character-section">
      <div class="section-title">
        <p class="label">人物关系</p>
        <h3>${personLinks.length} 条关系</h3>
      </div>
      <div class="relation-list">
        ${personLinks.map((link) => {
          const perspective = relationshipPerspective(link, person.id);
          const other = getCharacter(perspective.otherId);
          return `
            <button
              class="relation-row"
              data-character-id="${escapeHtml(perspective.otherId)}"
              type="button"
              style="--accent:${escapeHtml(link.color)}"
              aria-label="查看${escapeHtml(other?.name || perspective.otherId)}的人物详情"
            >
              <span class="mini-avatar" style="--avatar-gradient:${escapeHtml(other?.gradient || "linear-gradient(135deg, #9aa6b2, #65717d)")}">
                ${other ? avatarContent(other) : escapeHtml(perspective.otherId)}
              </span>
              <span class="relation-person">
                <strong>${escapeHtml(other?.name || perspective.otherId)}</strong>
                <span class="relation-role">${escapeHtml(perspective.otherRole || "关系人物")}</span>
              </span>
              <span class="relation-meta">
                <span>${escapeHtml(link.label || "人物关系")}</span>
                <small>${escapeHtml(link.type || "未分类")}</small>
              </span>
              <span class="relation-arrow" aria-hidden="true">→</span>
            </button>
          `;
        }).join("") || '<p class="empty-state">这个人物还没有配置关系。</p>'}
      </div>
    </section>

    <section class="character-section">
      <div class="section-title">
        <p class="label">出场剧情</p>
        <h3>${personPlots.length} 个剧情点</h3>
      </div>
      <div class="character-plot-list">
        ${personPlots.map((plot) => `
          <button
            class="${storyCardClass(plot, "character-plot detail-plot-card character-plot-card")}"
            data-plot-id="${escapeHtml(plot.id)}"
            type="button"
            style="--accent:${escapeHtml(plot.accent)}"
          >
            ${renderStoryCardContent(plot, { heading: "strong", titlePrefix: `${plot.id}. ` })}
          </button>
        `).join("")}
      </div>
    </section>
  `;

  characterDetail.querySelector(".return-to-plot-btn")?.addEventListener("click", returnToPlotContext);
  characterDetail.querySelectorAll(".character-plot-card[data-plot-id]").forEach((button) => {
    button.addEventListener("click", () => openPlotDetail(Number(button.dataset.plotId)));
  });
  bindCharacterRename(person);
}

function bindCharacterRename(person) {
  const trigger = characterDetail.querySelector(".character-rename-trigger");
  const editor = characterDetail.querySelector(".character-rename-editor");
  const input = characterDetail.querySelector(".character-rename-input");
  const previewButton = characterDetail.querySelector(".character-rename-preview");
  const cancelButton = characterDetail.querySelector(".character-rename-cancel");
  const result = characterDetail.querySelector(".character-rename-result");
  if (!trigger || !editor || !input || !previewButton || !cancelButton || !result) return;

  const reset = () => {
    refactorOperationId = "";
    input.value = "";
    result.innerHTML = "";
    editor.classList.add("is-hidden");
    trigger.setAttribute("aria-expanded", "false");
  };

  const setBusy = (busy) => {
    input.disabled = busy;
    previewButton.disabled = busy;
    cancelButton.disabled = busy;
    result.querySelector(".character-rename-apply")?.toggleAttribute("disabled", busy);
  };

  const showError = (message) => {
    refactorOperationId = "";
    result.innerHTML = `<p class="character-rename-error">${escapeHtml(message)}</p>`;
  };

  const preview = async () => {
    const newName = input.value.trim();
    if (!newName) {
      showError("请先输入新的角色名");
      input.focus();
      return;
    }
    setBusy(true);
    try {
      await initializeRefactorWorkspace();
      if (!refactorCapability?.writable) throw new Error("当前页面是只读模式，请用 run.sh 启动本地服务");
      const previewResult = await refactorApi("/api/refactor/preview", {
        project: currentProjectId(),
        type: "character",
        id: person.id,
        newName,
      });
      refactorOperationId = previewResult.operationId;
      result.innerHTML = `
        <div class="character-rename-confirm">
          <span>
            <strong>${escapeHtml(previewResult.oldName)} → ${escapeHtml(previewResult.newName)}</strong>
            将修改 ${previewResult.fileCount} 个文件、${previewResult.matchCount} 处引用
          </span>
          <button class="character-rename-apply" type="button">确认应用</button>
        </div>
      `;
      result.querySelector(".character-rename-apply")?.addEventListener("click", async (event) => {
        event.currentTarget.disabled = true;
        setBusy(true);
        try {
          await refactorApi("/api/refactor/apply", { operationId: refactorOperationId });
          window.location.reload();
        } catch (error) {
          showError(error.message);
          setBusy(false);
        }
      });
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(false);
    }
  };

  trigger.setAttribute("aria-expanded", "false");
  trigger.addEventListener("click", () => {
    const opening = editor.classList.contains("is-hidden");
    if (!opening) {
      reset();
      return;
    }
    editor.classList.remove("is-hidden");
    trigger.setAttribute("aria-expanded", "true");
    input.focus();
  });
  input.addEventListener("input", () => {
    refactorOperationId = "";
    result.innerHTML = "";
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") preview();
    if (event.key === "Escape") reset();
  });
  previewButton.addEventListener("click", preview);
  cancelButton.addEventListener("click", reset);
}

function renderPlaceList() {
  if (!placeList) return;
  const discoveredTypes = [...new Set(places.map((place) => place.type).filter(Boolean))];
  const entryTypes = [
    ...ENTRY_TYPES.filter((type) => discoveredTypes.includes(type)),
    ...discoveredTypes.filter((type) => !ENTRY_TYPES.includes(type)),
  ];
  renderChipFilter({
    container: entryTypeFilter,
    label: "类型",
    items: entryTypes,
    selected: state.entryType,
    onChange: (value) => {
      state.entryType = value;
      renderPlaceList();
      renderPlaceDetail();
    },
  });

  const entryTags = allEntryTags();
  renderChipFilter({
    container: entryTagFilter,
    label: "标签",
    items: entryTags,
    selected: state.entryTags,
    mode: "multi",
    onChange: (value) => {
      state.entryTags = nextSelectedTags(state.entryTags, entryTags, value);
      renderPlaceList();
      renderPlaceDetail();
    },
  });

  const visiblePlaces = places.filter((place) => {
    if (state.entryType !== "all" && place.type !== state.entryType) return false;
    if (!matchesSelectedTags(place.tags || [], state.entryTags, entryTags)) return false;
    if (!state.placeSearch) return true;
    const keyword = state.placeSearch.toLowerCase();
    return [
      place.name,
      place.id,
      place.type,
      place.subtype,
      place.area,
      place.intro,
      ...(place.tags || []),
      ...(place.aliases || []),
    ]
      .filter(Boolean)
      .some((text) => String(text).toLowerCase().includes(keyword));
  });

  if (visiblePlaces.length && !visiblePlaces.some((place) => place.id === state.selectedPlace)) {
    state.selectedPlace = visiblePlaces[0].id;
  }

  placeList.innerHTML = visiblePlaces
    .map((place) => `
      <button class="place-list-item ${place.id === state.selectedPlace ? "is-active" : ""}" data-id="${escapeHtml(place.id)}" type="button" style="--accent:${escapeHtml(place.accent)}">
        <span class="place-mini-symbol">${escapeHtml(place.name).slice(0, 2)}</span>
        <span>
          <strong>${escapeHtml(place.name)}</strong>
          <small>${escapeHtml(place.type || "未分类")}${place.subtype ? ` · ${escapeHtml(place.subtype)}` : ""} · ${escapeHtml(place.area || "未分区")}</small>
        </span>
      </button>
    `)
    .join("");

  if (!visiblePlaces.length) {
    placeList.innerHTML = '<p class="empty-state">没有找到匹配设定</p>';
  }

  document.querySelectorAll(".place-list-item").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedPlace = button.dataset.id;
      renderPlaceList();
      renderPlaceDetail();
    });
  });
}

function renderPlaceDetail() {
  if (!placeDetail) return;
  const place = getPlace(state.selectedPlace) || places[0];
  if (!place) {
    placeDetail.innerHTML = "";
    return;
  }

  const placePlots = plots.filter((plot) => (plot.entries || []).includes(place.id) || place.plots.includes(plot.id));
  const relatedPeopleIds = [...new Set([
    ...(place.people || []),
    ...placePlots.flatMap((plot) => plot.people || []),
  ])];
  const relatedPeople = relatedPeopleIds.map((id) => ({ id, person: getCharacter(id) }));

  placeDetail.innerHTML = `
    ${detailReturnButton()}
    <div class="place-hero" style="--accent:${escapeHtml(place.accent)}">
      <div class="place-symbol ${entrySymbolClass(place.type)}" aria-label="${escapeHtml(place.type || "设定")}">
        <span class="place-symbol-glyph" aria-hidden="true"></span>
        <span class="place-symbol-label">${escapeHtml(place.type || "设定")}</span>
      </div>
      <div class="character-copy">
        <p class="label">${escapeHtml(place.type || "未分类")}${place.subtype ? ` · ${escapeHtml(place.subtype)}` : ""} · ${escapeHtml(place.area || "未分区")}</p>
        <h2>${escapeHtml(place.name)}</h2>
        <div class="place-intro">${renderMarkdownBody(place.intro)}</div>
        <div class="place-facts">
          ${(place.tags || []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}
          ${(place.aliases || []).map((alias) => `<span>别名：${escapeHtml(alias)}</span>`).join("")}
          ${place.status ? `<span>${escapeHtml(place.status)}</span>` : ""}
        </div>
      </div>
    </div>

    <section class="character-section">
      <div class="section-title">
        <p class="label">相关人物</p>
        <h3>${relatedPeople.filter(({ person }) => person).length} 个角色</h3>
      </div>
      <div class="place-person-grid">
        ${relatedPeople.map(({ id, person }) => {
          if (!person) {
            return `
              <div class="plot-person-item">
                <span class="mini-avatar" style="--avatar-gradient:linear-gradient(135deg, #9aa6b2, #65717d)">${escapeHtml(id).slice(0, 2)}</span>
                <span>
                  <strong>${escapeHtml(id)}</strong>
                  <small>未在人物列表中</small>
                </span>
              </div>
            `;
          }
          return `
            <button class="plot-person-item" data-id="${escapeHtml(person.id)}" type="button">
              <span class="mini-avatar" style="--avatar-gradient:${escapeHtml(person.gradient)}">${avatarContent(person)}</span>
              <span>
                <strong>${escapeHtml(person.name)}</strong>
                <small>${escapeHtml(person.group || "未分组")}</small>
              </span>
            </button>
          `;
        }).join("") || '<p class="empty-state">这个设定还没有关联人物。</p>'}
      </div>
    </section>

    <section class="character-section">
      <div class="section-title">
        <p class="label">出现剧情</p>
        <h3>${placePlots.length} 个剧情点</h3>
      </div>
      <div class="character-plot-list">
        ${placePlots.map((plot) => `
          <button class="${storyCardClass(plot, "character-plot detail-plot-card place-plot-card")}" data-plot-id="${escapeHtml(plot.id)}" type="button" style="--accent:${escapeHtml(plot.accent)}">
            ${renderStoryCardContent(plot, { heading: "strong", titlePrefix: `${plot.id}. ` })}
          </button>
        `).join("") || '<p class="empty-state">这个设定还没有配置出现剧情。</p>'}
      </div>
    </section>
  `;

  document.querySelectorAll(".place-person-grid .plot-person-item[data-id]").forEach((button) => {
    button.addEventListener("click", () => openCharacterDetail(button.dataset.id, {
      preserveReturnContext: Boolean(state.detailReturnContext),
    }));
  });
  document.querySelectorAll(".place-plot-card[data-plot-id]").forEach((button) => {
    button.addEventListener("click", () => openPlotDetail(Number(button.dataset.plotId)));
  });
  placeDetail.querySelector(".return-to-plot-btn")?.addEventListener("click", returnToPlotContext);
}

function switchView(view) {
  const previousView = state.view;
  const activeNav = view === "plot-detail" ? "story" : view;
  document.querySelector("#readingProgress")?.classList.toggle("is-hidden", view !== "plot-detail");
  document.querySelectorAll(".view-btn").forEach((item) => item.classList.toggle("is-active", item.dataset.view === activeNav));
  document.querySelectorAll(".page-view").forEach((page) => page.classList.toggle("is-active", page.dataset.page === view));
  state.view = view;

  if (state.view === "graph") {
    updateGraphBounds();
    if (state.selected) selectPerson(state.selected);
    drawGraph();
    startGraphLoop();
  }
  if (state.view === "timeline") {
    requestTimelineRender();
  } else {
    timelineRenderVersion += 1;
    suspendTimelineViewport();
    timelineLegend?.classList.add("is-hidden");
  }
  if (state.view === "characters") {
    if (!state.selectedCharacter) state.selectedCharacter = state.selected || characters[0]?.id || "";
    renderCharacterList();
    renderCharacterDetail();
  }
  if (state.view === "places") {
    if (!state.selectedPlace) state.selectedPlace = places[0]?.id || "";
    renderPlaceList();
    renderPlaceDetail();
  }
  if (state.view === "fragments") {
    renderFragmentFilters();
    renderFragments();
  }
  if (state.view === "diagnostics") {
    requestDiagnosticsRender();
  }
  if (state.view === "story" && previousView !== "story" && previousView !== "plot-detail") {
    state.plotTags = allPlotTags();
    state.plotPage = 1;
    renderChapterSwitch();
    renderStoryFilters();
    renderPlots();
  }
  if (state.view === "plot-detail") renderPlotDetail();
  scrollPageToTop();
}

function renderProfile() {
  if (!state.hasSelection) {
    profileFloat.classList.add("is-hidden");
    return;
  }

  const person = getCharacter(state.selected);
  if (!person) return;
  const items = plots.filter((plot) => person.events.includes(plot.id));

  personName.textContent = person.name;
  personIntro.textContent = person.intro;
  personAvatar.innerHTML = avatarContent(person);
  personAvatar.classList.toggle("has-image", Boolean(person.avatar));
  personAvatar.style.setProperty("--selected-gradient", person.gradient);

  eventList.innerHTML = items
    .map((plot, index) => `
      <article class="event-item" style="--accent:${escapeHtml(plot.accent)}; animation-delay:${index * 70}ms">
        <span class="event-dot"></span>
        <p>${escapeHtml(plot.title)}：${escapeHtml(markdownExcerpt(plot.text, 120))}</p>
      </article>
    `)
    .join("");
  profileFloat.classList.remove("is-hidden");
}

function renderNodes() {
  nodeLayer.innerHTML = "";
  characters.forEach((person, index) => {
    const node = document.createElement("button");
    node.className = "person-node";
    node.type = "button";
    node.dataset.id = person.id;
    node.style.setProperty("--accent", person.color);
    node.style.setProperty("--avatar-gradient", person.gradient);
    node.style.animationDelay = `${index * 90}ms, ${index * 170}ms`;
    node.innerHTML = `
      <span class="avatar ${person.avatar ? "has-image" : ""}">${avatarContent(person)}</span>
      <span class="node-name">${escapeHtml(person.name)}</span>
    `;
    node.addEventListener("pointerdown", startDrag);
    node.addEventListener("click", () => {
      if (state.suppressClickId === person.id && Date.now() < state.suppressClickUntil) {
        state.suppressClickId = "";
        state.suppressClickUntil = 0;
        return;
      }
      state.suppressClickId = "";
      state.suppressClickUntil = 0;
      selectPerson(person.id);
    });
    nodeLayer.appendChild(node);
  });
  updateGraphBounds();
  applyGraphFilters();
}

function renderLinks() {
  drawGraph();
}

function selectPerson(id) {
  const person = getCharacter(id);
  if (!person) return;
  state.selected = id;
  state.hasSelection = true;
  state.selectedCharacter = id;
  centerViewportOn(person);
  renderProfile();
  markRelatedNodes();
}

function clearGraphSelection() {
  state.selected = "";
  state.hasSelection = false;
  profileFloat.classList.add("is-hidden");
  markRelatedNodes();
}

function graphReachability() {
  const direct = new Set(state.hasSelection ? [state.selected] : []);
  const reachable = new Set(state.hasSelection ? [state.selected] : []);
  if (state.hasSelection) {
    const queue = [state.selected];
    while (queue.length) {
      const current = queue.shift();
      relationships.forEach((link) => {
        const next = link.from === current ? link.to : link.to === current ? link.from : "";
        if (!next) return;
        if (current === state.selected) direct.add(next);
        if (!reachable.has(next)) {
          reachable.add(next);
          queue.push(next);
        }
      });
    }
  }
  return { direct, reachable };
}

function markRelatedNodes() {
  const { direct, reachable } = graphReachability();
  document.querySelectorAll(".person-node").forEach((node) => {
    const id = node.dataset.id;
    const person = getCharacter(id);
    node.classList.toggle("is-active", state.hasSelection && id === state.selected);
    node.classList.toggle("is-linked", direct.has(id) && id !== state.selected);
    node.classList.toggle("is-reachable", reachable.has(id) && id !== state.selected);
    node.classList.toggle("is-muted-by-selection", state.hasSelection && !reachable.has(id));
    node.classList.toggle("is-pinned", Boolean(person?.pinned));
  });
  applyGraphFilters();
}

function applyGraphFilters() {
  document.querySelectorAll(".person-node").forEach((node) => {
    const person = getCharacter(node.dataset.id);
    const visible = Boolean(person && isVisiblePerson(person));
    node.classList.toggle("is-filtered-out", !visible);
    node.classList.toggle("is-search-match", Boolean(state.search && visible));
  });

  drawGraph();
}

function updateGraphBounds() {
  const bounds = graphWrap.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return;
  state.width = bounds.width;
  state.height = bounds.height;

  characters.forEach((person, index) => {
    if (!Number.isFinite(person.px) || !Number.isFinite(person.py)) {
      const hasConfiguredPosition = Number.isFinite(Number(person.x)) && Number.isFinite(Number(person.y));
      const goldenAngle = Math.PI * (3 - Math.sqrt(5));
      const progress = Math.sqrt((index + 0.5) / Math.max(1, characters.length));
      const radius = Math.min(state.width, state.height) * (0.08 + progress * 0.34);
      const angle = index * goldenAngle + stableNoise(person.id, "initial-angle") * 0.28;
      const baseX = hasConfiguredPosition
        ? (Number(person.x) / 100) * state.width
        : state.width / 2 + Math.cos(angle) * radius;
      const baseY = hasConfiguredPosition
        ? (Number(person.y) / 100) * state.height
        : state.height / 2 + Math.sin(angle) * radius;
      const point = jitterPoint(
        baseX,
        baseY,
        person.id,
        Number(graphLayoutConfig.initialJitter || 34),
        "initial",
      );
      person.px = point.x;
      person.py = point.y;
    }
    person.vx = person.vx || 0;
    person.vy = person.vy || 0;
    person.pinned = Boolean(person.pinned);
  });
  updateGraphViewport();
  wakeGraphSimulation();
}

function clientToWorld(clientX, clientY) {
  const bounds = graphWrap.getBoundingClientRect();
  return {
    x: (clientX - bounds.left - state.graphPanX) / state.graphScale,
    y: (clientY - bounds.top - state.graphPanY) / state.graphScale,
  };
}

function centerViewportOn(person) {
  if (!state.width || !state.height) return;
  state.graphPanX = state.width / 2 - person.px * state.graphScale;
  state.graphPanY = state.height / 2 - person.py * state.graphScale;
  updateGraphViewport();
}

function updateGraphViewport() {
  if (!state.width || !state.height) return;
  nodeLayer.style.transform = `translate(${state.graphPanX}px, ${state.graphPanY}px) scale(${state.graphScale})`;
  graphWrap.classList.toggle("hide-labels", characters.length > 10 || state.graphScale < 0.75);
}

function canMovePerson(person) {
  return state.dragging?.id !== person.id && !person.pinned;
}

function pushPerson(person, vx, vy) {
  if (!person || !canMovePerson(person)) return;
  person.vx += vx;
  person.vy += vy;
}

function nudgeToward(person, x, y, strength = 0.02) {
  if (!person || !canMovePerson(person)) return;
  const vx = (x - person.px) * strength;
  const vy = (y - person.py) * strength;
  const force = Math.max(1, Math.hypot(vx, vy));
  const capped = Math.min(8, force);
  person.vx += (vx / force) * capped;
  person.vy += (vy / force) * capped;
}

function applyPairDistance(a, b, targetDistance, strength = 0.45) {
  if (!a || !b || !targetDistance) return;
  const dx = b.px - a.px;
  const dy = b.py - a.py;
  const distance = Math.max(1, Math.hypot(dx, dy));
  const force = (distance - targetDistance) * 0.00045 * strength;
  const nx = dx / distance;
  const ny = dy / distance;
  pushPerson(a, nx * force, ny * force);
  pushPerson(b, -nx * force, -ny * force);
}

function applyNaturalGroupForces() {
  const groups = new Map();
  characters.forEach((person) => {
    if (!person.group) return;
    if (!groups.has(person.group)) groups.set(person.group, []);
    groups.get(person.group).push(person);
  });

  groups.forEach((members) => {
    if (members.length < 2) return;
    const center = members.reduce((sum, person) => ({
      x: sum.x + person.px,
      y: sum.y + person.py,
    }), { x: 0, y: 0 });
    center.x /= members.length;
    center.y /= members.length;
    members.forEach((person) => nudgeToward(person, center.x, center.y, 0.0018));
  });
}

function graphPoint(percentX = 50, percentY = 50) {
  return {
    x: (Number(percentX) / 100) * state.width,
    y: (Number(percentY) / 100) * state.height,
  };
}

function stableNoise(key, salt = "") {
  const text = `${key}:${salt}`;
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) / 4294967295) * 2 - 1;
}

function jitterPoint(x, y, id, jitter = 0, salt = "") {
  const amount = Number(jitter || 0);
  if (!amount) return { x, y };
  return {
    x: x + stableNoise(id, `${salt}:x`) * amount,
    y: y + stableNoise(id, `${salt}:y`) * amount,
  };
}

function formationAngle(formation) {
  if (formation.angle !== undefined) return (Number(formation.angle) * Math.PI) / 180;
  if (formation.direction === "vertical") return Math.PI / 2;
  return 0;
}

function nudgeFormationMember(id, x, y, strength) {
  nudgeToward(getCharacter(id), x, y, strength);
}

function formationCenter(formation) {
  const anchor = getCharacter(formation.anchorNode || formation.bindMember || "");
  const offsetX = Number(formation.offsetX || 0);
  const offsetY = Number(formation.offsetY || 0);
  if (anchor) return { x: anchor.px + offsetX, y: anchor.py + offsetY };
  return graphPoint(formation.centerX ?? 50, formation.centerY ?? 50);
}

function placeFormationMember(formation, id, x, y, strength) {
  if (!id) return;
  const point = jitterPoint(x, y, id, formation.jitter ?? 18, formation.id || formation.type);
  nudgeFormationMember(id, point.x, point.y, strength);
}

function applyPairFormation(formation) {
  const members = formation.members || [];
  if (members.length < 2) return;
  const center = formationCenter(formation);
  const distance = Number(formation.distance || 260);
  const angle = formationAngle(formation);
  const strength = Number(formation.strength || 0.8);
  const nudgeStrength = 0.045 * strength;
  const dx = Math.cos(angle) * distance * 0.5;
  const dy = Math.sin(angle) * distance * 0.5;
  placeFormationMember(formation, members[0], center.x - dx, center.y - dy, nudgeStrength);
  placeFormationMember(formation, members[1], center.x + dx, center.y + dy, nudgeStrength);
  applyPairDistance(getCharacter(members[0]), getCharacter(members[1]), distance, Math.max(0.55, strength));
}

function applyCrossFormation(formation) {
  const center = formationCenter(formation);
  const spacing = Number(formation.spacing || 220);
  const strength = 0.04 * Number(formation.strength || 0.75);
  placeFormationMember(formation, formation.center, center.x, center.y, strength);
  placeFormationMember(formation, formation.north, center.x, center.y - spacing, strength);
  placeFormationMember(formation, formation.south, center.x, center.y + spacing, strength);
  placeFormationMember(formation, formation.west, center.x - spacing, center.y, strength);
  placeFormationMember(formation, formation.east, center.x + spacing, center.y, strength);
}

function applyRadialFormation(formation, options = {}) {
  const members = formation.members || [];
  if (!members.length) return;
  const center = formationCenter(formation);
  const radius = Number(formation.radius || 230);
  const startAngle = ((Number(formation.startAngle ?? -90) * Math.PI) / 180);
  const strength = 0.038 * Number(formation.strength || 0.72);
  if (options.centerMember) {
    placeFormationMember(formation, options.centerMember, center.x, center.y, strength);
  }
  members.forEach((id, index) => {
    const angle = startAngle + (Math.PI * 2 * index) / members.length;
    placeFormationMember(
      formation,
      id,
      center.x + Math.cos(angle) * radius,
      center.y + Math.sin(angle) * radius,
      strength,
    );
  });
}

function applyStarFormation(formation) {
  applyRadialFormation(formation, { centerMember: formation.center });
}

function applyRingFormation(formation) {
  applyRadialFormation(formation);
}

function applyTriangleFormation(formation) {
  const members = formation.members || [];
  if (members.length < 3) return;
  applyRadialFormation({ ...formation, members: members.slice(0, 3), radius: formation.radius || 190, startAngle: formation.startAngle ?? -90 });
}

function applyChainFormation(formation) {
  const members = formation.members || [];
  if (!members.length) return;
  const center = formationCenter(formation);
  const spacing = Number(formation.spacing || 180);
  const angle = formationAngle(formation);
  const strength = 0.038 * Number(formation.strength || 0.72);
  const mid = (members.length - 1) / 2;
  members.forEach((id, index) => {
    const offset = (index - mid) * spacing;
    placeFormationMember(
      formation,
      id,
      center.x + Math.cos(angle) * offset,
      center.y + Math.sin(angle) * offset,
      strength,
    );
  });
}

function applyFormationForces() {
  (graphLayoutConfig.formations || []).forEach((formation) => {
    if (formation.type === "pair") applyPairFormation(formation);
    if (formation.type === "cross") applyCrossFormation(formation);
    if (formation.type === "star") applyStarFormation(formation);
    if (formation.type === "ring") applyRingFormation(formation);
    if (formation.type === "chain") applyChainFormation(formation);
    if (formation.type === "triangle") applyTriangleFormation(formation);
  });
}

function applyConfiguredDistanceForces() {
  (graphLayoutConfig.distances || []).forEach((rule) => {
    applyPairDistance(
      getCharacter(rule.from),
      getCharacter(rule.to),
      Number(rule.distance),
      Number(rule.strength || 0.7),
    );
  });
}

function clusterCenter(cluster, members) {
  const hasCenter = cluster.centerX !== undefined && cluster.centerY !== undefined;
  if (hasCenter) {
    return {
      x: (Number(cluster.centerX) / 100) * state.width,
      y: (Number(cluster.centerY) / 100) * state.height,
    };
  }
  if (!members.length) return { x: state.width / 2, y: state.height / 2 };
  const center = members.reduce((sum, person) => ({
    x: sum.x + person.px,
    y: sum.y + person.py,
  }), { x: 0, y: 0 });
  return {
    x: center.x / members.length,
    y: center.y / members.length,
  };
}

function applyClusterForces() {
  (graphLayoutConfig.clusters || []).forEach((cluster) => {
    const members = (cluster.members || [])
      .map((id) => getCharacter(id))
      .filter(Boolean);
    if (!members.length) return;
    const center = clusterCenter(cluster, members);
    const radius = Number(cluster.radius || 180);
    const strength = Number(cluster.strength || 0.42);

    members.forEach((person, index) => {
      const angle = (Math.PI * 2 * index) / Math.max(1, members.length);
      const targetRadius = radius * (members.length > 2 ? 0.42 : 0.28);
      nudgeToward(
        person,
        center.x + Math.cos(angle) * targetRadius,
        center.y + Math.sin(angle) * targetRadius,
        0.006 * strength,
      );
    });

    members.forEach((a, index) => {
      members.slice(index + 1).forEach((b) => {
        applyPairDistance(a, b, Math.max(110, radius * 0.72), 0.16 * strength);
      });
    });
  });
}

function applyOrbitForces() {
  (graphLayoutConfig.nodes || []).forEach((rule) => {
    const person = getCharacter(rule.id);
    const anchor = getCharacter(rule.orbitOf);
    if (!person || !anchor) return;
    const distance = Number(rule.orbitDistance || 260);
    const angle = (Number(rule.orbitAngle || 0) * Math.PI) / 180;
    nudgeToward(
      person,
      anchor.px + Math.cos(angle) * distance,
      anchor.py + Math.sin(angle) * distance,
      Number(rule.strength || 0.026),
    );
  });
}

function applyGraphLayoutForces() {
  applyNaturalGroupForces();
  applyFormationForces();
  applyClusterForces();
  applyConfiguredDistanceForces();
  applyOrbitForces();
}

function forEachNearbyCharacterPair(maxDistance, callback) {
  const cellSize = Math.max(1, maxDistance);
  const buckets = new Map();
  characters.forEach((person, index) => {
    if (!Number.isFinite(person.px) || !Number.isFinite(person.py)) return;
    const cellX = Math.floor(person.px / cellSize);
    const cellY = Math.floor(person.py / cellSize);
    const key = `${cellX}:${cellY}`;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push({ person, index, cellX, cellY });
  });

  buckets.forEach((items) => {
    items.forEach((first) => {
      for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
        for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
          const nearby = buckets.get(`${first.cellX + offsetX}:${first.cellY + offsetY}`) || [];
          nearby.forEach((second) => {
            if (second.index <= first.index) return;
            callback(first.person, second.person);
          });
        }
      }
    });
  });
}

function separationVector(a, b) {
  const dx = b.px - a.px;
  const dy = b.py - a.py;
  const rawDistance = Math.hypot(dx, dy);
  if (rawDistance > 0.001) {
    return { distance: rawDistance, nx: dx / rawDistance, ny: dy / rawDistance };
  }
  const angle = (stableNoise(`${a.id}:${b.id}`, "overlap") + 1) * Math.PI;
  return { distance: 0, nx: Math.cos(angle), ny: Math.sin(angle) };
}

function separateOverlappingNodes() {
  const minDistance = Number(graphLayoutConfig.nodeSpacing || 116);
  forEachNearbyCharacterPair(minDistance, (a, b) => {
    const { distance, nx, ny } = separationVector(a, b);
    if (distance >= minDistance) return;
    const overlap = (minDistance - distance) * 0.52;
    const aCanMove = canMovePerson(a);
    const bCanMove = canMovePerson(b);
    if (aCanMove && bCanMove) {
      a.px -= nx * overlap * 0.5;
      a.py -= ny * overlap * 0.5;
      b.px += nx * overlap * 0.5;
      b.py += ny * overlap * 0.5;
      return;
    }
    if (aCanMove) {
      a.px -= nx * overlap;
      a.py -= ny * overlap;
    }
    if (bCanMove) {
      b.px += nx * overlap;
      b.py += ny * overlap;
    }
  });
}

function resolvePinnedNodeOverlap(person) {
  const minDistance = Number(graphLayoutConfig.nodeSpacing || 116);
  for (let pass = 0; pass < 4; pass += 1) {
    let moved = false;
    characters.forEach((other) => {
      if (other === person || !Number.isFinite(other.px) || !Number.isFinite(other.py)) return;
      const vector = separationVector(other, person);
      if (vector.distance >= minDistance) return;
      person.px += vector.nx * (minDistance - vector.distance + 2);
      person.py += vector.ny * (minDistance - vector.distance + 2);
      moved = true;
    });
    if (!moved) break;
  }
}

function startDrag(event) {
  event.stopPropagation();
  const id = event.currentTarget.dataset.id;
  state.dragging = {
    id,
    pointerId: event.pointerId,
    startClientX: event.clientX,
    startClientY: event.clientY,
    moved: false,
  };
  wakeGraphSimulation();
  event.currentTarget.setPointerCapture(event.pointerId);
}

graphWrap.addEventListener("pointerdown", (event) => {
  if (event.target.closest(".person-node, .profile-float")) return;
  state.panning = {
    startClientX: event.clientX,
    startClientY: event.clientY,
    startPanX: state.graphPanX,
    startPanY: state.graphPanY,
    moved: false,
  };
});

graphWrap.addEventListener("wheel", (event) => {
  event.preventDefault();
  const bounds = graphWrap.getBoundingClientRect();
  const cursorX = event.clientX - bounds.left;
  const cursorY = event.clientY - bounds.top;
  const before = clientToWorld(event.clientX, event.clientY);
  const nextScale = Math.min(4.8, Math.max(0.18, state.graphScale * Math.exp(-event.deltaY * 0.0012)));

  state.graphScale = nextScale;
  state.graphPanX = cursorX - before.x * nextScale;
  state.graphPanY = cursorY - before.y * nextScale;
  updateGraphViewport();
}, { passive: false });

window.addEventListener("pointermove", (event) => {
  if (state.panning) {
    if (Math.hypot(event.clientX - state.panning.startClientX, event.clientY - state.panning.startClientY) > 5) {
      state.panning.moved = true;
    }
    state.graphPanX = state.panning.startPanX + event.clientX - state.panning.startClientX;
    state.graphPanY = state.panning.startPanY + event.clientY - state.panning.startClientY;
    updateGraphViewport();
    return;
  }

  if (state.dragging) {
    const person = getCharacter(state.dragging.id);
    if (!person) return;
    const moveDistance = Math.hypot(event.clientX - state.dragging.startClientX, event.clientY - state.dragging.startClientY);
    if (moveDistance > 5) state.dragging.moved = true;
    const point = clientToWorld(event.clientX, event.clientY);
    person.px = point.x;
    person.py = point.y;
    person.vx = 0;
    person.vy = 0;
  }
});

window.addEventListener("pointerup", () => {
  if (state.panning && !state.panning.moved) clearGraphSelection();
  if (state.dragging?.moved) {
    const person = getCharacter(state.dragging.id);
    if (person) {
      resolvePinnedNodeOverlap(person);
      person.pinned = true;
      person.vx = 0;
      person.vy = 0;
      person.x = (person.px / state.width) * 100;
      person.y = (person.py / state.height) * 100;
    }
    state.suppressClickId = state.dragging.id;
    state.suppressClickUntil = Date.now() + 250;
    markRelatedNodes();
    wakeGraphSimulation();
  }
  state.dragging = null;
  state.panning = null;
});

function wakeGraphSimulation() {
  graphSimulationActive = true;
  graphSimulationTicks = 0;
  graphStableFrames = 0;
  startGraphLoop();
}

function startGraphLoop() {
  if (!graphAnimationFrame && state.view === "graph" && !document.hidden) {
    graphAnimationFrame = requestAnimationFrame(tick);
  }
}

function stepGraphSimulation() {
  forEachNearbyCharacterPair(150, (a, b) => {
    const { distance: rawDistance, nx, ny } = separationVector(b, a);
    const distance = Math.max(1, rawDistance);
    const push = Math.max(0, 150 - distance) * 0.0009;
    const selectedPush = state.hasSelection && (a.id === state.selected || b.id === state.selected) ? 0.004 : 0;
    pushPerson(a, nx * push, ny * push);
    pushPerson(b, -nx * push, -ny * push);
    if (selectedPush) {
      pushPerson(a, nx * selectedPush, ny * selectedPush);
      pushPerson(b, -nx * selectedPush, -ny * selectedPush);
    }
  });

  relationships.forEach((link) => {
    const a = getCharacter(link.from);
    const b = getCharacter(link.to);
    if (!a || !b) return;
    applyPairDistance(a, b, Number(link.distance || 250), Number(link.strength || 1));
  });

  applyGraphLayoutForces();

  let maxSpeed = 0;
  characters.forEach((person) => {
    if (canMovePerson(person)) {
      person.vx *= 0.91;
      person.vy *= 0.91;
      person.px += person.vx;
      person.py += person.vy;
      maxSpeed = Math.max(maxSpeed, Math.hypot(person.vx, person.vy));
    }
  });

  separateOverlappingNodes();

  characters.forEach((person) => {
    person.x = (person.px / state.width) * 100;
    person.y = (person.py / state.height) * 100;
  });

  graphSimulationTicks += 1;
  graphStableFrames = maxSpeed < 0.018 ? graphStableFrames + 1 : 0;
  if (graphStableFrames >= GRAPH_STABLE_FRAME_TARGET || graphSimulationTicks >= GRAPH_MAX_SIMULATION_TICKS) {
    graphSimulationActive = false;
  }
}

function tick(time) {
  graphAnimationFrame = 0;
  if (state.view !== "graph" || document.hidden) return;
  if (!state.width || !state.height) {
    startGraphLoop();
    return;
  }

  if (graphSimulationActive) stepGraphSimulation();
  if (graphSimulationActive || time - graphLastRenderTime >= GRAPH_EFFECT_FRAME_INTERVAL) {
    drawGraph(time);
    graphLastRenderTime = time;
  }
  if (graphSimulationActive || !reducedMotionQuery.matches) startGraphLoop();
}

function graphRenderScene(time = performance.now()) {
  const { direct, reachable } = graphReachability();
  const hasPosition = (person) => Number.isFinite(person?.px) && Number.isFinite(person?.py);
  const visibleCharacters = characters.filter((person) => isVisiblePerson(person) && hasPosition(person));
  const nodes = visibleCharacters.map((person) => {
    const isSelected = state.hasSelection && person.id === state.selected;
    const isDirect = state.hasSelection && direct.has(person.id) && !isSelected;
    const isReachable = state.hasSelection && reachable.has(person.id) && !isSelected && !isDirect;
    return {
      id: person.id,
      x: person.px,
      y: person.py,
      color: person.color,
      radius: isSelected ? 172 : isDirect ? 142 : isReachable ? 116 : 104,
      strength: isSelected ? 0.92 : isDirect ? 0.56 : isReachable ? 0.3 : 0.18,
    };
  });
  const edges = relationships.map((link) => {
    const from = getCharacter(link.from);
    const to = getCharacter(link.to);
    const highlighted = state.hasSelection && reachable.has(link.from) && reachable.has(link.to);
    return {
      from: { id: from?.id, x: from?.px || 0, y: from?.py || 0 },
      to: { id: to?.id, x: to?.px || 0, y: to?.py || 0 },
      color: link.color || "#65717d",
      visible: Boolean(from && to && hasPosition(from) && hasPosition(to) && isVisibleRelationship(link)),
      highlighted,
      muted: state.hasSelection && !highlighted,
    };
  });
  return {
    width: state.width,
    height: state.height,
    scale: state.graphScale,
    panX: state.graphPanX,
    panY: state.graphPanY,
    time,
    nodes,
    edges,
  };
}

function drawGraph(time = performance.now()) {
  updateGraphViewport();
  document.querySelectorAll(".person-node").forEach((node) => {
    const person = getCharacter(node.dataset.id);
    if (!person || !Number.isFinite(person.px) || !Number.isFinite(person.py)) return;
    node.style.left = `${person.px}px`;
    node.style.top = `${person.py}px`;
  });
  graphRenderer?.render(graphRenderScene(time));
}

globalSearch?.addEventListener("input", () => {
  state.globalSearch = globalSearch.value.trim();
  renderGlobalSearchResults();
});

globalSearch?.addEventListener("search", () => {
  state.globalSearch = globalSearch.value.trim();
  renderGlobalSearchResults();
});

globalSearch?.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    globalSearch.value = "";
    state.globalSearch = "";
    hideGlobalSearchResults();
  }
});

document.addEventListener("click", (event) => {
  if (event.target.closest(".global-search")) return;
  hideGlobalSearchResults();
});

window.addEventListener("pageshow", scrollPageToTop);
window.addEventListener("load", scrollPageToTop);

graphSearch.addEventListener("input", () => {
  state.search = graphSearch.value.trim();
  applyGraphFilters();
});

graphSearch.addEventListener("search", () => {
  state.search = graphSearch.value.trim();
  applyGraphFilters();
});

groupFilter.addEventListener("change", () => {
  state.group = groupFilter.value;
  applyGraphFilters();
});

relationFilter.addEventListener("change", () => {
  state.relationType = relationFilter.value;
  applyGraphFilters();
});

characterSearch.addEventListener("input", () => {
  state.characterSearch = characterSearch.value.trim();
  renderCharacterList();
  renderCharacterDetail();
});

characterSearch.addEventListener("search", () => {
  state.characterSearch = characterSearch.value.trim();
  renderCharacterList();
  renderCharacterDetail();
});

placeSearch?.addEventListener("input", () => {
  state.placeSearch = placeSearch.value.trim();
  renderPlaceList();
  renderPlaceDetail();
});

placeSearch?.addEventListener("search", () => {
  state.placeSearch = placeSearch.value.trim();
  renderPlaceList();
  renderPlaceDetail();
});

timelineList?.addEventListener("scroll", () => scheduleTimelineViewportRender());
window.addEventListener("scroll", () => {
  scheduleTimelineViewportRender();
  updateReadingProgress();
});
window.addEventListener("resize", () => {
  scheduleTimelineViewportRender(true);
  updateReadingProgress();
});

function runAmbientCanvas() {
  const canvas = document.querySelector("#ambientCanvas");
  const ctx = canvas?.getContext?.("2d");
  if (!canvas || !ctx) return;
  let ambientFrame = 0;
  let lastPaint = 0;
  const particles = Array.from({ length: 78 }, (_, index) => ({
    x: Math.random(),
    y: Math.random(),
    r: 1.2 + Math.random() * 2.8,
    speed: 0.001 + Math.random() * 0.002,
    phase: index * 0.4,
    color: ["rgba(42, 157, 143, 0.32)", "rgba(231, 111, 81, 0.24)", "rgba(69, 123, 157, 0.25)", "rgba(233, 196, 106, 0.28)"][index % 4],
  }));

  function resize() {
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = window.innerWidth * ratio;
    canvas.height = window.innerHeight * ratio;
    canvas.style.width = `${window.innerWidth}px`;
    canvas.style.height = `${window.innerHeight}px`;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  function paint(time) {
    ambientFrame = 0;
    if (document.hidden) return;
    if (!reducedMotionQuery.matches && time - lastPaint < GRAPH_EFFECT_FRAME_INTERVAL) {
      ambientFrame = requestAnimationFrame(paint);
      return;
    }
    lastPaint = time;
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    particles.forEach((particle) => {
      const motionTime = reducedMotionQuery.matches ? 0 : time;
      const drift = Math.sin(motionTime * particle.speed + particle.phase) * 26;
      const x = particle.x * window.innerWidth + drift;
      const y = ((particle.y + motionTime * particle.speed * 0.018) % 1) * window.innerHeight;
      ctx.beginPath();
      ctx.fillStyle = particle.color;
      ctx.arc(x, y, particle.r, 0, Math.PI * 2);
      ctx.fill();
    });
    if (!reducedMotionQuery.matches) ambientFrame = requestAnimationFrame(paint);
  }

  function start() {
    if (!ambientFrame && !document.hidden) ambientFrame = requestAnimationFrame(paint);
  }

  window.addEventListener("resize", () => {
    resize();
    start();
  });
  document.addEventListener("visibilitychange", start);
  reducedMotionQuery.addEventListener("change", start);
  resize();
  start();
}

window.addEventListener("resize", () => {
  if (state.view === "graph") {
    updateGraphBounds();
    drawGraph();
  }
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && state.view === "graph") startGraphLoop();
});

reducedMotionQuery.addEventListener("change", (event) => {
  if (graphRenderer) graphRenderer.reducedMotion = event.matches;
  drawGraph();
  if (!event.matches) startGraphLoop();
});

document.querySelectorAll(".view-btn").forEach((button) => {
  button.addEventListener("click", () => {
    rememberCurrentPlotPosition();
    state.detailReturnContext = null;
    state.highlightedReferenceType = "";
    state.highlightedReferenceId = "";
    switchView(button.dataset.view);
  });
});

timelineDirectionBtn?.addEventListener("click", () => {
  state.timelineReversed = !state.timelineReversed;
  hideTimelineFloat();
  requestTimelineRender();
});

diagnosticRefreshBtn?.addEventListener("click", () => {
  refactorCapability = null;
  requestDiagnosticsRender();
});

refactorType?.addEventListener("change", refreshRefactorTargets);
refactorTarget?.addEventListener("change", updateRefactorTargetHint);
refactorNewName?.addEventListener("input", closeRefactorPreview);
refactorNewName?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") previewRefactor();
});
refactorPreviewBtn?.addEventListener("click", previewRefactor);
refactorCancelBtn?.addEventListener("click", closeRefactorPreview);
refactorApplyBtn?.addEventListener("click", applyRefactor);
refactorUndoBtn?.addEventListener("click", undoRefactor);

profileDetailBtn.addEventListener("click", () => {
  if (!state.selected) return;
  state.selectedCharacter = state.selected;
  switchView("characters");
});

characterDetail.addEventListener("click", (event) => {
  const button = event.target.closest(".relation-row[data-character-id]");
  if (!button || !characterDetail.contains(button)) return;
  state.selectedCharacter = button.dataset.characterId;
  state.characterSearch = "";
  if (characterSearch) characterSearch.value = "";
  renderCharacterList();
  renderCharacterDetail();
  scrollPageToTop();
});

async function init() {
  try {
    await loadMarkdownData();
    state.selected = "";
    state.selectedCharacter = characters[0]?.id || "";
    state.selectedPlace = places[0]?.id || "";
    state.hasSelection = false;
    state.plotTags = allPlotTags();
    state.fragmentTags = allFragmentTags();
    state.entryTags = allEntryTags();
    renderProjectChrome();
    renderProfile();
    renderGraphFilters();
    renderNodes();
    renderLinks();
    markRelatedNodes();
    switchView("graph");
    startGraphLoop();
  } catch (error) {
    plotStrip.innerHTML = `
      <article class="plot-card" style="--accent:#e76f51">
        <div class="plot-index">!</div>
        <div>
          <h4>内容加载失败</h4>
          <p>${escapeHtml(error.message)}</p>
        </div>
      </article>
    `;
    console.error(error);
  }
}

init();
runAmbientCanvas();
