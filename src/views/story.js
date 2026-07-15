function resetStoryNavigationState() {
  state.chapter = "all";
  state.plotStatus = "all";
  state.plotTags = allPlotTags();
  state.plotShelf = "all";
  state.plotPage = 1;
  state.highlightPlotId = null;
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
  renderSideTaskToggle();
  const statuses = [...new Set(plots.map((plot) => plot.status).filter(Boolean))];
  renderChipFilter({
    container: statusFilter,
    label: "状态",
    items: statuses,
    selected: state.plotStatus,
    includeAll: false,
    allowClear: true,
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

function selectPlotEditorStatus(status) {
  if (!plotCreateStatusField) return;
  const value = String(status || "草稿").trim() || "草稿";
  const hasOption = [...plotCreateStatusField.options].some((option) => option.value === value);
  if (!hasOption) {
    plotCreateStatusField.add(new Option(value, value));
  }
  plotCreateStatusField.value = value;
}

function renderPlotReferenceOptions(plot = null) {
  const people = new Set((plot?.people || []).map(String));
  const entries = new Set((plot?.entries || []).map(String));
  if (plotCreatePeople) {
    plotCreatePeople.innerHTML = characters.map((person) => `<option value="${escapeHtml(person.id)}" ${people.has(String(person.id)) ? "selected" : ""}>${escapeHtml(person.name)}</option>`).join("");
  }
  if (plotCreateEntries) {
    plotCreateEntries.innerHTML = places.map((place) => `<option value="${escapeHtml(place.id)}" ${entries.has(String(place.id)) ? "selected" : ""}>${escapeHtml(place.name)}</option>`).join("");
  }
}

function selectedPlotReferences(select) {
  return [...(select?.selectedOptions || [])].map((option) => option.value);
}

function moveDialogToVisibleRoot(dialog) {
  if (dialog && dialog.parentElement !== document.body) document.body.append(dialog);
}

function setPlotTrashStatus(message = "", type = "") {
  if (!plotTrashStatus) return;
  plotTrashStatus.textContent = message;
  plotTrashStatus.className = `plot-trash-status${type ? ` is-${type}` : ""}`;
}

const TRASH_KIND_LABELS = {
  plot: "剧情",
  character: "人物",
  entry: "设定",
  fragment: "碎片",
  relationship: "人物关系",
  timeline: "剧情线",
  chapter: "篇章",
};

const HISTORY_KIND_LABELS = {
  ...TRASH_KIND_LABELS,
  project: "作品设置",
  graph: "人物图谱",
  diagnostics: "配置修复",
  refactor: "批量重命名",
  content: "内容",
};

let plotTrashItemsCache = [];

function trashKindLabel(kind) {
  return TRASH_KIND_LABELS[kind] || CONTENT_KIND_LABELS[kind] || "内容";
}

function renderPlotTrashKindFilter(items) {
  if (!plotTrashKindFilter) return;
  const previous = plotTrashKindFilter.value || "all";
  const counts = items.reduce((result, item) => {
    result[item.kind] = (result[item.kind] || 0) + 1;
    return result;
  }, {});
  plotTrashKindFilter.innerHTML = [
    `<option value="all">所有类型（${items.length}）</option>`,
    ...Object.entries(TRASH_KIND_LABELS).map(([kind, label]) => (
      `<option value="${kind}">${label}（${counts[kind] || 0}）</option>`
    )),
  ].join("");
  plotTrashKindFilter.value = previous in counts || previous === "all" ? previous : "all";
}

function updatePlotTrashTrigger(count = 0, writable = false) {
  if (plotTrashCount) plotTrashCount.textContent = String(count);
  plotTrashWorkspace?.classList.toggle("is-hidden", !writable);
  plotTrashTrigger?.classList.toggle("is-hidden", !writable);
}

function renderPlotTrashItems(items = []) {
  if (!plotTrashList) return;
  plotTrashItemsCache = items;
  renderPlotTrashKindFilter(items);
  const selectedKind = plotTrashKindFilter?.value || "all";
  const visibleItems = selectedKind === "all" ? items : items.filter((item) => item.kind === selectedKind);
  plotTrashList.innerHTML = visibleItems.length
    ? visibleItems.map((item) => `
        <article class="plot-trash-item">
          <div>
            <span>${escapeHtml(trashKindLabel(item.kind))}${item.kind === "plot" ? ` · 原第 ${escapeHtml(item.sequence)} 章` : ""}</span>
            <strong>${escapeHtml(item.title)}</strong>
            <small>${escapeHtml(item.daysRemaining)} 天后永久删除</small>
            ${item.restoreBlockedReason ? `<small class="plot-trash-restore-warning">${escapeHtml(item.restoreBlockedReason)}</small>` : ""}
          </div>
          <div class="plot-trash-item-actions">
            <button class="plot-trash-preview-btn icon-action" data-trash-id="${escapeHtml(item.trashId)}" data-kind="${escapeHtml(item.kind || "plot")}" data-history="${item.history ? "true" : "false"}" type="button" aria-label="预览${escapeHtml(item.title)}" title="预览">${uiIcon("eye")}</button>
            <button class="plot-trash-restore icon-action" data-trash-id="${escapeHtml(item.trashId)}" data-kind="${escapeHtml(item.kind || "plot")}" data-history="${item.history ? "true" : "false"}" type="button" aria-label="恢复${escapeHtml(item.title)}" title="${escapeHtml(item.restoreBlockedReason || "恢复")}" ${item.canRestore === false ? "disabled" : ""}>${uiIcon("restore")}</button>
          </div>
        </article>
      `).join("")
    : `
        <div class="plot-trash-empty">
          <strong>${items.length ? "这个类型没有删除内容" : "回收站是空的"}</strong>
          <p>${items.length ? "可以切换其他删除类型查看。" : "删除的内容会在这里保留 7 天。"}</p>
        </div>
      `;
  plotTrashList.querySelectorAll(".plot-trash-preview-btn").forEach((button) => {
    button.addEventListener("click", () => previewPlotFromTrash(button));
  });
  plotTrashList.querySelectorAll(".plot-trash-restore").forEach((button) => {
    button.addEventListener("click", () => restorePlotFromTrash(button));
  });
}

function resetPlotTrashPreview() {
  if (!plotTrashPreview) return;
  plotTrashPreview.innerHTML = `
    <div class="plot-trash-preview-empty">
      <strong>选择一项内容预览</strong>
      <p>选择一项内容后加载预览。</p>
    </div>
  `;
}

async function previewPlotFromTrash(button) {
  const trashId = button?.dataset.trashId || "";
  const kind = button?.dataset.kind || "plot";
  if (!trashId || !plotTrashPreview) return;
  plotTrashList?.querySelectorAll(".plot-trash-preview-btn").forEach((item) => {
    item.classList.toggle("is-active", item === button);
  });
  button.disabled = true;
  button.textContent = "加载中…";
  setPlotTrashStatus("正在加载正文预览…");
  try {
    if (button.dataset.history === "true") {
      const item = plotTrashItemsCache.find((candidate) => String(candidate.trashId) === String(trashId) && candidate.history);
      if (!item) throw new Error("这项删除记录已经失效");
      plotTrashPreview.innerHTML = `
        <header class="plot-trash-preview-head">
          <span>${escapeHtml(trashKindLabel(kind))} · ${escapeHtml(item.daysRemaining)} 天后永久删除</span>
          <h3>${escapeHtml(item.title)}</h3>
        </header>
        <div class="plot-trash-structure-preview">
          <strong>恢复会撤销这次结构删除</strong>
          <p>${escapeHtml(item.label)}</p>
          <small>同时恢复这次操作涉及的时间线或篇章配置；如果相关内容后来又被修改，系统会停止恢复并提示冲突。</small>
        </div>
      `;
      setPlotTrashStatus("结构删除会通过安全撤销恢复。");
      return;
    }
    const endpoint = kind === "plot" ? "/api/plots/trash/preview" : "/api/records/trash/preview";
    const result = await refactorApi(`${endpoint}?project=${encodeURIComponent(currentProjectId())}&trashId=${encodeURIComponent(trashId)}`);
    plotTrashPreview.style.setProperty("--accent", result.accent || "#3f7fc1");
    plotTrashPreview.innerHTML = `
      <header class="plot-trash-preview-head">
        <span>${kind === "plot" ? `原第 ${escapeHtml(result.sequence)} 章 · ` : ""}${escapeHtml(result.daysRemaining)} 天后永久删除</span>
        <h3>${escapeHtml(result.title)}</h3>
      </header>
      <div class="plot-detail-body plot-trash-preview-body">${renderMarkdownBody(result.body)}</div>
      ${result.restoreBlockedReason ? `<p class="plot-trash-restore-warning">${escapeHtml(result.restoreBlockedReason)}</p>` : ""}
    `;
    setPlotTrashStatus("预览内容来自回收站，不会修改原文件。");
  } catch (error) {
    setPlotTrashStatus(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "预览";
  }
}

async function fetchPlotTrash() {
  const [plotResult, recordResult, historyResult] = await Promise.all([
    refactorApi(`/api/plots/trash?project=${encodeURIComponent(currentProjectId())}`),
    refactorApi(`/api/records/trash?project=${encodeURIComponent(currentProjectId())}`),
    refactorApi(`/api/history/trash?project=${encodeURIComponent(currentProjectId())}`),
  ]);
  return { ...plotResult, items: [
    ...plotResult.items.map((item) => ({ ...item, kind: "plot" })),
    ...recordResult.items,
    ...historyResult.items.map((item) => ({
      ...item,
      history: true,
      trashId: String(item.id),
      kind: item.entityType,
      title: item.deletedItems?.map((deleted) => deleted.title).join("、") || item.label,
      deletedAt: item.createdAt,
      canRestore: item.canUndo,
      restoreBlockedReason: item.undoBlockedReason,
    })),
  ].sort((a, b) => Number(b.deletedAt || 0) - Number(a.deletedAt || 0)) };
}

async function refreshPlotTrashAccess() {
  try {
    await initializeRefactorWorkspace();
    if (!refactorCapability?.writable) throw new Error("只读模式");
    const result = await fetchPlotTrash();
    updatePlotTrashTrigger(result.items.length, true);
    return result.items;
  } catch {
    updatePlotTrashTrigger(0, false);
    return [];
  }
}

async function openPlotTrashDialog() {
  if (!plotTrashDialog) return;
  if (plotTrashDialog.open) return;
  moveDialogToVisibleRoot(plotTrashDialog);
  renderPlotTrashItems([]);
  resetPlotTrashPreview();
  setPlotTrashStatus("正在读取回收站…");
  plotTrashDialog.showModal();
  try {
    await initializeRefactorWorkspace();
    if (!refactorCapability?.writable) throw new Error("当前页面是只读模式，请用 run.sh 启动本地服务");
    const result = await fetchPlotTrash();
    renderPlotTrashItems(result.items);
    updatePlotTrashTrigger(result.items.length, true);
    setPlotTrashStatus(result.items.length ? "可在到期前恢复内容。" : "");
  } catch (error) {
    plotTrashList?.replaceChildren();
    setPlotTrashStatus(error.message, "error");
  }
}

function closePlotTrashDialog() {
  if (plotTrashDialog?.open) plotTrashDialog.close();
  setPlotTrashStatus();
}

async function restorePlotFromTrash(button) {
  const trashId = button?.dataset.trashId || "";
  const kind = button?.dataset.kind || "plot";
  if (!trashId) return;
  button.disabled = true;
  button.textContent = "正在恢复…";
  setPlotTrashStatus("正在恢复内容…");
  try {
    const result = button.dataset.history === "true"
      ? await refactorApi("/api/history/undo", { project: currentProjectId(), transactionId: Number(trashId) })
      : await refactorApi(kind === "plot" ? "/api/plots/trash/restore" : "/api/records/trash/restore", {
          project: currentProjectId(),
          trashId,
        });
    await refreshWorkspaceDataInPlace();
    const trash = await fetchPlotTrash();
    renderPlotTrashItems(trash.items);
    resetPlotTrashPreview();
    updatePlotTrashTrigger(trash.items.length, true);
    await refreshOperationHistoryAccess();
    setPlotTrashStatus(`已恢复“${result.title || result.name || result.label || result.id}”`, "success");
  } catch (error) {
    setPlotTrashStatus(error.message, "error");
    button.disabled = false;
    button.textContent = "恢复";
  }
}

function formatHistoryTime(timestamp) {
  const date = new Date(Number(timestamp || 0) * 1000);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString("zh-CN", { hour12: false });
}

function setOperationHistoryStatus(message = "", type = "") {
  if (!operationHistoryStatus) return;
  operationHistoryStatus.textContent = message;
  operationHistoryStatus.className = `plot-trash-status${type ? ` is-${type}` : ""}`;
}

function updateOperationHistoryTrigger(items = [], writable = false) {
  operationHistoryWorkspace?.classList.toggle("is-hidden", !writable);
  operationHistoryTrigger?.classList.toggle("is-hidden", !writable);
  if (operationHistoryCount) operationHistoryCount.textContent = String(items.filter((item) => item.canUndo).length);
}

function renderOperationHistoryItems(items = []) {
  if (!operationHistoryList) return;
  operationHistoryList.innerHTML = items.length ? items.map((item) => `
    <article class="operation-history-item${item.canUndo ? "" : " is-blocked"}">
      <div class="operation-history-type"><span>${escapeHtml(HISTORY_KIND_LABELS[item.entityType] || "内容")}</span><small>${escapeHtml(formatHistoryTime(item.createdAt))}</small></div>
      <div class="operation-history-copy">
        <strong>${escapeHtml(item.label)}</strong>
        <small>${escapeHtml(item.changedCount)} 项持久化内容发生变化 · ${escapeHtml(item.daysRemaining)} 天内可撤销</small>
        ${item.undoBlockedReason ? `<p>${escapeHtml(item.undoBlockedReason)}</p>` : ""}
      </div>
      <button class="operation-history-undo icon-action" data-transaction-id="${escapeHtml(item.id)}" type="button" aria-label="撤销${escapeHtml(item.label)}" title="${escapeHtml(item.undoBlockedReason || "撤销这项操作")}" ${item.canUndo ? "" : "disabled"}>${uiIcon("restore")}</button>
    </article>
  `).join("") : `
    <div class="plot-trash-empty"><strong>还没有可撤销操作</strong><p>之后的保存和删除会记录在这里。</p></div>
  `;
  operationHistoryList.querySelectorAll(".operation-history-undo").forEach((button) => {
    button.addEventListener("click", () => undoHistoryOperation(button));
  });
}

async function fetchOperationHistory() {
  return refactorApi(`/api/history?project=${encodeURIComponent(currentProjectId())}`);
}

async function refreshOperationHistoryAccess() {
  try {
    await initializeRefactorWorkspace();
    if (!refactorCapability?.features?.includes("operation-history-v1")) throw new Error("当前本地服务需要更新");
    const result = await fetchOperationHistory();
    updateOperationHistoryTrigger(result.items, true);
    return result.items;
  } catch {
    updateOperationHistoryTrigger([], false);
    return [];
  }
}

async function openOperationHistoryDialog() {
  if (!operationHistoryDialog || operationHistoryDialog.open) return;
  moveDialogToVisibleRoot(operationHistoryDialog);
  renderOperationHistoryItems([]);
  setOperationHistoryStatus("正在读取操作记录…");
  operationHistoryDialog.showModal();
  try {
    const result = await fetchOperationHistory();
    renderOperationHistoryItems(result.items);
    updateOperationHistoryTrigger(result.items, true);
    setOperationHistoryStatus(result.items.length ? "只会安全撤销未被后续修改覆盖的操作。" : "");
  } catch (error) {
    setOperationHistoryStatus(error.message, "error");
  }
}

function closeOperationHistoryDialog() {
  if (operationHistoryDialog?.open) operationHistoryDialog.close();
  setOperationHistoryStatus();
}

async function undoHistoryOperation(button) {
  const transactionId = Number(button?.dataset.transactionId);
  if (!transactionId) return;
  const confirmed = await showAppConfirm({
    eyebrow: "安全撤销",
    title: "撤销这项操作？",
    message: button.getAttribute("aria-label")?.replace(/^撤销/, "") || "所选操作将恢复到修改前状态。",
    detail: "撤销本身也会生成一条记录，因此仍可再次撤销。",
    variant: "warning",
    icon: "restore",
    confirmLabel: "确认撤销这项操作",
    cancelLabel: "取消撤销",
  });
  if (!confirmed) return;
  button.disabled = true;
  setOperationHistoryStatus("正在检查冲突并撤销…");
  try {
    const result = await refactorApi("/api/history/undo", { project: currentProjectId(), transactionId });
    await refreshWorkspaceDataInPlace();
    const history = await fetchOperationHistory();
    renderOperationHistoryItems(history.items);
    updateOperationHistoryTrigger(history.items, true);
    await refreshPlotTrashAccess();
    setOperationHistoryStatus(`已撤销“${result.label}”`, "success");
  } catch (error) {
    setOperationHistoryStatus(error.message, "error");
    button.disabled = false;
  }
}

function setPlotCreateBusy(busy) {
  plotCreateForm?.querySelectorAll("input, select, textarea, button").forEach((element) => {
    element.disabled = busy
      || element === plotCreateChapter
      || (Boolean(state.editingPlotId) && element === plotCreatePosition);
  });
  if (plotCreateClose) plotCreateClose.disabled = busy;
  if (plotCreateCancel) plotCreateCancel.disabled = busy;
}

function setPlotCreateMessage(message = "", type = "") {
  if (!plotCreateMessage) return;
  plotCreateMessage.textContent = message;
  plotCreateMessage.className = type ? `is-${type}` : "";
}

let plotEditorSyncedElement = null;
let plotEditorScrollUnlockFrame = 0;

function syncPlotEditorScroll(source, target) {
  if (!source || !target || plotEditorSyncedElement === source) return;
  const sourceRange = Math.max(0, source.scrollHeight - source.clientHeight);
  const targetRange = Math.max(0, target.scrollHeight - target.clientHeight);
  const progress = sourceRange > 0 ? source.scrollTop / sourceRange : 0;
  plotEditorSyncedElement = target;
  target.scrollTop = progress * targetRange;
  if (plotEditorScrollUnlockFrame) window.cancelAnimationFrame(plotEditorScrollUnlockFrame);
  plotEditorScrollUnlockFrame = window.requestAnimationFrame(() => {
    plotEditorSyncedElement = null;
    plotEditorScrollUnlockFrame = 0;
  });
}

function resetPlotEditorScroll() {
  if (plotEditorScrollUnlockFrame) window.cancelAnimationFrame(plotEditorScrollUnlockFrame);
  plotEditorScrollUnlockFrame = 0;
  plotEditorSyncedElement = null;
  if (plotCreateBody) plotCreateBody.scrollTop = 0;
  if (plotCreatePreview) plotCreatePreview.scrollTop = 0;
}

function renderPlotEditorPreview() {
  if (!plotCreatePreview) return;
  const body = plotCreateBody?.value.trim() || "";
  plotCreatePreview.style.setProperty("--accent", plotCreateAccent?.value || "#3f7fc1");
  plotCreatePreview.innerHTML = body
    ? renderMarkdownBody(body)
    : "<p>正文预览会显示在这里。</p>";
  syncPlotEditorScroll(plotCreateBody, plotCreatePreview);
}

function renderPlotInsertImpact() {
  if (!plotInsertImpact || !plotCreatePositionField || !plotCreatePosition) return;
  if (state.editingPlotId) {
    const current = plots.find((plot) => Number(plot.id) === Number(state.editingPlotId));
    const currentSequence = plotSequence(current);
    const requested = Number(plotCreatePosition.value);
    plotCreatePosition.max = String(plots.length);
    const affectedCount = Number.isInteger(requested) && requested >= 1 && requested <= plots.length
      ? Math.abs(requested - currentSequence)
      : 0;
    const orderMessage = !Number.isInteger(requested) || requested < 1 || requested > plots.length
      ? `请输入 1 到 ${plots.length} 之间的章节顺序。`
      : (requested === currentSequence
        ? "阅读顺序保持不变。"
        : `保存后移动到第 ${requested} 章，并自动调整 ${affectedCount} 篇文章的顺序；已有引用不变。`);
    plotInsertImpact.innerHTML = `
      <strong>稳定 ID ${escapeHtml(state.editingPlotId)}</strong>
      <span>${escapeHtml(orderMessage)}</span>
    `;
    return;
  }
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
  moveDialogToVisibleRoot(plotCreateDialog);
  state.editingPlotId = null;
  plotCreateForm.reset();
  plotCreateSettings?.removeAttribute("open");
  document.querySelector("#plotCreateTitle").textContent = "写新剧情";
  setIconButton(plotCreateSubmit, "save", "保存剧情");
  const positionLabel = plotCreatePositionField?.querySelector("span");
  if (positionLabel) positionLabel.textContent = "放在第几章";
  if (plotCreateAccent) plotCreateAccent.value = "#3f7fc1";
  if (plotCreatePosition) plotCreatePosition.value = String(nextPlotSequence());
  renderPlotReferenceOptions();
  if (plotCreateChapter) {
    plotCreateChapter.innerHTML = chapterKeys().map((chapter) => (
      `<option value="${escapeHtml(chapter)}">${escapeHtml(chapterName(chapter))}</option>`
    )).join("");
  }
  renderPlotEditorPreview();
  resetPlotEditorScroll();
  renderPlotInsertImpact();
  setPlotCreateMessage("正在连接本地内容库…");
  setPlotCreateBusy(true);
  plotCreateDialog.showModal();
  try {
    await initializeRefactorWorkspace();
    if (!refactorCapability?.writable) throw new Error("当前页面是只读模式，请用 run.sh 启动本地服务");
    setPlotCreateBusy(false);
    setPlotCreateMessage("支持 Markdown；人物和设定会在保存后自动识别。");
    plotCreateBody?.focus();
  } catch (error) {
    setPlotCreateMessage(error.message, "error");
    if (plotCreateClose) plotCreateClose.disabled = false;
    if (plotCreateCancel) plotCreateCancel.disabled = false;
  }
}

async function openPlotEditDialog(plotId) {
  const plot = plots.find((item) => Number(item.id) === Number(plotId));
  if (!plotCreateDialog || !plotCreateForm || !plot) return;
  moveDialogToVisibleRoot(plotCreateDialog);
  state.editingPlotId = Number(plot.id);
  plotCreateForm.reset();
  plotCreateSettings?.removeAttribute("open");
  document.querySelector("#plotCreateTitle").textContent = "修改剧情";
  setIconButton(plotCreateSubmit, "save", "保存修改");
  const positionLabel = plotCreatePositionField?.querySelector("span");
  if (positionLabel) positionLabel.textContent = "当前章节顺序";
  if (plotCreateChapter) {
    plotCreateChapter.innerHTML = chapterKeys().map((chapter) => (
      `<option value="${escapeHtml(chapter)}">${escapeHtml(chapterName(chapter))}</option>`
    )).join("");
    plotCreateChapter.value = plot.chapter || chapterKeys()[0];
  }
  if (plotCreateName) plotCreateName.value = plot.title || "";
  if (plotCreatePosition) plotCreatePosition.value = String(plotSequence(plot));
  selectPlotEditorStatus(plot.status);
  if (plotCreateAccent) plotCreateAccent.value = plot.accent || "#3f7fc1";
  if (plotCreateSummary) plotCreateSummary.value = plot.summary || "";
  if (plotCreateLanes) plotCreateLanes.value = (plot.lanes || []).join("，");
  if (plotCreateTags) plotCreateTags.value = (plot.tags || []).join("，");
  renderPlotReferenceOptions(plot);
  if (plotCreateKey) plotCreateKey.checked = Boolean(plot.key);
  if (plotCreateClimax) plotCreateClimax.checked = Boolean(plot.climax);
  if (plotCreateBody) plotCreateBody.value = plot.text || "";
  renderPlotEditorPreview();
  resetPlotEditorScroll();
  renderPlotInsertImpact();
  setPlotCreateMessage("正在连接本地内容库…");
  setPlotCreateBusy(true);
  plotCreateDialog.showModal();
  try {
    await initializeRefactorWorkspace();
    if (!refactorCapability?.writable) throw new Error("当前页面是只读模式，请用 run.sh 启动本地服务");
    setPlotCreateBusy(false);
    setPlotCreateMessage("可以修改正文、关联和阅读顺序；稳定 ID 与已有引用保持不变。");
    plotCreateBody?.focus();
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
  state.editingPlotId = null;
  pendingFragmentConversionId = "";
}

async function createPlotFromEditor(event) {
  event.preventDefault();
  if (!plotCreateForm?.checkValidity()) {
    plotCreateSettings?.setAttribute("open", "");
    plotCreateForm.reportValidity();
    return;
  }
  const editingPlotId = Number(state.editingPlotId) || null;
  const requestedSequence = Number(plotCreatePosition?.value);
  const shiftingExistingPlots = !editingPlotId && requestedSequence < nextPlotSequence();
  setPlotCreateBusy(true);
  setPlotCreateMessage(editingPlotId
    ? "正在保存修改…"
    : (shiftingExistingPlots ? "正在插入剧情并顺移后续章节…" : "正在保存新剧情…"));
  try {
    const result = await refactorApi(editingPlotId ? "/api/plots/update" : "/api/plots/create", {
      project: currentProjectId(),
      ...(editingPlotId ? { id: editingPlotId } : {}),
      title: plotCreateName?.value.trim() || "",
      chapter: plotCreateChapter?.value || chapterKeys()[0],
      ...(!editingPlotId ? { insertAt: requestedSequence } : { sequence: requestedSequence }),
      status: plotCreateStatusField?.value || "草稿",
      accent: plotCreateAccent?.value || "#3f7fc1",
      summary: plotCreateSummary?.value.trim() || "",
      lanes: plotEditorListValues(plotCreateLanes?.value),
      tags: plotEditorListValues(plotCreateTags?.value),
      people: selectedPlotReferences(plotCreatePeople),
      entries: selectedPlotReferences(plotCreateEntries),
      key: Boolean(plotCreateKey?.checked),
      climax: Boolean(plotCreateClimax?.checked),
      body: plotCreateBody?.value.trim() || "",
    });
    if (!editingPlotId && pendingFragmentConversionId) {
      await refactorApi("/api/records/delete", {
        project: currentProjectId(),
        kind: "fragment",
        id: pendingFragmentConversionId,
      });
      pendingFragmentConversionId = "";
    }
    setPlotCreateMessage(editingPlotId
      ? "修改已保存"
      : `已保存为第 ${result.sequence} 章${result.shiftedCount ? `，${result.shiftedCount} 章已顺延` : ""}。`, "success");
    await refreshWorkspaceDataInPlace({ plotId: result.id });
    closePlotCreateDialog();
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

function fragmentPreviewText(text, limit = 220) {
  const container = document.createElement("div");
  container.innerHTML = renderMarkdownBody(text || "");
  const normalized = String(container.textContent || "").replace(/\s+/g, " ").trim();
  return normalized.length > limit ? `${normalized.slice(0, limit).trimEnd()}…` : normalized;
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
      <div class="fragment-body" aria-label="${escapeHtml(fragment.title)}摘要"><p>${escapeHtml(fragmentPreviewText(fragment.text) || "暂无正文")}</p></div>
      <div class="fragment-actions" aria-label="${escapeHtml(fragment.title)}的操作"><button class="fragment-edit-record icon-action" data-id="${escapeHtml(fragment.id)}" type="button" aria-label="编辑${escapeHtml(fragment.title)}" title="编辑碎片">${uiIcon("edit")}</button><button class="fragment-immersive-record icon-action" data-id="${escapeHtml(fragment.id)}" type="button" aria-label="沉浸式编写${escapeHtml(fragment.title)}" title="沉浸式编写">${uiIcon("maximize")}</button><button class="fragment-convert-record icon-action" data-id="${escapeHtml(fragment.id)}" type="button" aria-label="将${escapeHtml(fragment.title)}转为剧情" title="转为剧情">${uiIcon("convert")}</button><button class="fragment-delete-record icon-action is-danger" data-id="${escapeHtml(fragment.id)}" type="button" aria-label="删除${escapeHtml(fragment.title)}" title="删除碎片">${uiIcon("trash")}</button></div>
    </article>
  `).join("") : '<p class="empty-state">没有匹配的碎片。</p>';
  fragmentBoard.querySelectorAll(".fragment-edit-record").forEach((button) => button.addEventListener("click", () => {
    const fragment = fragments.find((item) => String(item.id) === button.dataset.id);
    if (fragment) openContentEditor("fragment", fragment);
  }));
  fragmentBoard.querySelectorAll(".fragment-immersive-record").forEach((button) => button.addEventListener("click", () => {
    const fragment = fragments.find((item) => String(item.id) === button.dataset.id);
    if (fragment) openContentEditor("fragment", fragment, { immersive: true });
  }));
  fragmentBoard.querySelectorAll(".fragment-convert-record").forEach((button) => button.addEventListener("click", () => {
    const fragment = fragments.find((item) => String(item.id) === button.dataset.id);
    if (fragment) convertFragmentToPlot(fragment);
  }));
  fragmentBoard.querySelectorAll(".fragment-delete-record").forEach((button) => button.addEventListener("click", () => {
    const fragment = fragments.find((item) => String(item.id) === button.dataset.id);
    if (fragment) deleteContentRecord("fragment", fragment);
  }));
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
