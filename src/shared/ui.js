const UI_ICON_PATHS = {
  add: '<path d="M12 5v14M5 12h14"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H11v17H6.5A2.5 2.5 0 0 0 4 22Z"/><path d="M20 5.5A2.5 2.5 0 0 0 17.5 3H13v17h4.5A2.5 2.5 0 0 1 20 22Z"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  convert: '<path d="M14 3h5v5M19 3l-7 7"/><path d="M19 13v5a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V8a3 3 0 0 1 3-3h5"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  eye: '<path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.5"/>',
  folder: '<path d="M3 7h7l2 2h9v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/><path d="M3 7V5a2 2 0 0 1 2-2h5l2 2"/>',
  layout: '<path d="M4 6h16M8 3v6M4 18h16M16 15v6M4 12h16M12 9v6"/>',
  maximize: '<path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/>',
  minimize: '<path d="M8 8H3V3M16 8h5V3M8 16H3v5M16 16h5v5"/>',
  repair: '<path d="m15 4 5 5L8 21H3v-5Z"/><path d="m13 6 5 5M5 3v4M3 5h4M19 16v5M16.5 18.5h5"/>',
  restore: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
  save: '<path d="m5 12 4 4L19 6"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M7 7l1 14h8l1-14M10 11v6M14 11v6"/>',
  up: '<path d="m6 15 6-6 6 6"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
};

