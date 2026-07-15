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
  window.setTimeout(() => {
    document.querySelector(`[data-plot-id="${plotId}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, 60);
}

function openCharacterDetail(id, { preserveReturnContext = false } = {}) {
  const person = getCharacter(id);
  if (!person) return;
  rememberCurrentPlotPosition();
  if (!preserveReturnContext) state.detailReturnContext = null;
  setCharacterShelfForPerson(person);
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

async function deletePlotFromDetail(plot, button) {
  if (!plot) return;
  try {
    await initializeRefactorWorkspace();
    if (!refactorCapability?.writable) throw new Error("当前页面是只读模式，请用 run.sh 启动本地服务");
  } catch (error) {
    window.alert(error.message);
    return;
  }
  const confirmed = await showAppConfirm({
    title: "移入回收站？",
    message: `《${plot.title}》将从剧情和时间线中移除。`,
    detail: "它会保留 7 天，期间可以从检查页的回收站恢复。",
    confirmLabel: `确认删除${plot.title}`,
    cancelLabel: `取消删除${plot.title}`,
  });
  if (!confirmed) return;
  if (button) {
    button.disabled = true;
    button.textContent = "正在删除…";
  }
  try {
    await refactorApi("/api/plots/delete", {
      project: currentProjectId(),
      id: Number(plot.id),
    });
    state.selectedPlotId = null;
    state.highlightPlotId = null;
    state.detailReturnContext = null;
    state.plotPage = 1;
    setChapterFilter(plot.chapter);
    await refreshWorkspaceDataInPlace({ render: false });
    switchView("story");
    refreshPlotTrashAccess();
  } catch (error) {
    window.alert(error.message);
    if (button) {
      button.disabled = false;
      button.textContent = "删除";
    }
  }
}

function returnToCharacterContext() {
  const context = state.detailReturnContext;
  if (context?.source !== "character") return false;
  const person = getCharacter(context.characterId);
  if (!person) return false;
  const scrollY = Number(context.scrollY) || 0;
  state.detailReturnContext = null;
  openCharacterDetail(person.id);
  window.requestAnimationFrame(() => {
    window.scrollTo({ top: scrollY, left: 0, behavior: "auto" });
  });
  return true;
}

function openPlotReferenceDetail(type, id) {
  rememberCurrentPlotPosition();
  state.detailReturnContext = {
    source: "plot",
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
  if (!context || context.source === "character") return;
  state.highlightedReferenceType = context.highlightedReferenceType;
  state.highlightedReferenceId = context.highlightedReferenceId;
  state.plotReadingPositions[String(context.plotId)] = context.scrollY;
  openPlotDetail(context.plotId, { preserveReturnContext: true });
}

function detailReturnButton() {
  if (!state.detailReturnContext || state.detailReturnContext.source === "character") return "";
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
    .filter((person) => matchesKeyword(characterSearchValues(person), keyword))
    .map((person) => ({
      type: "character",
      id: person.id,
      title: person.name,
      meta: `人物 · ${person.group || "未分组"} · ${characterScopeLabel(person)}`,
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
      meta: `剧情 · ${chapterName(plot.chapter)} · 第 ${plotSequence(plot)} 章 · ${plot.status || "未标记"}`,
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
      if (typeof setGlobalSearchOpen === "function") setGlobalSearchOpen(false, { focus: false });
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
  if (type === "character") return getCharacter(id)?.color || "#2aa79b";
  return getPlace(id)?.accent || "#3f7fc1";
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
  document.querySelector("#floatingPlotChapter").textContent = `${chapterName(plot.chapter)} · 第 ${plotSequence(plot)} 章`;

  const characterReturn = state.detailReturnContext?.source === "character"
    ? getCharacter(state.detailReturnContext.characterId)
    : null;
  const backLabel = backButton.querySelector("span:last-child");
  if (backLabel) backLabel.textContent = characterReturn ? "返回人物详情" : "返回剧情列表";
  backButton.title = characterReturn ? `返回${characterReturn.name}的人物详情` : "返回剧情列表";
  backButton.onclick = () => {
    if (characterReturn && returnToCharacterContext()) return;
    openPlotInStory(plot.id);
  };
  prevButton.disabled = !navigation.prev;
  nextButton.disabled = !navigation.next;
  document.querySelector("#floatingPlotPrevTitle").textContent = navigation.prev?.title || "没有上一章";
  document.querySelector("#floatingPlotNextTitle").textContent = navigation.next?.title || "没有下一章";
  prevButton.onclick = navigation.prev
    ? () => openPlotDetail(navigation.prev.id, { preserveReturnContext: Boolean(characterReturn) })
    : null;
  nextButton.onclick = navigation.next
    ? () => openPlotDetail(navigation.next.id, { preserveReturnContext: Boolean(characterReturn) })
    : null;
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
    ${markdown.toc.length ? `
      <section class="plot-rail-section">
        <p class="eyebrow">Contents</p>
        <h2>本章目录</h2>
        <nav class="plot-toc" aria-label="本章目录">
          ${markdown.toc.map((item) => `
            <a href="#${item.id}" data-target-id="${escapeHtml(item.id)}" class="plot-toc-item level-${item.level}">${escapeHtml(item.title)}</a>
          `).join("")}
        </nav>
      </section>
    ` : ""}
    <section class="plot-rail-section">
      <p class="eyebrow">Cast</p>
      <h2>出场人物</h2>
      <div class="plot-people-list">
        ${plotPeople.map(({ id, person }) => {
          if (!person) {
            return `
              <div class="plot-person-item">
                <span class="mini-avatar" style="--avatar-gradient:linear-gradient(135deg, #3f7fc1, #7d6bd6)">${escapeHtml(id).slice(0, 2)}</span>
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
                  <span class="place-mini-symbol" style="--accent:#6676c7">${escapeHtml(id).slice(0, 2)}</span>
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
  `;

  plotDetail.innerHTML = `
    <div class="plot-detail-head" style="--accent:${escapeHtml(plot.accent)}">
      <div class="plot-detail-title-row">
        <h2>${escapeHtml(plot.title)}</h2>
        <div class="plot-detail-actions is-hidden" aria-label="剧情操作">
          <button class="plot-edit-btn icon-action" type="button" aria-label="修改${escapeHtml(plot.title)}" title="修改剧情">${uiIcon("edit")}</button>
          <button class="plot-delete-btn icon-action is-danger" type="button" aria-label="删除${escapeHtml(plot.title)}" title="删除剧情">${uiIcon("trash")}</button>
        </div>
      </div>
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
      document.getElementById(item.dataset.targetId)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
  applyPlotReferenceHighlights();
  document.querySelectorAll(".plot-reference-toggle").forEach((button) => {
    button.addEventListener("click", () => togglePlotReference(button.dataset.referenceType, button.dataset.id));
  });
  document.querySelectorAll(".plot-reference-open").forEach((button) => {
    button.addEventListener("click", () => openPlotReferenceDetail(button.dataset.referenceType, button.dataset.id));
  });
  const plotActions = plotDetail.querySelector(".plot-detail-actions");
  plotDetail.querySelector(".plot-edit-btn")?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    openPlotEditDialog(plot.id);
  });
  const deleteButton = plotDetail.querySelector(".plot-delete-btn");
  deleteButton?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    deletePlotFromDetail(plot, deleteButton);
  });
  initializeRefactorWorkspace()
    .then(() => plotActions?.classList.toggle("is-hidden", !refactorCapability?.writable))
    .catch(() => plotActions?.classList.add("is-hidden"));
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
