let characters = [];
let plots = [];
let fragments = [];
let places = [];
let relationships = [];
let timelineModel = null;
let timelineConfig = {};
let graphLayoutConfig = {};
let projectConfig = {};
const DATA_VERSION = "timeline-density";
const DEFAULT_PROJECT_ID = "demo";
const PAGE_SIZE = 6;
const ENTRY_TYPES = ["组织", "势力", "地点", "物品", "事件背景", "规则"];

function safeProjectId(value) {
  const normalized = String(value || DEFAULT_PROJECT_ID).trim();
  return /^[a-zA-Z0-9_-]+$/.test(normalized) ? normalized : DEFAULT_PROJECT_ID;
}

function currentProjectId() {
  return safeProjectId(new URLSearchParams(window.location.search).get("project"));
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

function parseMarkdownFile(text) {
  const match = text.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  if (!match) return { meta: {}, body: text.trim() };

  const meta = {};
  match[1].split("\n").forEach((line) => {
    const separator = line.indexOf(":");
    if (separator === -1) return;
    const key = line.slice(0, separator).trim();
    const value = line.slice(separator + 1);
    meta[key] = parseValue(value);
  });

  return { meta, body: match[2].trim() };
}

async function fetchText(path) {
  const separator = path.includes("?") ? "&" : "?";
  const response = await fetch(`${path}${separator}v=${DATA_VERSION}`);
  if (!response.ok) throw new Error(`无法加载 ${path}`);
  return response.text();
}

function extractManifestSection(text, sectionName) {
  const lines = text.split("\n");
  const paths = [];
  let inSection = false;

  lines.forEach((line) => {
    const heading = line.match(/^##\s+(.+)$/);
    if (heading) {
      inSection = heading[1].trim() === sectionName;
      return;
    }
    if (!inSection) return;
    const item = line.match(/^-\s+(.+\.md)\s*$/);
    if (item) paths.push(item[1].trim());
  });

  return paths;
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

async function loadGraphLayoutConfig(path) {
  if (!path) return {};
  const { meta, body } = parseMarkdownFile(await fetchText(path));
  return {
    ...meta,
    formations: parseConfigBlocks(body, "Formations"),
    distances: parseConfigBlocks(body, "Distances"),
    clusters: parseConfigBlocks(body, "Clusters"),
    nodes: parseConfigBlocks(body, "Nodes"),
  };
}

async function loadMarkdownData() {
  projectConfig = {
    id: currentProjectId(),
  };
  const manifestPath = `${contentBasePath()}/manifest.md`;
  const { meta: manifestMeta, body: manifestBody } = parseMarkdownFile(await fetchText(manifestPath));
  projectConfig = {
    ...projectConfig,
    title: manifestMeta.title || "小说剧情记录器",
    eyebrow: manifestMeta.eyebrow || "Story Teller",
    chapters: Array.isArray(manifestMeta.chapters) ? manifestMeta.chapters : ["act1", "act2", "act3"],
  };
  projectConfig.chapterLabels = chapterLabelMap(manifestMeta);

  const characterPaths = extractManifestSection(manifestBody, "Characters").map(resolveContentPath);
  const plotPaths = extractManifestSection(manifestBody, "Plots").map(resolveContentPath);
  const fragmentPaths = extractManifestSection(manifestBody, "Fragments").map(resolveContentPath);
  const placePaths = extractManifestSection(manifestBody, "Entries").map(resolveContentPath);
  const relationshipPaths = extractManifestSection(manifestBody, "Relationships").map(resolveContentPath);
  const timelinePaths = extractManifestSection(manifestBody, "Timeline").map(resolveContentPath);
  const graphLayoutPaths = extractManifestSection(manifestBody, "GraphLayout").map(resolveContentPath);

  characters = await Promise.all(characterPaths.map(async (path) => {
    const { meta, body } = parseMarkdownFile(await fetchText(path));
    return {
      ...meta,
      intro: body,
      avatar: meta.avatar ? resolveContentPath(meta.avatar) : "",
      events: Array.isArray(meta.events) ? meta.events : [],
      markers: Array.isArray(meta.markers) ? meta.markers : (meta.marker ? [meta.marker] : []),
    };
  }));

  plots = await Promise.all(plotPaths.map(async (path) => {
    const { meta, body } = parseMarkdownFile(await fetchText(path));
    return {
      ...meta,
      text: body,
      people: Array.isArray(meta.people) ? meta.people : [],
      entries: Array.isArray(meta.entries) ? meta.entries : [],
      tags: Array.isArray(meta.tags) ? meta.tags : [],
      status: meta.status || "已接入",
    };
  }));
  plots.sort((a, b) => a.id - b.id);

  fragments = await Promise.all(fragmentPaths.map(async (path, index) => {
    const { meta, body } = parseMarkdownFile(await fetchText(path));
    return {
      ...meta,
      id: meta.id || `fragment-${index + 1}`,
      title: meta.title || "未命名碎片",
      text: body,
      tags: Array.isArray(meta.tags) ? meta.tags : [],
      status: meta.status || "灵感",
    };
  }));

  places = await Promise.all(placePaths.map(async (path) => {
    const { meta, body } = parseMarkdownFile(await fetchText(path));
    return {
      ...meta,
      intro: body,
      people: Array.isArray(meta.people) ? meta.people : [],
      plots: Array.isArray(meta.plots) ? meta.plots : [],
      aliases: Array.isArray(meta.aliases) ? meta.aliases : [],
      tags: Array.isArray(meta.tags) ? meta.tags : [],
      accent: meta.accent || meta.color || "#457b9d",
      type: meta.type || "设定",
      subtype: meta.subtype || "",
    };
  }));

  relationships = await Promise.all(relationshipPaths.map(async (path) => {
    const { meta } = parseMarkdownFile(await fetchText(path));
    return meta;
  }));

  timelineConfig = await loadTimelineConfig(timelinePaths[0]);
  graphLayoutConfig = await loadGraphLayoutConfig(graphLayoutPaths[0]);
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
  timelineReversed: false,
  width: 0,
  height: 0,
};

const graphWrap = document.querySelector("#graphWrap");
const linkLayer = document.querySelector("#linkLayer");
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

function initial(name) {
  return name.slice(0, 1);
}

function avatarContent(person) {
  if (person.avatar) {
    return `<img src="${person.avatar}" alt="${person.name}" />`;
  }
  return `<span class="avatar-text">${person.name}</span>`;
}

function characterMarkers(person) {
  return Array.isArray(person?.markers) ? person.markers.filter(Boolean) : [];
}

function markerTone(marker) {
  return {
    男主: "#2563a8",
    女主: "#c95f92",
    主角: "#2a9d8f",
    主角团: "#d58a35",
    反派: "#9d3f3f",
    中立: "#65717d",
  }[marker] || "var(--accent)";
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

function slugifyHeading(text, index) {
  const base = String(text || "")
    .trim()
    .toLowerCase()
    .replace(/[^\p{Letter}\p{Number}]+/gu, "-")
    .replace(/^-+|-+$/g, "");
  return base || `section-${index + 1}`;
}

function renderMarkdownContent(text) {
  const blocks = String(text || "")
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);
  if (!blocks.length) return { html: "<p>暂无正文。</p>", toc: [] };
  const toc = [];
  const html = blocks.map((block) => {
    if (block.startsWith("### ")) {
      const title = block.slice(4).trim();
      const id = slugifyHeading(title, toc.length);
      toc.push({ id, title, level: 3 });
      return `<h4 id="${id}">${escapeHtml(title)}</h4>`;
    }
    if (block.startsWith("## ")) {
      const title = block.slice(3).trim();
      const id = slugifyHeading(title, toc.length);
      toc.push({ id, title, level: 2 });
      return `<h3 id="${id}">${escapeHtml(title)}</h3>`;
    }
    return `<p>${escapeHtml(block).replaceAll("\n", "<br />")}</p>`;
  }).join("");
  return { html, toc };
}

function renderMarkdownBody(text) {
  return renderMarkdownContent(text).html;
}

function plotExcerpt(plot) {
  const text = String(plot.text || "").replace(/\s+/g, " ").trim();
  if (text.length <= 86) return text;
  return `${text.slice(0, 86)}...`;
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
    <span class="filter-label">${label}</span>
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

function pagedItems(items, page) {
  const totalPages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  const currentPage = clampPage(page, totalPages);
  const start = (currentPage - 1) * PAGE_SIZE;
  return {
    currentPage,
    totalPages,
    items: items.slice(start, start + PAGE_SIZE),
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

function getPlace(id) {
  return places.find((place) => place.id === id);
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
    .map((group) => `<option value="${group}">${group}</option>`)
    .join("");
  relationFilter.innerHTML = '<option value="all">全部关系</option>' + relationTypes
    .map((type) => `<option value="${type}">${type}</option>`)
    .join("");
}

function renderProjectChrome() {
  document.title = projectConfig.title ? `${projectConfig.title}记录器` : "小说剧情记录器";
  if (storyEyebrow) storyEyebrow.textContent = projectConfig.eyebrow || "Story Teller";
  if (storyTitle) storyTitle.textContent = projectConfig.title || "小说剧情记录器";
}

function renderChapterSwitch() {
  if (!chapterSwitch) return;
  const chapterButtons = chapterKeys().map((chapter) => `
    <button class="chapter-btn ${state.chapter === chapter ? "is-active" : ""}" data-chapter="${chapter}" type="button">
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
  const page = pagedItems(visible, state.plotPage);
  state.plotPage = page.currentPage;
  plotStrip.innerHTML = page.items.length ? page.items
    .map((plot, index) => `
      <button class="${storyCardClass(plot, `plot-card ${state.highlightPlotId === plot.id ? "is-highlighted" : ""}`)}" data-plot-id="${plot.id}" type="button" style="--accent:${plot.accent}; animation-delay:${index * 55}ms">
        <div class="plot-index">${plot.id}</div>
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
  const page = pagedItems(visible, state.fragmentPage);
  state.fragmentPage = page.currentPage;
  fragmentBoard.innerHTML = page.items.length ? page.items.map((fragment, index) => `
    <article class="fragment-card" id="fragment-${fragment.id}" style="--accent:${fragment.accent || "#8a5cf6"}; animation-delay:${index * 55}ms">
      <div class="fragment-head">
        <span class="status-badge">${fragment.status || "灵感"}</span>
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
    scopeLabel: chapterKeys().includes(state.chapter) ? "篇内导航" : "全部剧情",
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

function generatedTimelineColor(index) {
  const hues = [206, 329, 151, 36, 257, 184, 4, 96, 284, 222];
  const hue = hues[index % hues.length];
  const lightness = index >= hues.length ? 42 + ((index - hues.length) % 3) * 4 : 46;
  return `hsl(${hue} 58% ${lightness}%)`;
}

function assignTimelineColors(lines, branchConfigs, connectors, palette, mainLineName) {
  const colorMap = new Map();
  const basePalette = palette.length
    ? palette
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
      colorMap.set(range.lane, branchConfig.color);
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

function renderTimeline() {
  updateTimelineDirectionButton();
  const mainLineName = timelineConfig.mainLine || "主线";
  const lines = Array.isArray(timelineConfig.lines) && timelineConfig.lines.length
    ? timelineConfig.lines
    : [mainLineName];
  const branchConfigs = timelineConfig.branches || [];
  const lineSpacing = timelineConfig.lineSpacing || 54;
  const topPadding = timelineConfig.topPadding || 54;
  const sidePadding = timelineConfig.sidePadding || 34;
  const palette = Array.isArray(timelineConfig.palette) && timelineConfig.palette.length
    ? timelineConfig.palette
    : ["#1d9bf0", "#c95f92", "#3f9b72", "#d58a35", "#7868c7", "#2d9ca0", "#c9685f", "#71869d"];
  const branchConfigByLine = new Map(branchConfigs.map((item) => [item.line, item]));
  const nodeConfigByPlot = new Map((timelineConfig.nodes || []).map((item) => [Number(item.plotId), item]));
  const plotIndexById = new Map(plots.map((plot, index) => [Number(plot.id), index]));
  let timelineColorMap = new Map();
  const baseLineColor = (line) => palette[Math.max(0, lines.indexOf(line)) % palette.length];
  const lineColor = (line) => timelineColorMap.get(line) || baseLineColor(line);
  const lineTrack = (branchConfig) => Math.max(1, Number(branchConfig?.trackFromMain || 1) || 1);
  const branchDisplayLength = (branchConfig) => Math.max(180, Number(branchConfig?.displayLength || 360) || 360);
  const mainDisplayLength = Math.max(680, ...branchConfigs
    .map((branchConfig) => branchDisplayLength(branchConfig) * 1.8), ...branchConfigs
    .filter((branchConfig) => (branchConfig.startLine || mainLineName) === mainLineName && (branchConfig.endLine || mainLineName) === mainLineName)
    .map((branchConfig) => {
      const start = asTimelineRatio(branchConfig.startPosition, 0);
      const end = asTimelineRatio(branchConfig.endPosition, 1);
      const span = Math.max(0.08, Math.abs(end - start));
      return (branchDisplayLength(branchConfig) + 140) / span;
    }));
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

  const summaryItems = selectTimelineSummaryItems(positionedPlots, lines, mainLineName);
  const summaryIds = new Set(summaryItems.map((item) => Number(item.plot.id)));
  const nodes = positionedPlots.map((item) => {
    const { plot, position, nodeColor, priority } = item;
    const positionLabel = `${position.lane} · ${timelinePercentLabel(position.storyRatio)}`;
    const nodeClass = [
      "timeline-node",
      "timeline-node-focus",
      priority >= 4 || summaryIds.has(Number(plot.id)) ? "is-featured" : "is-minor",
      plot.climax ? "is-climax" : "",
      plot.key ? "is-key" : "",
    ].filter(Boolean).join(" ");
    return `<button class="${nodeClass}" data-plot-id="${plot.id}" data-lane="${position.lane}" type="button" aria-label="${timelinePlotTitle(plot)}，${positionLabel}" title="${positionLabel}" style="--accent:${nodeColor}; left:${position.x}px; top:${position.y}px">
      <span class="timeline-pulse" aria-hidden="true"></span>
      <span class="timeline-dot" aria-hidden="true"></span>
      <span class="timeline-node-tip">${positionLabel}</span>
    </button>`;
  }).join("");

  const summaryCard = (item) => {
    const { plot, position, nodeColor } = item;
    return `
      <button class="timeline-summary-card timeline-jump" data-plot-id="${plot.id}" data-primary-lane="${position.lane}" data-lanes="${position.lane}" type="button" style="--accent:${nodeColor}; --card-y:${Math.round(position.y)}px">
        <span>${timelinePlotChapter(plot)} · ${plot.id}</span>
        <strong>${timelinePlotTitle(plot)}</strong>
        <p>${timelinePlotSummary(plot)}</p>
        <small class="timeline-read-hint">阅读全文</small>
      </button>
    `;
  };
  const leftSummaryCards = summaryItems.filter((item) => item.side === "left").map(summaryCard).join("");
  const rightSummaryCards = summaryItems.filter((item) => item.side !== "left").map(summaryCard).join("");
  const legendItems = laneLines
    .filter((line) => line.lane !== mainLineName && connectorLines.some((connector) => connector.lane === line.lane))
    .map((line) => `
      <span class="timeline-legend-item" data-line="${line.lane}" style="--accent:${line.color}">
        <i aria-hidden="true"></i>${line.lane}
      </span>
    `).join("");

  timelineModel = {
    width: graphWidth,
    height: graphHeight,
    lanes: lines,
    laneLines,
    connectors: connectorLines,
    focusLane: "",
  };

  timelineList.innerHTML = `
    <div class="timeline-board ${plots.length > 36 ? "is-dense" : ""}" style="--timeline-height:${graphHeight}px; --map-width:${graphWidth}px">
      <div class="timeline-side timeline-side-left">
        ${leftSummaryCards}
      </div>
      <div class="timeline-map">
        <div class="timeline-orbit" aria-hidden="true"></div>
        <div class="timeline-canvas" id="timelineCanvasWrap" style="width:${graphWidth}px; height:${graphHeight}px" aria-label="剧情线画布">
          <canvas class="timeline-drawing" id="timelineDrawing" width="${graphWidth}" height="${graphHeight}" aria-hidden="true"></canvas>
          ${nodes}
        </div>
      </div>
      <div class="timeline-side timeline-side-right">
        ${rightSummaryCards}
      </div>
      <div class="timeline-float is-hidden" id="timelineFloat">
        <span id="timelineFloatLane"></span>
        <strong id="timelineFloatTitle"></strong>
        <p id="timelineFloatText"></p>
      </div>
    </div>
  `;
  if (timelineLegend) timelineLegend.innerHTML = legendItems;

  document.querySelectorAll(".timeline-jump").forEach((item) => {
    item.addEventListener("click", (event) => {
      event.stopPropagation();
      openPlotDetail(Number(item.dataset.plotId));
    });
  });
  document.querySelectorAll(".timeline-node-focus").forEach((item) => {
    item.addEventListener("click", (event) => {
      event.stopPropagation();
      openPlotDetail(Number(item.dataset.plotId));
    });
  });
  document.querySelector("#timelineCanvasWrap")?.addEventListener("click", handleTimelineCanvasClick);
  document.querySelector(".timeline-board")?.addEventListener("click", handleTimelineBoardClick);
  drawTimelineCanvas();
  updateTimelineLegend();
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

function drawTimelineCanvas() {
  const canvas = document.querySelector("#timelineDrawing");
  if (!canvas || !timelineModel) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = timelineModel.width * ratio;
  canvas.height = timelineModel.height * ratio;
  canvas.style.width = `${timelineModel.width}px`;
  canvas.style.height = `${timelineModel.height}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, timelineModel.width, timelineModel.height);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";

  timelineModel.laneLines.filter((line) => line.lane === "主线").forEach((line) => {
    const isFocused = timelineModel.focusLane === line.lane;
    ctx.save();
    ctx.globalAlpha = timelineModel.focusLane && !isFocused ? 0.18 : 0.84;
    ctx.strokeStyle = line.color;
    ctx.lineWidth = isFocused ? 12 : 7;
    ctx.shadowColor = isFocused ? "rgba(25, 33, 42, 0.26)" : "rgba(31, 46, 58, 0.12)";
    ctx.shadowBlur = isFocused ? 16 : 8;
    ctx.beginPath();
    ctx.moveTo(line.x, line.y1);
    ctx.lineTo(line.x, line.y2);
    ctx.stroke();
    ctx.restore();
  });

  timelineModel.connectors.forEach((connector) => {
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

function updateTimelineLegend() {
  if (!timelineModel || !timelineLegend) return;
  const visibleLines = new Set();
  const canvasWrap = document.querySelector("#timelineCanvasWrap");
  const canvasRect = canvasWrap?.getBoundingClientRect();
  const listRect = timelineList?.getBoundingClientRect();
  if (canvasRect && listRect && canvasRect.height > 0) {
    const clipTop = Math.max(0, listRect.top);
    const clipBottom = Math.min(window.innerHeight, listRect.bottom);
    const scale = timelineModel.height / canvasRect.height;
    const visibleTop = Math.max(0, (clipTop - canvasRect.top) * scale);
    const visibleBottom = Math.min(timelineModel.height, (clipBottom - canvasRect.top) * scale);
    const overlapsView = (start, end) => Math.max(start, visibleTop) <= Math.min(end, visibleBottom);
    timelineModel.laneLines.forEach((line) => {
      if (overlapsView(Math.min(line.y1, line.y2), Math.max(line.y1, line.y2))) visibleLines.add(line.lane);
    });
    timelineModel.connectors.forEach((connector) => {
      if (overlapsView(Math.min(connector.y1, connector.y2), Math.max(connector.y1, connector.y2))) visibleLines.add(connector.lane);
    });
  }

  let visibleCount = 0;
  document.querySelectorAll(".timeline-legend-item").forEach((item) => {
    const isVisible = timelineModel.focusLane
      ? item.dataset.line === timelineModel.focusLane
      : visibleLines.has(item.dataset.line);
    item.classList.toggle("is-hidden-by-focus", !isVisible);
    item.classList.toggle("is-active", item.dataset.line === timelineModel.focusLane);
    if (isVisible) visibleCount += 1;
  });
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

function showTimelineFloat(target) {
  const float = document.querySelector("#timelineFloat");
  if (!float) return;
  const plot = plots.find((item) => item.id === Number(target.dataset.plotId));
  const lane = target.dataset.lane || "剧情线";
  const activeLane = lane.split(" / ").map((item) => item.trim()).filter(Boolean)[0] || lane;
  if (timelineModel) timelineModel.focusLane = plot ? activeLane : lane;
  drawTimelineCanvas();
  updateTimelineLegend();
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
  float.classList.remove("is-hidden");
}

function hideTimelineFloat() {
  document.querySelector("#timelineFloat")?.classList.add("is-hidden");
  if (timelineModel) timelineModel.focusLane = "";
  drawTimelineCanvas();
  updateTimelineLegend();
  document.querySelectorAll(".timeline-summary-card.is-hidden-by-focus").forEach((item) => item.classList.remove("is-hidden-by-focus"));
  document.querySelectorAll(".timeline-node.is-muted-by-focus").forEach((item) => item.classList.remove("is-muted-by-focus"));
}

function setChapterFilter(chapter) {
  state.chapter = chapter;
  document.querySelectorAll(".chapter-btn").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.chapter === chapter);
  });
}

function openPlotInStory(plotId) {
  const plot = plots.find((item) => item.id === plotId);
  if (!plot) return;
  state.highlightPlotId = plotId;
  setChapterFilter(plot.chapter);
  switchView("story");
  renderPlots();
  window.setTimeout(() => {
    document.querySelector(`[data-plot-id="${plotId}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, 60);
}

function openCharacterDetail(id) {
  const person = getCharacter(id);
  if (!person) return;
  state.selectedCharacter = id;
  state.characterSearch = "";
  if (characterSearch) characterSearch.value = "";
  switchView("characters");
  hideGlobalSearchResults();
}

function openPlaceDetail(id) {
  const place = getPlace(id);
  if (!place) return;
  state.selectedPlace = id;
  state.placeSearch = "";
  if (placeSearch) placeSearch.value = "";
  switchView("places");
  hideGlobalSearchResults();
}

function openPlotDetail(plotId) {
  const plot = plots.find((item) => item.id === plotId);
  if (!plot) return;
  state.selectedPlotId = plotId;
  state.highlightPlotId = plotId;
  switchView("plot-detail");
  hideGlobalSearchResults();
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
    <button class="global-search-result" type="button" data-type="${result.type}" data-id="${result.id}" data-from="${result.from || ""}" data-to="${result.to || ""}">
      <span>${result.meta}</span>
      <strong>${result.title}</strong>
      <small>${result.text || ""}</small>
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

function renderPlotDetail() {
  const plot = plots.find((item) => item.id === Number(state.selectedPlotId)) || plots[0];
  if (!plot || !plotDetail || !plotPeopleRail) return;
  const plotPeople = plot.people.map((id) => ({ id, person: getCharacter(id) }));
  const plotPlaces = (plot.entries || []).map((id) => ({ id, place: getPlace(id) }));
  const navigation = plotNavigation(plot);
  const markdown = renderMarkdownContent(plot.text);

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
            <button class="plot-person-item" data-id="${person.id}" type="button">
              <span class="mini-avatar" style="--avatar-gradient:${person.gradient}">${avatarContent(person)}</span>
              <span>
                <strong>${person.name}</strong>
                <small>${person.group || "未分组"}</small>
              </span>
            </button>
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
              <button class="plot-place-item" data-id="${place.id}" type="button" style="--accent:${place.accent}">
                <span class="place-mini-symbol">${escapeHtml(place.name).slice(0, 2)}</span>
                <span>
                  <strong>${place.name}</strong>
                  <small>${place.type || "未分类"} · ${place.area || "未分区"}</small>
                </span>
              </button>
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
    <div class="plot-detail-head" style="--accent:${plot.accent}">
      <div class="plot-detail-actions">
        <button class="plot-back-btn" id="plotBackBtn" type="button">返回剧情列表</button>
        <span class="chapter-chip">${chapterName(plot.chapter)} · ${plot.id}</span>
      </div>
      <div>
        <h2>${plot.title}</h2>
        <div class="badge-line">
          ${statusBadge(plot.status)}
          ${tagBadges(plot.tags)}
          ${plotBadges(plot)}
        </div>
      </div>
      <div class="plot-nav-row" aria-label="章节切换">
        <button class="plot-nav-btn" id="plotPrevBtn" type="button" ${navigation.prev ? `data-plot-id="${navigation.prev.id}"` : "disabled"}>
          <span>上一章</span>
          <strong>${navigation.prev ? navigation.prev.title : "没有上一章"}</strong>
        </button>
        <span class="plot-nav-scope">${navigation.scopeLabel}</span>
        <button class="plot-nav-btn" id="plotNextBtn" type="button" ${navigation.next ? `data-plot-id="${navigation.next.id}"` : "disabled"}>
          <span>下一章</span>
          <strong>${navigation.next ? navigation.next.title : "没有下一章"}</strong>
        </button>
      </div>
    </div>
    <div class="plot-detail-body">
      ${markdown.html}
    </div>
  `;

  document.querySelector("#plotBackBtn")?.addEventListener("click", () => openPlotInStory(plot.id));
  document.querySelectorAll(".plot-nav-btn[data-plot-id]").forEach((button) => {
    button.addEventListener("click", () => openPlotDetail(Number(button.dataset.plotId)));
  });
  document.querySelectorAll(".plot-person-item[data-id]").forEach((button) => {
    button.addEventListener("click", () => openCharacterDetail(button.dataset.id));
  });
  document.querySelectorAll(".plot-place-item[data-id]").forEach((button) => {
    button.addEventListener("click", () => openPlaceDetail(button.dataset.id));
  });
  document.querySelectorAll(".plot-toc-item").forEach((item) => {
    item.addEventListener("click", (event) => {
      event.preventDefault();
      document.querySelector(item.getAttribute("href"))?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
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
    ]
      .filter(Boolean)
      .some((text) => String(text).toLowerCase().includes(keyword));
  });

  if (visibleCharacters.length && !visibleCharacters.some((person) => person.id === state.selectedCharacter)) {
    state.selectedCharacter = visibleCharacters[0].id;
  }

  characterList.innerHTML = visibleCharacters
    .map((person) => `
      <button class="character-list-item ${person.id === state.selectedCharacter ? "is-active" : ""}" data-id="${person.id}" type="button">
        <span class="mini-avatar" style="--avatar-gradient:${person.gradient}">${avatarContent(person)}</span>
        <span>
          <strong>${person.name}</strong>
          <small>${person.group || "未分组"}</small>
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
    <div class="character-hero">
      <div class="character-avatar" style="--avatar-gradient:${person.gradient}">${avatarContent(person)}</div>
      <div class="character-copy">
        <p class="label">${person.group || "未分组"}</p>
        <h2>${person.name}</h2>
        <p>${person.intro}</p>
      </div>
      <aside class="character-marker-panel">
        ${markerBadges(person)}
      </aside>
    </div>

    <section class="character-section">
      <div class="section-title">
        <p class="label">出场剧情</p>
        <h3>${personPlots.length} 个剧情点</h3>
      </div>
      <div class="character-plot-list">
        ${personPlots.map((plot) => `
          <article class="${storyCardClass(plot, "character-plot")}" style="--accent:${plot.accent}">
            ${renderStoryCardContent(plot, { heading: "strong", titlePrefix: `${plot.id}. ` })}
          </article>
        `).join("")}
      </div>
    </section>

    <section class="character-section">
      <div class="section-title">
        <p class="label">人物关系</p>
        <h3>${personLinks.length} 条关系</h3>
      </div>
      <div class="relation-list">
        ${personLinks.map((link) => {
          const otherId = link.from === person.id ? link.to : link.from;
          const other = getCharacter(otherId);
          return `
            <div class="relation-row" style="--accent:${link.color}">
              <span>${other?.name || otherId}</span>
              <strong>${link.label}</strong>
              <small>${link.type || "未分类"}</small>
            </div>
          `;
        }).join("")}
      </div>
    </section>
  `;
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
      <button class="place-list-item ${place.id === state.selectedPlace ? "is-active" : ""}" data-id="${place.id}" type="button" style="--accent:${place.accent}">
        <span class="place-mini-symbol">${escapeHtml(place.name).slice(0, 2)}</span>
        <span>
          <strong>${place.name}</strong>
          <small>${place.type || "未分类"}${place.subtype ? ` · ${place.subtype}` : ""} · ${place.area || "未分区"}</small>
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
    <div class="place-hero" style="--accent:${place.accent}">
      <div class="place-symbol">${escapeHtml(place.name).slice(0, 2)}</div>
      <div class="character-copy">
        <p class="label">${place.type || "未分类"}${place.subtype ? ` · ${place.subtype}` : ""} · ${place.area || "未分区"}</p>
        <h2>${place.name}</h2>
        <div class="place-intro">${renderMarkdownBody(place.intro)}</div>
      </div>
      <aside class="place-facts">
        <span>${escapeHtml(place.type || "未分类")}</span>
        ${place.subtype ? `<span>${escapeHtml(place.subtype)}</span>` : ""}
        ${place.area ? `<span>${escapeHtml(place.area)}</span>` : ""}
        ${(place.tags || []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}
        ${(place.aliases || []).map((alias) => `<span>${escapeHtml(alias)}</span>`).join("")}
        ${place.status ? `<span>${escapeHtml(place.status)}</span>` : ""}
      </aside>
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
            <button class="plot-person-item" data-id="${person.id}" type="button">
              <span class="mini-avatar" style="--avatar-gradient:${person.gradient}">${avatarContent(person)}</span>
              <span>
                <strong>${person.name}</strong>
                <small>${person.group || "未分组"}</small>
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
          <button class="${storyCardClass(plot, "character-plot place-plot-card")}" data-plot-id="${plot.id}" type="button" style="--accent:${plot.accent}">
            ${renderStoryCardContent(plot, { heading: "strong", titlePrefix: `${plot.id}. ` })}
          </button>
        `).join("") || '<p class="empty-state">这个设定还没有配置出现剧情。</p>'}
      </div>
    </section>
  `;

  document.querySelectorAll(".place-person-grid .plot-person-item[data-id]").forEach((button) => {
    button.addEventListener("click", () => openCharacterDetail(button.dataset.id));
  });
  document.querySelectorAll(".place-plot-card[data-plot-id]").forEach((button) => {
    button.addEventListener("click", () => openPlotDetail(Number(button.dataset.plotId)));
  });
}

function switchView(view) {
  const previousView = state.view;
  const activeNav = view === "plot-detail" ? "story" : view;
  document.querySelectorAll(".view-btn").forEach((item) => item.classList.toggle("is-active", item.dataset.view === activeNav));
  document.querySelectorAll(".page-view").forEach((page) => page.classList.toggle("is-active", page.dataset.page === view));
  state.view = view;

  if (state.view === "graph") {
    updateGraphBounds();
    if (state.selected) selectPerson(state.selected);
    drawGraph();
  }
  if (state.view === "timeline") {
    renderTimeline();
  } else {
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
  if (state.view === "story" && previousView !== "story" && previousView !== "plot-detail") {
    state.plotTags = allPlotTags();
    state.plotPage = 1;
    renderStoryFilters();
    renderPlots();
  }
  if (state.view === "plot-detail") renderPlotDetail();
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
      <article class="event-item" style="--accent:${plot.accent}; animation-delay:${index * 70}ms">
        <span class="event-dot"></span>
        <p>${plot.title}：${plot.text}</p>
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
      <span class="node-name">${person.name}</span>
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
  linkLayer.innerHTML = "";
  relationships.forEach((link) => {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.classList.add("relationship-path");
    path.dataset.from = link.from;
    path.dataset.to = link.to;
    path.dataset.type = link.type || "";
    path.style.setProperty("--accent", link.color);
    linkLayer.appendChild(path);
  });
  applyGraphFilters();
}

function selectPerson(id) {
  const person = getCharacter(id);
  if (!person) return;
  state.selected = id;
  state.hasSelection = true;
  state.selectedCharacter = id;
  person.pinned = false;
  centerViewportOn(person);
  renderProfile();
  markRelatedNodes();
}

function markRelatedNodes() {
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

  document.querySelectorAll(".person-node").forEach((node) => {
    const id = node.dataset.id;
    const person = getCharacter(id);
    node.classList.toggle("is-active", state.hasSelection && id === state.selected);
    node.classList.toggle("is-linked", direct.has(id) && id !== state.selected);
    node.classList.toggle("is-reachable", reachable.has(id) && id !== state.selected);
    node.classList.toggle("is-muted-by-selection", state.hasSelection && !reachable.has(id));
    node.classList.toggle("is-pinned", Boolean(person?.pinned));
  });
  document.querySelectorAll(".relationship-path").forEach((item) => {
    const relatedEdge = state.hasSelection && reachable.has(item.dataset.from) && reachable.has(item.dataset.to);
    item.classList.toggle("is-reachable", relatedEdge);
    item.classList.toggle("is-muted-by-selection", state.hasSelection && !relatedEdge);
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

  document.querySelectorAll(".relationship-path").forEach((item) => {
    const visible = isVisibleRelationship({
      from: item.dataset.from,
      to: item.dataset.to,
      type: item.dataset.type,
    });
    item.classList.toggle("is-filtered-out", !visible);
  });
}

function updateGraphBounds() {
  const bounds = graphWrap.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return;
  state.width = bounds.width;
  state.height = bounds.height;

  characters.forEach((person) => {
    if (typeof person.px !== "number" || typeof person.py !== "number") {
      const point = jitterPoint(
        (person.x / 100) * state.width,
        (person.y / 100) * state.height,
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
  const worldX = -state.graphPanX / state.graphScale;
  const worldY = -state.graphPanY / state.graphScale;
  linkLayer.setAttribute("viewBox", `${worldX} ${worldY} ${state.width / state.graphScale} ${state.height / state.graphScale}`);
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

function separateOverlappingNodes() {
  const minDistance = Number(graphLayoutConfig.nodeSpacing || 116);
  characters.forEach((a, index) => {
    characters.slice(index + 1).forEach((b) => {
      const dx = b.px - a.px;
      const dy = b.py - a.py;
      const distance = Math.max(0.1, Math.hypot(dx, dy));
      if (distance >= minDistance) return;
      const overlap = (minDistance - distance) * 0.52;
      const nx = dx / distance;
      const ny = dy / distance;
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
  });
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
  event.currentTarget.setPointerCapture(event.pointerId);
}

graphWrap.addEventListener("pointerdown", (event) => {
  if (event.target.closest(".person-node")) return;
  state.panning = {
    startClientX: event.clientX,
    startClientY: event.clientY,
    startPanX: state.graphPanX,
    startPanY: state.graphPanY,
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
    state.graphPanX = state.panning.startPanX + event.clientX - state.panning.startClientX;
    state.graphPanY = state.panning.startPanY + event.clientY - state.panning.startClientY;
    updateGraphViewport();
    return;
  }

  if (state.dragging) {
    const person = getCharacter(state.dragging.id);
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
  if (state.dragging?.moved) {
    const person = getCharacter(state.dragging.id);
    if (person) {
      person.pinned = true;
      person.vx = 0;
      person.vy = 0;
      person.x = (person.px / state.width) * 100;
      person.y = (person.py / state.height) * 100;
    }
    state.suppressClickId = state.dragging.id;
    state.suppressClickUntil = Date.now() + 250;
    markRelatedNodes();
  }
  state.dragging = null;
  state.panning = null;
});

function tick() {
  if (!state.width || !state.height) {
    requestAnimationFrame(tick);
    return;
  }

  characters.forEach((a, index) => {
    characters.forEach((b, bIndex) => {
      if (index >= bIndex) return;
      const dx = a.px - b.px;
      const dy = a.py - b.py;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const push = Math.max(0, 150 - distance) * 0.0009;
      const nx = dx / distance;
      const ny = dy / distance;
      const selectedPush = state.hasSelection && (a.id === state.selected || b.id === state.selected) ? 0.004 : 0;
      pushPerson(a, nx * push, ny * push);
      pushPerson(b, -nx * push, -ny * push);
      if (selectedPush) {
        pushPerson(a, nx * selectedPush, ny * selectedPush);
        pushPerson(b, -nx * selectedPush, -ny * selectedPush);
      }
    });
  });

  relationships.forEach((link) => {
    const a = getCharacter(link.from);
    const b = getCharacter(link.to);
    if (!a || !b) return;
    applyPairDistance(a, b, Number(link.distance || 250), Number(link.strength || 1));
  });

  applyGraphLayoutForces();

  characters.forEach((person) => {
    if (canMovePerson(person)) {
      person.vx *= 0.91;
      person.vy *= 0.91;
      person.px += person.vx;
      person.py += person.vy;
    }
  });

  separateOverlappingNodes();

  characters.forEach((person) => {
    person.x = (person.px / state.width) * 100;
    person.y = (person.py / state.height) * 100;
  });

  drawGraph();
  requestAnimationFrame(tick);
}

function drawGraph() {
  updateGraphViewport();
  document.querySelectorAll(".person-node").forEach((node) => {
    const person = getCharacter(node.dataset.id);
    node.style.left = `${person.px}px`;
    node.style.top = `${person.py}px`;
  });

  document.querySelectorAll(".relationship-path").forEach((path) => {
    const a = getCharacter(path.dataset.from);
    const b = getCharacter(path.dataset.to);
    if (!a || !b) return;
    const dx = b.px - a.px;
    const dy = b.py - a.py;
    const curve = Math.min(92, Math.hypot(dx, dy) * 0.24);
    const cx = (a.px + b.px) / 2 - (dy / Math.max(1, Math.hypot(dx, dy))) * curve;
    const cy = (a.py + b.py) / 2 + (dx / Math.max(1, Math.hypot(dx, dy))) * curve;
    path.setAttribute("d", `M ${a.px} ${a.py} Q ${cx} ${cy} ${b.px} ${b.py}`);
  });

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

timelineList?.addEventListener("scroll", updateTimelineLegend);
window.addEventListener("scroll", updateTimelineLegend);
window.addEventListener("resize", updateTimelineLegend);

function runAmbientCanvas() {
  const canvas = document.querySelector("#ambientCanvas");
  const ctx = canvas.getContext("2d");
  const particles = Array.from({ length: 78 }, (_, index) => ({
    x: Math.random(),
    y: Math.random(),
    r: 1.2 + Math.random() * 2.8,
    speed: 0.001 + Math.random() * 0.002,
    phase: index * 0.4,
    color: ["rgba(42, 157, 143, 0.32)", "rgba(231, 111, 81, 0.24)", "rgba(69, 123, 157, 0.25)", "rgba(233, 196, 106, 0.28)"][index % 4],
  }));

  function resize() {
    canvas.width = window.innerWidth * window.devicePixelRatio;
    canvas.height = window.innerHeight * window.devicePixelRatio;
    canvas.style.width = `${window.innerWidth}px`;
    canvas.style.height = `${window.innerHeight}px`;
    ctx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);
  }

  function paint(time) {
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    particles.forEach((particle) => {
      const drift = Math.sin(time * particle.speed + particle.phase) * 26;
      const x = particle.x * window.innerWidth + drift;
      const y = ((particle.y + time * particle.speed * 0.018) % 1) * window.innerHeight;
      ctx.beginPath();
      ctx.fillStyle = particle.color;
      ctx.arc(x, y, particle.r, 0, Math.PI * 2);
      ctx.fill();
    });
    requestAnimationFrame(paint);
  }

  window.addEventListener("resize", resize);
  resize();
  requestAnimationFrame(paint);
}

window.addEventListener("resize", () => {
  updateGraphBounds();
  drawGraph();
});

document.querySelectorAll(".view-btn").forEach((button) => {
  button.addEventListener("click", () => {
    switchView(button.dataset.view);
  });
});

timelineDirectionBtn?.addEventListener("click", () => {
  state.timelineReversed = !state.timelineReversed;
  hideTimelineFloat();
  renderTimeline();
});

profileDetailBtn.addEventListener("click", () => {
  if (!state.selected) return;
  state.selectedCharacter = state.selected;
  switchView("characters");
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
    renderChapterSwitch();
    renderStoryFilters();
    renderPlots();
    renderFragmentFilters();
    renderFragments();
    renderTimeline();
    renderCharacterList();
    renderCharacterDetail();
    renderPlaceList();
    renderPlaceDetail();
    renderProfile();
    renderGraphFilters();
    renderLinks();
    renderNodes();
    markRelatedNodes();
    switchView("graph");
    requestAnimationFrame(tick);
  } catch (error) {
    plotStrip.innerHTML = `
      <article class="plot-card" style="--accent:#e76f51">
        <div class="plot-index">!</div>
        <div>
          <h4>内容加载失败</h4>
          <p>${error.message}</p>
        </div>
      </article>
    `;
    console.error(error);
  }
}

runAmbientCanvas();
init();
