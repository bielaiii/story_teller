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
        <div class="plot-index">${escapeHtml(plotSequence(plot))}</div>
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

function nextPlotSequence() {
  return Math.max(0, ...plots.map(plotSequence)) + 1;
}

function plotEditorListValues(value) {
  return String(value || "")
    .split(/[,，、]/)
    .map((item) => item.trim())
    .filter((item, index, items) => item && items.indexOf(item) === index);
}

function setPlotCreateBusy(busy) {
  plotCreateForm?.querySelectorAll("input, select, textarea, button").forEach((element) => {
    element.disabled = element === plotCreateChapter ? true : busy;
  });
  if (plotCreateClose) plotCreateClose.disabled = busy;
  if (plotCreateCancel) plotCreateCancel.disabled = busy;
}

function setPlotCreateMessage(message = "", type = "") {
  if (!plotCreateMessage) return;
  plotCreateMessage.textContent = message;
  plotCreateMessage.className = type ? `is-${type}` : "";
}

function renderPlotEditorPreview() {
  if (!plotCreatePreview) return;
  const body = plotCreateBody?.value.trim() || "";
  plotCreatePreview.style.setProperty("--accent", plotCreateAccent?.value || "#3f7fc1");
  plotCreatePreview.innerHTML = body
    ? renderMarkdownBody(body)
    : "<p>正文预览会显示在这里。</p>";
}

function renderPlotInsertImpact() {
  if (!plotInsertImpact || !plotCreatePositionField || !plotCreatePosition) return;
  const nextSequence = nextPlotSequence();
  plotCreatePosition.max = String(nextSequence);
  const requested = Number(plotCreatePosition.value);
  if (!Number.isInteger(requested) || requested < 1 || requested > nextSequence) {
    plotInsertImpact.innerHTML = `
      <strong>可选第 1～${nextSequence} 章</strong>
      <span>填写新剧情最终所在的章号；该位置原有的章节及其后内容会自动顺延。</span>
    `;
    return;
  }
  const nextPlot = plots.find((plot) => plotSequence(plot) >= requested);
  const previousPlot = [...plots].reverse().find((plot) => plotSequence(plot) < requested);
  const inferredChapter = nextPlot?.chapter || previousPlot?.chapter || chapterKeys()[0];
  if (plotCreateChapter && chapterKeys().includes(inferredChapter)) {
    plotCreateChapter.value = inferredChapter;
  }
  const affected = plots.filter((plot) => plotSequence(plot) >= requested);
  const examples = affected.slice(0, 4).map((plot) => (
    `《${escapeHtml(plot.title)}》${plotSequence(plot)} → ${plotSequence(plot) + 1}`
  ));
  plotInsertImpact.innerHTML = `
    <strong>新剧情将成为第 ${requested} 章</strong>
    <span>自动归入“${escapeHtml(chapterName(inferredChapter))}”；${affected.length ? `后面的 ${affected.length} 章会顺延，稳定 ID 和引用保持不变。` : "当前位置没有后续章节，不需要顺移。"}</span>
    ${examples.length ? `<small>${examples.join(" · ")}${affected.length > examples.length ? " · …" : ""}</small>` : ""}
  `;
}

async function openPlotCreateDialog() {
  if (!plotCreateDialog || !plotCreateForm) return;
  plotCreateForm.reset();
  if (plotCreateAccent) plotCreateAccent.value = "#3f7fc1";
  if (plotCreatePosition) plotCreatePosition.value = String(nextPlotSequence());
  if (plotCreateChapter) {
    plotCreateChapter.innerHTML = chapterKeys().map((chapter) => (
      `<option value="${escapeHtml(chapter)}">${escapeHtml(chapterName(chapter))}</option>`
    )).join("");
  }
  renderPlotEditorPreview();
  renderPlotInsertImpact();
  setPlotCreateMessage("正在连接本地内容库…");
  setPlotCreateBusy(true);
  plotCreateDialog.showModal();
  try {
    await initializeRefactorWorkspace();
    if (!refactorCapability?.writable) throw new Error("当前页面是只读模式，请用 run.sh 启动本地服务");
    setPlotCreateBusy(false);
    setPlotCreateMessage("支持 Markdown；人物和设定会在保存后自动识别。");
    plotCreateName?.focus();
  } catch (error) {
    setPlotCreateMessage(error.message, "error");
    if (plotCreateClose) plotCreateClose.disabled = false;
    if (plotCreateCancel) plotCreateCancel.disabled = false;
  }
}

function closePlotCreateDialog() {
  if (!plotCreateDialog?.open) return;
  plotCreateDialog.close();
  setPlotCreateMessage();
  setPlotCreateBusy(false);
}

async function createPlotFromEditor(event) {
  event.preventDefault();
  if (!plotCreateForm?.reportValidity()) return;
  const requestedSequence = Number(plotCreatePosition?.value);
  const shiftingExistingPlots = requestedSequence < nextPlotSequence();
  setPlotCreateBusy(true);
  setPlotCreateMessage(shiftingExistingPlots ? "正在插入剧情并顺移后续章节…" : "正在保存新剧情…");
  try {
    const result = await refactorApi("/api/plots/create", {
      project: currentProjectId(),
      title: plotCreateName?.value.trim() || "",
      chapter: plotCreateChapter?.value || chapterKeys()[0],
      insertAt: requestedSequence,
      status: plotCreateStatusField?.value || "草稿",
      accent: plotCreateAccent?.value || "#3f7fc1",
      summary: plotCreateSummary?.value.trim() || "",
      lanes: plotEditorListValues(plotCreateLanes?.value),
      tags: plotEditorListValues(plotCreateTags?.value),
      key: Boolean(plotCreateKey?.checked),
      climax: Boolean(plotCreateClimax?.checked),
      body: plotCreateBody?.value.trim() || "",
    });
    setPlotCreateMessage(`已保存为第 ${result.sequence} 章${result.shiftedCount ? `，${result.shiftedCount} 章已顺延` : ""}。`, "success");
    window.sessionStorage?.setItem("story-teller-open-plot", String(result.id));
    window.setTimeout(() => window.location.reload(), 560);
  } catch (error) {
    setPlotCreateMessage(error.message, "error");
    setPlotCreateBusy(false);
  }
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