function uiIcon(name) {
  const paths = UI_ICON_PATHS[name] || UI_ICON_PATHS.edit;
  return `<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
}

function setIconButton(button, icon, label) {
  if (!button) return;
  button.innerHTML = uiIcon(icon);
  button.setAttribute("aria-label", label);
  button.title = label;
  button.dataset.icon = icon;
}

let appConfirmResolver = null;

function settleAppConfirm(result) {
  const resolver = appConfirmResolver;
  appConfirmResolver = null;
  if (appConfirmDialog?.open) appConfirmDialog.close();
  if (resolver) resolver(Boolean(result));
}

function showAppConfirm({
  eyebrow = "需要确认",
  title = "确认操作？",
  message = "",
  detail = "",
  variant = "danger",
  icon = variant === "danger" ? "trash" : "repair",
  confirmLabel = "确认",
  cancelLabel = "取消",
} = {}) {
  if (!appConfirmDialog) return Promise.resolve(false);
  if (appConfirmResolver) settleAppConfirm(false);
  appConfirmEyebrow.textContent = eyebrow;
  appConfirmTitle.textContent = title;
  appConfirmMessage.textContent = message;
  appConfirmDetail.textContent = detail;
  appConfirmDetail.classList.toggle("is-hidden", !detail);
  appConfirmDialog.classList.toggle("is-warning", variant === "warning");
  appConfirmSymbol.innerHTML = uiIcon(icon);
  setIconButton(appConfirmCancel, "close", cancelLabel);
  setIconButton(appConfirmSubmit, icon, confirmLabel);
  appConfirmSubmit.classList.toggle("is-danger", variant === "danger");
  appConfirmDialog.showModal();
  requestAnimationFrame(() => appConfirmCancel?.focus());
  return new Promise((resolve) => { appConfirmResolver = resolve; });
}

appConfirmCancel?.addEventListener("click", () => settleAppConfirm(false));
appConfirmSubmit?.addEventListener("click", () => settleAppConfirm(true));
appConfirmDialog?.addEventListener("cancel", (event) => {
  event.preventDefault();
  settleAppConfirm(false);
});
appConfirmDialog?.addEventListener("click", (event) => {
  if (event.target === appConfirmDialog) settleAppConfirm(false);
});
appConfirmDialog?.addEventListener("close", () => {
  if (!appConfirmResolver) return;
  const resolver = appConfirmResolver;
  appConfirmResolver = null;
  resolver(false);
});

async function refreshWorkspaceDataInPlace(options = {}) {
  const activeView = state.view;
  const scrollX = window.scrollX;
  const scrollY = window.scrollY;
  const scrollPositions = [...document.querySelectorAll("[id]")]
    .filter((element) => element.scrollTop || element.scrollLeft)
    .map((element) => ({ id: element.id, top: element.scrollTop, left: element.scrollLeft }));
  const graphPositions = new Map(characters.map((person) => [String(person.id), {
    px: person.px,
    py: person.py,
  }]));

  await loadMarkdownData();

  characters.forEach((person) => {
    const previous = graphPositions.get(String(person.id));
    if (!previous) return;
    if (Number.isFinite(previous.px)) person.px = previous.px;
    if (Number.isFinite(previous.py)) person.py = previous.py;
  });

  if (options.characterId && getCharacter(options.characterId)) {
    state.selectedCharacter = String(options.characterId);
    if (state.selected === String(options.characterId)) state.selected = String(options.characterId);
    setCharacterShelfForPerson(getCharacter(options.characterId));
  }
  if (options.placeId && getPlace(options.placeId)) state.selectedPlace = String(options.placeId);
  if (options.plotId && plots.some((plot) => Number(plot.id) === Number(options.plotId))) {
    state.selectedPlotId = Number(options.plotId);
  }

  if (state.selected && !getCharacter(state.selected)) {
    state.selected = "";
    state.hasSelection = false;
  }
  if (state.selectedCharacter && !getCharacter(state.selectedCharacter)) {
    state.selectedCharacter = (characters.find((person) => !isTemporaryCharacter(person)) || characters[0])?.id || "";
  }
  if (state.selectedPlace && !getPlace(state.selectedPlace)) state.selectedPlace = places[0]?.id || "";

  renderProjectChrome();
  graphDataDirty = true;
  if (activeView === "graph") {
    renderGraphFilters();
    renderNodes();
    renderLinks();
    markRelatedNodes();
    renderProfile();
    graphDataDirty = false;
  } else if (activeView === "characters") {
    renderCharacterList();
    renderCharacterDetail();
  } else if (activeView === "places") {
    renderPlaceList();
    renderPlaceDetail();
  } else if (activeView === "fragments") {
    renderFragmentFilters();
    renderFragments();
  } else if (activeView === "story") {
    renderChapterSwitch();
    renderStoryFilters();
    renderPlots();
  } else if (activeView === "plot-detail") {
    renderPlotDetail();
  } else if (activeView === "timeline") {
    requestTimelineRender();
  } else if (activeView === "diagnostics") {
    requestDiagnosticsRender();
    refreshPlotTrashAccess();
    refreshOperationHistoryAccess();
  }

  const restoreScrollPositions = () => {
    scrollPositions.forEach(({ id, top, left }) => {
      const element = document.getElementById(id);
      if (element) element.scrollTo({ top, left, behavior: "instant" });
    });
    window.scrollTo({ top: scrollY, left: scrollX, behavior: "instant" });
  };
  restoreScrollPositions();
  window.requestAnimationFrame(restoreScrollPositions);
}

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
    男主: "#3f7fc1",
    女主: "#d65f8f",
    主角: "#2aa79b",
    主角团: "#df8d35",
    反派: "#d84f6a",
    中立: "#6676c7",
    关键人物: "#3f7fc1",
    家人: "#68aa5b",
    家属: "#68aa5b",
    对手: "#df7655",
    支线: "#7d6bd6",
    支线主角: "#7d6bd6",
    规则: "#d8b64a",
    反派群像: "#d84f6a",
  };
  if (semanticTones[marker]) return semanticTones[marker];

  const palette = ["#3f7fc1", "#2aa79b", "#d65f8f", "#d8b64a", "#68aa5b", "#7d6bd6"];
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

function safeCssColor(value, fallback = "#6676c7") {
  const color = String(value || "").trim();
  if (!color || /[;{}"'<>]/.test(color) || !globalThis.CSS?.supports?.("color", color)) return fallback;
  return color;
}

function safeCssGradient(value, fallback = "linear-gradient(135deg, #3f7fc1, #d65f8f)") {
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

function bulletNoteLines(text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim().replace(/^(?:[-*+]\s+|\d+[.)、]\s*)/, ""))
    .filter(Boolean);
}

function renderBulletNoteItems(text) {
  const lines = bulletNoteLines(text);
  if (!lines.length) return '<li class="is-empty">暂无设定</li>';
  return lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("");
}

function renderBulletNotes(text, className = "") {
  return `<ul class="profile-note-list ${escapeHtml(className)}">${renderBulletNoteItems(text)}</ul>`;
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

function isSideTaskPlot(plot) {
  return [
    plot.title,
    plot.status,
    ...(plot.tags || []),
    ...(plot.lanes || []),
    plot.lane,
  ]
    .filter(Boolean)
    .some((value) => String(value).includes("支线"));
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

function renderChipFilter({
  container,
  label,
  items,
  selected,
  mode = "single",
  includeAll = true,
  allowClear = false,
  onChange,
}) {
  if (!container) return;
  if (!items.length) {
    container.innerHTML = "";
    return;
  }
  const activeItems = mode === "multi" ? visibleSelectedTags(selected, items) : [];
  container.innerHTML = `
    ${label ? `<span class="filter-label">${escapeHtml(label)}</span>` : ""}
    ${mode === "single" && includeAll ? `<button class="filter-chip ${selected === "all" ? "is-active" : ""}" data-value="all" type="button">全部</button>` : ""}
    ${items.map((item) => {
      const active = mode === "multi"
        ? activeItems.includes(item)
        : selected === item || (!includeAll && selected === "all");
      return `
        <button class="filter-chip ${active ? "is-active" : ""}" data-value="${escapeHtml(item)}" type="button" aria-pressed="${active}">${escapeHtml(item)}</button>
      `;
    }).join("")}
  `;
  container.querySelectorAll("[data-value]").forEach((button) => {
    button.addEventListener("click", () => {
      const value = allowClear && mode === "single" && button.dataset.value === selected
        ? "all"
        : button.dataset.value;
      onChange(value, activeItems);
    });
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
    person.characterScope,
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
  if (!isGraphCharacter(person)) return false;
  const groupMatch = state.group === "all" || person.group === state.group;
  return groupMatch && personMatchesSearch(person);
}

function isGraphCharacter(person) {
  return Boolean(
    person
    && person.graphVisible !== false
    && isMainlineCharacterScope(person.characterScope),
  );
}

function graphCharacters() {
  return characters.filter(isGraphCharacter);
}

function isVisibleRelationship(link) {
  const a = getCharacter(link.from);
  const b = getCharacter(link.to);
  if (!a || !b) return false;
  const typeMatch = state.relationType === "all" || link.type === state.relationType;
  return typeMatch && isVisiblePerson(a) && isVisiblePerson(b);
}

function renderGraphFilters() {
  const groups = [...new Set(graphCharacters().map((person) => person.group).filter(Boolean))];
  const relationTypes = [...new Set(
    relationships
      .filter((link) => isGraphCharacter(getCharacter(link.from)) && isGraphCharacter(getCharacter(link.to)))
      .map((link) => link.type)
      .filter(Boolean),
  )];

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
