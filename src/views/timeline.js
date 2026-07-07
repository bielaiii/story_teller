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
  const hues = [204, 337, 164, 38, 262, 186, 14, 116, 286, 224];
  const hue = hues[index % hues.length];
  const lightness = index >= hues.length ? 46 + ((index - hues.length) % 3) * 3 : 48;
  return `hsl(${hue} 58% ${lightness}%)`;
}

function assignTimelineColors(lines, branchConfigs, connectors, palette, mainLineName) {
  const colorMap = new Map();
  const basePalette = palette.length
    ? palette.map((color, index) => safeCssColor(color, generatedTimelineColor(index)))
    : ["#3f7fc1", "#d65f8f", "#3ba878", "#df8d35", "#7d6bd6", "#2c9fb3", "#d95b6b", "#6676c7"];
  colorMap.set(mainLineName, basePalette[0] || "#3f7fc1");
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
    : ["#3f7fc1", "#d65f8f", "#3ba878", "#df8d35", "#7d6bd6", "#2c9fb3", "#d95b6b", "#6676c7"];
  const branchConfigByLine = new Map(branchConfigs.map((item) => [item.line, item]));
  const nodeConfigByPlot = new Map((timelineConfig.nodes || []).map((item) => [Number(item.plotId), item]));
  let timelineColorMap = new Map();
  const baseLineColor = (line) => palette[Math.max(0, lines.indexOf(line)) % palette.length];
  const lineColor = (line) => safeCssColor(timelineColorMap.get(line) || baseLineColor(line), "#6676c7");
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
  const viewportHeight = Math.max(1, range.bottom - range.top);
  const viewportWidth = Math.max(1, range.right - range.left);
  const verticalBuffer = Math.max(TIMELINE_VIEWPORT_BUFFER_Y, viewportHeight * 1.15);
  const horizontalBuffer = Math.max(TIMELINE_VIEWPORT_BUFFER_X, viewportWidth * 0.42);
  return {
    top: Math.max(0, snapDown(range.top - verticalBuffer)),
    bottom: Math.min(timelineModel.height, snapUp(range.bottom + verticalBuffer)),
    left: Math.max(0, snapDown(range.left - horizontalBuffer)),
    right: Math.min(timelineModel.width, snapUp(range.right + horizontalBuffer)),
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

function connectorBounds(connector) {
  const geometry = connectorGeometry(connector);
  const xValues = [connector.x1, connector.x2, connector.x3 ?? connector.x1];
  const yValues = [
    connector.y1,
    connector.y2,
    geometry.topY,
    geometry.bottomY,
    geometry.topRailY,
    geometry.bottomRailY,
    geometry.branchTopY,
    geometry.branchBottomY,
  ];
  return {
    left: Math.min(...xValues),
    right: Math.max(...xValues),
    top: Math.min(...yValues),
    bottom: Math.max(...yValues),
  };
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

  const connectorLaneSet = new Set(timelineModel.connectors.map((connector) => connector.lane));
  timelineModel.laneLines.filter((line) => (
    (line.lane === timelineModel.mainLineName || !connectorLaneSet.has(line.lane))
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
    const bounds = connectorBounds(connector);
    return (
      bounds.right + 32 >= drawLeft
      && bounds.left - 32 <= drawRight
      && bounds.bottom + 32 >= drawTop
      && bounds.top - 32 <= drawBottom
    );
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
      const bounds = connectorBounds(connector);
      if (overlapsView(bounds.top, bounds.bottom)) visibleLines.add(connector.lane);
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
