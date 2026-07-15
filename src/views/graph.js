let graphLinesReady = false;
let graphDataDirty = false;

function switchView(view, { resetStory = false } = {}) {
  const previousView = state.view;
  const activeNav = view === "plot-detail" ? "story" : view;
  if (view === "story" && resetStory) resetStoryNavigationState();
  if (previousView === "graph" && view !== "graph") {
    graphStage?.classList.add("has-completed-node-entry");
  }
  document.querySelector("#readingProgress")?.classList.toggle("is-hidden", view !== "plot-detail");
  document.querySelectorAll(".view-btn").forEach((item) => item.classList.toggle("is-active", item.dataset.view === activeNav));
  document.querySelectorAll(".page-view").forEach((page) => page.classList.toggle("is-active", page.dataset.page === view));
  document.body.classList.toggle("is-graph-view", view === "graph");
  document.body.classList.toggle("is-timeline-view", view === "timeline");
  state.view = view;

  if (state.view === "graph") {
    if (graphDataDirty) {
      renderGraphFilters();
      renderNodes();
      renderLinks();
      graphDataDirty = false;
    }
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
    if (!state.selectedCharacter) {
      const fallback = characters.find((person) => !isTemporaryCharacter(person)) || characters[0];
      state.selectedCharacter = fallback?.id || "";
      if (fallback) setCharacterShelfForPerson(fallback);
    }
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
    refreshPlotTrashAccess();
    refreshOperationHistoryAccess();
  }
  if (state.view === "story" && (previousView !== "story" || resetStory)) {
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
  setIconButton(profileDetailBtn, "convert", `进入${person.name}的完整档案`);
  personIntro.innerHTML = renderBulletNoteItems(person.intro);
  personAvatar.innerHTML = avatarContent(person);
  personAvatar.classList.toggle("has-image", Boolean(person.avatar));
  personAvatar.style.setProperty("--selected-gradient", person.gradient);
  profileFloat.style.setProperty("--accent", person.color);

  eventList.innerHTML = items
    .map((plot, index) => `
      <button
        class="event-item"
        data-plot-id="${escapeHtml(plot.id)}"
        type="button"
        style="--accent:${escapeHtml(plot.accent)}; animation-delay:${index * 70}ms"
        aria-label="打开《${escapeHtml(plot.title)}》，${escapeHtml(chapterName(plot.chapter))}第 ${escapeHtml(plotSequence(plot))} 章"
      >
        <span class="event-dot"></span>
        <span class="event-copy">
          <strong>${escapeHtml(plot.title)}</strong>
          <small>${escapeHtml(chapterName(plot.chapter))} · 第 ${escapeHtml(plotSequence(plot))} 章</small>
          <p>${escapeHtml(markdownExcerpt(plot.text, 120))}</p>
        </span>
        <span class="event-arrow" aria-hidden="true">→</span>
      </button>
    `)
    .join("");
  eventList.querySelectorAll(".event-item[data-plot-id]").forEach((button) => {
    button.addEventListener("click", () => openPlotDetail(Number(button.dataset.plotId)));
  });
  profileFloat.classList.remove("is-hidden");
}

function renderNodes() {
  nodeLayer.innerHTML = "";
  const visibleGraphCharacters = graphCharacters();
  const shouldAnimateEntry = Boolean(
    graphStage
    && !graphStage.classList.contains("has-completed-node-entry")
    && !reducedMotionQuery.matches,
  );
  graphLinesReady = !shouldAnimateEntry;
  graphStage?.classList.toggle("is-lines-ready", graphLinesReady);
  graphStage?.classList.toggle("is-entering-nodes", shouldAnimateEntry);
  visibleGraphCharacters.forEach((person, index) => {
    const node = document.createElement("button");
    node.className = "person-node";
    node.type = "button";
    node.dataset.id = person.id;
    node.setAttribute("aria-label", `选中${person.name}，查看关联剧情`);
    node.title = "查看关联剧情";
    node.style.setProperty("--accent", person.color);
    node.style.setProperty("--avatar-gradient", person.gradient);
    node.style.animationDelay = shouldAnimateEntry ? `${index * 36}ms` : "0ms";
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
  scheduleGraphLinesReveal(visibleGraphCharacters.length, shouldAnimateEntry);
}

function renderLinks() {
  drawGraph();
}

function scheduleGraphLinesReveal(nodeCount, shouldAnimateEntry) {
  window.clearTimeout(graphNodeEntryTimer);
  if (!graphStage) return;
  if (!shouldAnimateEntry) {
    revealGraphLines();
    return;
  }
  const entryDuration = 540 + Math.max(0, nodeCount - 1) * 36;
  graphNodeEntryTimer = window.setTimeout(() => {
    revealGraphLines();
  }, entryDuration);
}

function revealGraphLines() {
  if (!graphStage) return;
  graphLinesReady = true;
  graphStage.classList.add("has-completed-node-entry");
  requestAnimationFrame(() => {
    graphStage.classList.remove("is-entering-nodes");
    graphStage.classList.add("is-lines-ready");
    drawGraph();
  });
}

function selectPerson(id) {
  const person = getCharacter(id);
  if (!person) return;
  if (!isGraphCharacter(person)) {
    openCharacterDetail(id);
    return;
  }
  state.selected = id;
  state.hasSelection = true;
  state.selectedCharacter = id;
  freezeGraphSimulation();
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
        if (!isGraphCharacter(getCharacter(link.from)) || !isGraphCharacter(getCharacter(link.to))) return;
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
    node.classList.toggle("is-soft-anchored", Number.isFinite(person?.manualAnchorX) && Number.isFinite(person?.manualAnchorY));
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
  const previousWidth = state.width;
  const previousHeight = state.height;
  state.width = bounds.width;
  state.height = bounds.height;
  const resized = Math.abs(previousWidth - state.width) > 1 || Math.abs(previousHeight - state.height) > 1;

  const layoutCharacters = graphCharacters();
  let initializedPosition = false;
  layoutCharacters.forEach((person, index) => {
    if (!Number.isFinite(person.px) || !Number.isFinite(person.py)) {
      const goldenAngle = Math.PI * (3 - Math.sqrt(5));
      const progress = Math.sqrt((index + 0.5) / Math.max(1, layoutCharacters.length));
      const importance = normalizeMainPlotImpact(person.mainPlotImpact) / 100;
      const crowdScale = Math.min(1.7, Math.max(1, Math.sqrt(layoutCharacters.length / 12)));
      const radius = Math.min(state.width, state.height)
        * (0.12 + progress * 0.44)
        * crowdScale
        * (1.06 - importance * 0.18);
      const angle = index * goldenAngle + stableNoise(person.id, "initial-angle") * 0.28;
      const point = jitterPoint(
        state.width / 2 + Math.cos(angle) * radius,
        state.height / 2 + Math.sin(angle) * radius,
        person.id,
        Number(graphLayoutConfig.initialJitter || 34),
        "initial",
      );
      person.px = point.x;
      person.py = point.y;
      initializedPosition = true;
    }
    person.vx = person.vx || 0;
    person.vy = person.vy || 0;
    person.lastFinitePx = person.px;
    person.lastFinitePy = person.py;
  });
  if (initializedPosition) prewarmGraphLayout(Number(graphLayoutConfig.prewarmTicks || 520));
  updateGraphViewport();
  if (initializedPosition && graphSimulationActive) startGraphLoop();
  if (!initializedPosition && resized) wakeGraphSimulation();
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
  drawGraph();
}

function updateGraphViewport() {
  if (!state.width || !state.height) return;
  nodeLayer.style.transform = `translate(${state.graphPanX}px, ${state.graphPanY}px) scale(${state.graphScale})`;
  graphWrap.classList.toggle("hide-labels", graphCharacters().length > 10 || state.graphScale < 0.75);
}

function canMovePerson(person) {
  return state.dragging?.id !== person.id;
}

function pushPerson(person, vx, vy) {
  if (!person || !canMovePerson(person)) return;
  person.vx += vx;
  person.vy += vy;
}

function restoreFiniteGraphState() {
  let restored = false;
  graphCharacters().forEach((person, index) => {
    if (!Number.isFinite(person.px) || !Number.isFinite(person.py)) {
      const angle = index * Math.PI * (3 - Math.sqrt(5));
      const radius = Math.min(state.width, state.height) * 0.18;
      person.px = Number.isFinite(person.lastFinitePx)
        ? person.lastFinitePx
        : state.width / 2 + Math.cos(angle) * radius;
      person.py = Number.isFinite(person.lastFinitePy)
        ? person.lastFinitePy
        : state.height / 2 + Math.sin(angle) * radius;
      restored = true;
    }
    if (!Number.isFinite(person.vx) || !Number.isFinite(person.vy)) {
      person.vx = 0;
      person.vy = 0;
      restored = true;
    }
    person.lastFinitePx = person.px;
    person.lastFinitePy = person.py;
  });
  return restored;
}

function nudgeToward(person, x, y, strength = 0.02) {
  if (!person || !canMovePerson(person)) return;
  const vx = (x - person.px) * strength;
  const vy = (y - person.py) * strength;
  const force = Math.max(1, Math.hypot(vx, vy));
  const capped = Math.min(3.4, force);
  person.vx += (vx / force) * capped;
  person.vy += (vy / force) * capped;
}

function applyPairDistance(a, b, targetDistance, strength = 0.45) {
  if (!a || !b || !targetDistance) return;
  const dx = b.px - a.px;
  const dy = b.py - a.py;
  const distance = Math.max(1, Math.hypot(dx, dy));
  const force = (distance - targetDistance) * 0.00038 * strength;
  const nx = dx / distance;
  const ny = dy / distance;
  pushPerson(a, nx * force, ny * force);
  pushPerson(b, -nx * force, -ny * force);
}

function graphNodeSpacing(multiplier = 1) {
  const configuredSpacing = Number(graphLayoutConfig.nodeSpacing);
  const visualMinimum = Number(graphLayoutConfig.minVisualNodeSpacing || 166);
  const baseSpacing = Number.isFinite(configuredSpacing) && configuredSpacing > 0
    ? configuredSpacing
    : visualMinimum;
  return Math.max(visualMinimum, baseSpacing) * multiplier;
}

function applyNaturalGroupForces() {
  const groups = new Map();
  graphCharacters().forEach((person) => {
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
    const strength = Number(graphLayoutConfig.groupStrength || 1);
    members.forEach((person) => nudgeToward(person, center.x, center.y, 0.0018 * strength));
  });
}

function buildGraphTopology() {
  const visibleCharacters = graphCharacters();
  const neighbors = new Map(visibleCharacters.map((person) => [person.id, []]));
  relationships.forEach((link) => {
    const from = getCharacter(link.from);
    const to = getCharacter(link.to);
    if (!isGraphCharacter(from) || !isGraphCharacter(to)) return;
    neighbors.get(from.id).push({ person: to, link });
    neighbors.get(to.id).push({ person: from, link });
  });
  return neighbors;
}

function automaticRelationshipDistance(link, topology) {
  const configuredDistance = Number(link.distance);
  if (Number.isFinite(configuredDistance) && configuredDistance > 0) return configuredDistance;
  const baseDistance = Number(graphLayoutConfig.relationshipDistance || 250);
  const fromDegree = topology.get(link.from)?.length || 0;
  const toDegree = topology.get(link.to)?.length || 0;
  const leafExtra = fromDegree === 1 || toDegree === 1
    ? Number(graphLayoutConfig.leafDistanceExtra || 48)
    : 0;
  return baseDistance + leafExtra;
}

function applyAutomaticCenterForces(topology) {
  const visibleCharacters = graphCharacters();
  if (!visibleCharacters.length || !state.width || !state.height) return;
  const center = graphPoint();
  const strength = Number(graphLayoutConfig.centerStrength || 1);
  const movable = visibleCharacters.filter((person) => canMovePerson(person));
  if (movable.length) {
    const centroid = movable.reduce((sum, person) => ({
      x: sum.x + person.px,
      y: sum.y + person.py,
    }), { x: 0, y: 0 });
    centroid.x /= movable.length;
    centroid.y /= movable.length;
    const correctionX = (center.x - centroid.x) * 0.0014 * strength;
    const correctionY = (center.y - centroid.y) * 0.0014 * strength;
    movable.forEach((person) => pushPerson(person, correctionX, correctionY));
  }

  const maxDegree = Math.max(1, ...visibleCharacters.map((person) => topology.get(person.id)?.length || 0));
  const radiusLimit = Math.min(state.width, state.height) * 0.34;

  visibleCharacters.forEach((person) => {
    const importance = normalizeMainPlotImpact(person.mainPlotImpact) / 100;
    const connectedness = (topology.get(person.id)?.length || 0) / maxDegree;
    const centrality = importance * 0.76 + connectedness * 0.24;
    const radius = radiusLimit * (1 - centrality) + 24;
    const angle = (stableNoise(person.id, "automatic-center") + 1) * Math.PI;
    nudgeToward(
      person,
      center.x + Math.cos(angle) * radius,
      center.y + Math.sin(angle) * radius,
      0.0011 * strength,
    );
  });
}

function applyAutomaticLeafForces(topology) {
  const center = graphPoint();
  const strength = Number(graphLayoutConfig.leafStrength || 1);
  topology.forEach((connections, id) => {
    if (connections.length !== 1) return;
    const person = getCharacter(id);
    const { person: anchor, link } = connections[0];
    if (!person || !anchor) return;
    const anchorConnections = topology.get(anchor.id)?.length || 0;
    if (
      anchorConnections === 1
      && person.mainPlotImpact >= anchor.mainPlotImpact
    ) return;

    const leafSiblings = (topology.get(anchor.id) || [])
      .map((connection) => connection.person)
      .filter((candidate) => (topology.get(candidate.id)?.length || 0) === 1)
      .sort(compareCharacterPriority);
    const siblingIndex = Math.max(0, leafSiblings.findIndex((candidate) => candidate.id === person.id));
    const spread = Math.min(Math.PI * 0.82, Math.max(0, leafSiblings.length - 1) * 0.44);
    const offset = leafSiblings.length > 1
      ? -spread / 2 + (spread * siblingIndex) / (leafSiblings.length - 1)
      : 0;
    const dx = anchor.px - center.x;
    const dy = anchor.py - center.y;
    const baseAngle = Math.hypot(dx, dy) < 24
      ? (stableNoise(anchor.id, "leaf-anchor") + 1) * Math.PI
      : Math.atan2(dy, dx);
    const angle = baseAngle + offset;
    const targetDistance = automaticRelationshipDistance(link, topology);
    nudgeToward(
      person,
      anchor.px + Math.cos(angle) * targetDistance,
      anchor.py + Math.sin(angle) * targetDistance,
      0.0038 * strength,
    );
  });
}

function applyAutomaticLayoutBounds() {
  const width = Number(state.width);
  const height = Number(state.height);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return;
  const spacing = graphNodeSpacing();
  const visibleCharacters = graphCharacters();
  const expansion = Math.max(1, Math.sqrt(Math.max(1, visibleCharacters.length) / 24));
  const margin = spacing * 0.7;
  const minX = width / 2 - Math.max(1, width / 2 - margin) * expansion;
  const maxX = width / 2 + Math.max(1, width / 2 - margin) * expansion;
  const minY = height / 2 - Math.max(1, height / 2 - margin) * expansion;
  const maxY = height / 2 + Math.max(1, height / 2 - margin) * expansion;

  visibleCharacters.forEach((person) => {
    if (!canMovePerson(person) || !Number.isFinite(person.px) || !Number.isFinite(person.py)) return;
    const correctionX = person.px < minX
      ? minX - person.px
      : person.px > maxX
        ? maxX - person.px
        : 0;
    const correctionY = person.py < minY
      ? minY - person.py
      : person.py > maxY
        ? maxY - person.py
        : 0;
    if (Number.isFinite(correctionX) && Number.isFinite(correctionY)) {
      pushPerson(person, correctionX * 0.012, correctionY * 0.012);
    }
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
  const person = getCharacter(id);
  if (isGraphCharacter(person)) nudgeToward(person, x, y, strength);
}

function formationCenter(formation) {
  const anchorCandidate = getCharacter(formation.anchorNode || formation.bindMember || "");
  const anchor = isGraphCharacter(anchorCandidate) ? anchorCandidate : null;
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
    const from = getCharacter(rule.from);
    const to = getCharacter(rule.to);
    if (!isGraphCharacter(from) || !isGraphCharacter(to)) return;
    applyPairDistance(
      from,
      to,
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
      .filter(isGraphCharacter);
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
    if (!isGraphCharacter(person) || !isGraphCharacter(anchor)) return;
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

function applyManualAnchorForces() {
  const deadZone = Number(graphLayoutConfig.manualAnchorDeadZone || 34);
  const baseStrength = Number(graphLayoutConfig.manualAnchorStrength || 0.006);
  graphCharacters().forEach((person) => {
    if (
      !canMovePerson(person)
      || !Number.isFinite(person.manualAnchorX)
      || !Number.isFinite(person.manualAnchorY)
    ) return;
    const dx = person.manualAnchorX - person.px;
    const dy = person.manualAnchorY - person.py;
    const distance = Math.hypot(dx, dy);
    if (distance <= deadZone) return;
    const strength = baseStrength * Math.min(1.8, distance / graphNodeSpacing());
    nudgeToward(person, person.manualAnchorX, person.manualAnchorY, strength);
  });
}

function applyGraphLayoutForces(topology) {
  applyAutomaticCenterForces(topology);
  applyNaturalGroupForces();
  applyAutomaticLeafForces(topology);
  applyAutomaticLayoutBounds();
  applyFormationForces();
  applyClusterForces();
  applyConfiguredDistanceForces();
  applyOrbitForces();
  applyManualAnchorForces();
}

function forEachNearbyCharacterPair(maxDistance, callback) {
  const cellSize = Math.max(1, maxDistance);
  const buckets = new Map();
  graphCharacters().forEach((person, index) => {
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
  const minDistance = graphNodeSpacing();
  let maxSeparationSpeed = 0;
  forEachNearbyCharacterPair(minDistance, (a, b) => {
    const { distance, nx, ny } = separationVector(a, b);
    if (distance >= minDistance) return;
    const overlap = minDistance - distance;
    const correction = Math.min(28, overlap * 0.52 + 0.8);
    const aCanMove = canMovePerson(a);
    const bCanMove = canMovePerson(b);
    if (aCanMove && bCanMove) {
      a.px -= nx * correction * 0.5;
      a.py -= ny * correction * 0.5;
      b.px += nx * correction * 0.5;
      b.py += ny * correction * 0.5;
      a.vx *= 0.54;
      a.vy *= 0.54;
      b.vx *= 0.54;
      b.vy *= 0.54;
      maxSeparationSpeed = Math.max(maxSeparationSpeed, correction);
      return;
    }
    if (aCanMove) {
      a.px -= nx * correction;
      a.py -= ny * correction;
      a.vx *= 0.54;
      a.vy *= 0.54;
      maxSeparationSpeed = Math.max(maxSeparationSpeed, correction);
    }
    if (bCanMove) {
      b.px += nx * correction;
      b.py += ny * correction;
      b.vx *= 0.54;
      b.vy *= 0.54;
      maxSeparationSpeed = Math.max(maxSeparationSpeed, correction);
    }
  });
  return maxSeparationSpeed;
}

function resolveDraggedNodeOverlap(person) {
  const minDistance = graphNodeSpacing();
  for (let pass = 0; pass < 4; pass += 1) {
    let moved = false;
    graphCharacters().forEach((other) => {
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
  startGraphLoop();
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
  drawGraph();
}, { passive: false });

window.addEventListener("pointermove", (event) => {
  if (state.panning) {
    if (Math.hypot(event.clientX - state.panning.startClientX, event.clientY - state.panning.startClientY) > 5) {
      state.panning.moved = true;
    }
    state.graphPanX = state.panning.startPanX + event.clientX - state.panning.startClientX;
    state.graphPanY = state.panning.startPanY + event.clientY - state.panning.startClientY;
    drawGraph();
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
    drawGraph();
  }
});

window.addEventListener("pointerup", () => {
  if (state.panning && !state.panning.moved) clearGraphSelection();
  if (state.dragging?.moved) {
    const person = getCharacter(state.dragging.id);
    if (person) {
      resolveDraggedNodeOverlap(person);
      person.manualAnchorX = person.px;
      person.manualAnchorY = person.py;
      person.vx = 0;
      person.vy = 0;
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
  if (state.hasSelection) {
    freezeGraphSimulation();
    startGraphLoop();
    return;
  }
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

function freezeGraphSimulation() {
  graphSimulationActive = false;
  graphSimulationTicks = GRAPH_MAX_SIMULATION_TICKS;
  graphStableFrames = GRAPH_STABLE_FRAME_TARGET;
  graphCharacters().forEach((person) => {
    person.vx = 0;
    person.vy = 0;
    person.lastFinitePx = person.px;
    person.lastFinitePy = person.py;
  });
}

function prewarmGraphLayout(maxTicks = 180) {
  if (state.hasSelection) {
    freezeGraphSimulation();
    return;
  }
  graphSimulationActive = true;
  graphSimulationTicks = 0;
  graphStableFrames = 0;
  const deadline = performance.now() + Number(graphLayoutConfig.prewarmBudgetMs || 18);
  const ticks = Math.max(0, Math.min(420, Number(maxTicks) || 0));
  for (let tickIndex = 0; tickIndex < ticks && graphSimulationActive; tickIndex += 1) {
    if (performance.now() > deadline) break;
    stepGraphSimulation();
  }
}

function stepGraphSimulation() {
  if (state.hasSelection) {
    freezeGraphSimulation();
    return;
  }
  const topology = buildGraphTopology();
  const repelDistance = graphNodeSpacing(1.08);
  forEachNearbyCharacterPair(repelDistance, (a, b) => {
    const { distance: rawDistance, nx, ny } = separationVector(b, a);
    const distance = Math.max(1, rawDistance);
    const push = Math.max(0, repelDistance - distance) * 0.00135;
    const selectedPush = state.hasSelection && (a.id === state.selected || b.id === state.selected) ? 0.0012 : 0;
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
    if (!isGraphCharacter(a) || !isGraphCharacter(b)) return;
    applyPairDistance(
      a,
      b,
      automaticRelationshipDistance(link, topology),
      Number(link.strength || 1),
    );
  });

  applyGraphLayoutForces(topology);
  if (restoreFiniteGraphState()) {
    graphSimulationActive = false;
    return;
  }

  let maxSpeed = 0;
  graphCharacters().forEach((person) => {
    if (canMovePerson(person)) {
      person.vx *= 0.74;
      person.vy *= 0.74;
      const speed = Math.hypot(person.vx, person.vy);
      const maxVelocity = Number(graphLayoutConfig.maxVelocity || 7);
      if (speed > maxVelocity) {
        person.vx = (person.vx / speed) * maxVelocity;
        person.vy = (person.vy / speed) * maxVelocity;
      }
      person.px += person.vx;
      person.py += person.vy;
      maxSpeed = Math.max(maxSpeed, Math.hypot(person.vx, person.vy));
    }
  });

  maxSpeed = Math.max(maxSpeed, separateOverlappingNodes());
  if (restoreFiniteGraphState()) {
    graphSimulationActive = false;
    return;
  }

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
  const visibleCharacters = graphCharacters().filter((person) => isVisiblePerson(person) && hasPosition(person));
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
      color: link.color || "#6676c7",
      visible: Boolean(graphLinesReady && from && to && hasPosition(from) && hasPosition(to) && isVisibleRelationship(link)),
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
  const scene = graphRenderScene(time);
  graphRenderer?.render(scene);
}
