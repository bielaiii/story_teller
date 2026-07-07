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
  renderSideTaskToggle();
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

function renderSideTaskToggle() {
  if (!sideTaskToggle) return;
  const sideCount = plots.filter(isSideTaskPlot).length;
  const active = state.plotShelf === "side";
  const label = sideTaskToggle.querySelector("span");
  sideTaskToggle.classList.toggle("is-active", active);
  sideTaskToggle.setAttribute("aria-pressed", String(active));
  sideTaskToggle.setAttribute("aria-label", active ? `返回全部剧情，共 ${plots.length} 个` : `查看支线任务，共 ${sideCount} 个`);
  if (label) label.textContent = active ? "全部剧情" : "支线任务";
  if (sideTaskCount) sideTaskCount.textContent = String(active ? plots.length : sideCount);
}

function renderPlots() {
  const visible = plots.filter((plot) => {
    const chapterMatch = state.chapter === "all"
      || (state.chapter === "key" && plot.key)
      || (state.chapter === "climax" && plot.climax)
      || plot.chapter === state.chapter;
    const statusMatch = state.plotStatus === "all" || plot.status === state.plotStatus;
    const tagMatch = matchesSelectedTags(plot.tags || [], state.plotTags, allPlotTags());
    const shelfMatch = state.plotShelf !== "side" || isSideTaskPlot(plot);
    return chapterMatch && statusMatch && tagMatch && shelfMatch;
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
    .join("") : `<p class="empty-state">${state.plotShelf === "side" ? "没有匹配的支线任务。" : "没有匹配的剧情。"}</p>`;
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
