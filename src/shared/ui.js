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
