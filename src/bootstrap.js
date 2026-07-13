function setGlobalSearchOpen(open, options = {}) {
  if (!globalSearchContainer) return;
  globalSearchContainer.classList.toggle("is-open", open);
  globalSearchToggle?.setAttribute("aria-expanded", open ? "true" : "false");
  globalSearchToggle?.setAttribute("aria-label", open ? "关闭搜索" : "打开搜索");
  if (open && options.focus !== false) {
    requestAnimationFrame(() => globalSearch?.focus());
  }
}

globalSearchToggle?.addEventListener("click", () => {
  setGlobalSearchOpen(!globalSearchContainer?.classList.contains("is-open"));
});

globalSearch?.addEventListener("focus", () => {
  setGlobalSearchOpen(true, { focus: false });
});

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
    setGlobalSearchOpen(false);
    globalSearch.blur();
  }
});

document.addEventListener("click", (event) => {
  if (event.target.closest(".global-search")) return;
  hideGlobalSearchResults();
  setGlobalSearchOpen(false);
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

temporaryCharacterToggle?.addEventListener("click", () => {
  state.characterShelf = state.characterShelf === "temporary" ? "main" : "temporary";
  state.characterSearch = "";
  state.characterCategory = "all";
  state.characterGroup = "all";
  if (characterSearch) characterSearch.value = "";
  const nextPerson = characters.find((person) => (
    state.characterShelf === "temporary" ? isTemporaryCharacter(person) : !isTemporaryCharacter(person)
  ));
  state.selectedCharacter = nextPerson?.id || "";
  renderCharacterList();
  renderCharacterDetail();
});

characterCreateTrigger?.addEventListener("click", openCharacterCreateDialog);
characterCreateClose?.addEventListener("click", closeCharacterCreateDialog);
characterCreateCancel?.addEventListener("click", closeCharacterCreateDialog);
characterCreateForm?.addEventListener("submit", createCharacterFromDialog);

sideTaskToggle?.addEventListener("click", () => {
  state.plotShelf = state.plotShelf === "side" ? "all" : "side";
  state.chapter = "all";
  state.plotStatus = "all";
  state.plotTags = allPlotTags();
  state.plotPage = 1;
  renderChapterSwitch();
  renderStoryFilters();
  renderPlots();
});

plotCreateTrigger?.addEventListener("click", openPlotCreateDialog);
plotCreateClose?.addEventListener("click", closePlotCreateDialog);
plotCreateCancel?.addEventListener("click", closePlotCreateDialog);
plotCreateForm?.addEventListener("submit", createPlotFromEditor);
plotCreatePosition?.addEventListener("input", renderPlotInsertImpact);
plotCreateBody?.addEventListener("input", renderPlotEditorPreview);
plotCreateAccent?.addEventListener("input", renderPlotEditorPreview);

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
  hideCharacterDensityFloat();
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
    color: [
      "rgba(42, 167, 155, 0.2)",
      "rgba(223, 118, 85, 0.16)",
      "rgba(63, 127, 193, 0.18)",
      "rgba(216, 182, 74, 0.18)",
      "rgba(214, 95, 143, 0.14)",
    ][index % 5],
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
relationshipCreateForm?.addEventListener("submit", createRelationship);
relationshipFirstPerson?.addEventListener("change", () => {
  if (relationshipFirstPerson.value === relationshipSecondPerson?.value) {
    relationshipSecondPerson.value = characters
      .map((person) => String(person.id))
      .find((id) => id !== relationshipFirstPerson.value && !relationshipPairExists(relationshipFirstPerson.value, id))
      || "";
  }
  updateRelationshipPairState();
});
relationshipSecondPerson?.addEventListener("change", updateRelationshipPairState);

profileDetailBtn.addEventListener("click", () => {
  if (!state.selected) return;
  openCharacterDetail(state.selected);
});

characterDetail.addEventListener("click", (event) => {
  const button = event.target.closest(".relation-row[data-character-id]");
  if (!button || !characterDetail.contains(button)) return;
  const person = getCharacter(button.dataset.characterId);
  if (person) setCharacterShelfForPerson(person);
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
    state.selectedCharacter = (characters.find((person) => !isTemporaryCharacter(person)) || characters[0])?.id || "";
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
    const pendingPlotId = Number(window.sessionStorage?.getItem("story-teller-open-plot"));
    if (pendingPlotId && plots.some((plot) => Number(plot.id) === pendingPlotId)) {
      window.sessionStorage.removeItem("story-teller-open-plot");
      openPlotDetail(pendingPlotId);
    } else {
      switchView("graph");
      startGraphLoop();
    }
  } catch (error) {
    plotStrip.innerHTML = `
      <article class="plot-card" style="--accent:#df7655">
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
