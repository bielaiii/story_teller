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

function timelineRangesOverlap(first, second) {
  return first.start < second.end && second.start < first.end;
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

function timelinePlotTitle(plot) {
  return plot.title;
}

function timelinePlotSummary(plot) {
  return plot.summary || plot.text;
}

function timelinePlotChapter(plot) {
  return chapterName(plot.chapter);
}

function timelinePlotPriority(plot) {
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
  const plotLaneNames = (plot) => {
    const configured = Array.isArray(plot.lanes) ? plot.lanes : [plot.lane];
    const normalized = configured.map((lane) => String(lane || "").trim()).filter(Boolean);
    return normalized.length ? normalized : [mainLineName];
  };
  const discoveredLines = [...new Set(plots.flatMap(plotLaneNames))];
  const configuredLineOrder = Array.isArray(timelineConfig.lines) ? timelineConfig.lines : [];
  const lines = [...new Set([
    mainLineName,
    ...configuredLineOrder.filter((line) => discoveredLines.includes(line)),
    ...discoveredLines,
  ])];
  const configuredBranchByLine = new Map((timelineConfig.branches || []).map((item) => [item.line, item]));
  const lastPlotIndex = Math.max(1, plots.length - 1);
  const plotIndexById = new Map(plots.map((plot, index) => [Number(plot.id), index]));
  const branchConfigs = lines.filter((line) => line !== mainLineName).map((line, branchIndex) => {
    const plotIndexes = plots
      .map((plot, index) => (plotLaneNames(plot).includes(line) ? index : -1))
      .filter((index) => index >= 0);
    const firstIndex = Math.min(...plotIndexes);
    const finalIndex = Math.max(...plotIndexes);
    const paddingRatio = plots.length <= 1 ? 0.08 : 0.58 / lastPlotIndex;
    let startPosition = Math.max(0, firstIndex / lastPlotIndex - paddingRatio);
    let endPosition = Math.min(1, finalIndex / lastPlotIndex + paddingRatio);
    if (endPosition - startPosition < 0.1) {
      const center = (startPosition + endPosition) / 2;
      startPosition = Math.max(0, center - 0.05);
      endPosition = Math.min(1, center + 0.05);
    }
    const configured = configuredBranchByLine.get(line) || {};
    if (plotIndexById.has(Number(configured.startPlotId))) {
      startPosition = Math.min(
        startPosition,
        plotIndexById.get(Number(configured.startPlotId)) / lastPlotIndex,
      );
    }
    if (plotIndexById.has(Number(configured.endPlotId))) {
      endPosition = Math.max(
        endPosition,
        plotIndexById.get(Number(configured.endPlotId)) / lastPlotIndex,
      );
    }
    return {
      ...configured,
      line,
      startLine: mainLineName,
      endLine: mainLineName,
      startPosition,
      endPosition,
      nodeCount: plotIndexes.length,
      side: configured.side === "left" || configured.side === "right"
        ? configured.side
        : (branchIndex % 2 === 0 ? "right" : "left"),
    };
  });
  const lineSpacing = Math.max(72, Number(timelineConfig.lineSpacing || 72) || 72);
  const topPadding = timelineConfig.topPadding || 54;
  const sidePadding = timelineConfig.sidePadding || 34;
  const palette = Array.isArray(timelineConfig.palette) && timelineConfig.palette.length
    ? timelineConfig.palette.map((color, index) => safeCssColor(color, generatedTimelineColor(index)))
    : ["#3f7fc1", "#d65f8f", "#3ba878", "#df8d35", "#7d6bd6", "#2c9fb3", "#d95b6b", "#6676c7"];
  const branchConfigByLine = new Map(branchConfigs.map((item) => [item.line, item]));
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
  const nodeGap = Math.max(40, Number(timelineConfig.nodeGap || 56) || 56);
  const branchDisplayLength = (branchConfig) => {
    const automaticLength = Math.max(460, (Number(branchConfig?.nodeCount || 0) + 1) * nodeGap);
    if (branchConfig?.displayLength !== undefined) {
      return Math.max(automaticLength, Number(branchConfig.displayLength) || 420);
    }
    if (branchConfig?.visualLength !== undefined) {
      return Math.max(automaticLength, Number(branchConfig.visualLength) * storyUnitPixels || 420);
    }
    return automaticLength;
  };
  const mainDisplayLength = Math.max(680, ...branchConfigs
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
    const primaryLane = plotLaneNames(plot)[0] || mainLineName;
    const fallbackRatio = plots.length <= 1 ? 0 : index / (plots.length - 1);
    const storyRatio = fallbackRatio;
    if (primaryLane === mainLineName) {
      return {
        x: lineX(mainLineName),
        y: plotY(index),
        lane: primaryLane,
        storyRatio,
      };
    }
    const connector = connectorLines.find((item) => item.lane === primaryLane);
    if (!connector) return { x: lineX(primaryLane), y: plotY(index), lane: primaryLane, storyRatio };
    const geometry = connectorGeometry(connector);
    return {
      x: connector.x2,
      y: Math.max(geometry.branchTopY, Math.min(geometry.branchBottomY, plotY(index))),
      lane: primaryLane,
      storyRatio,
    };
  };

  const positionedPlots = plots.map((plot, index) => {
    const position = timelineNodePosition(plot, index);
    const nodeColor = lineColor(position.lane);
    const laneSide = position.lane === mainLineName
      ? (index % 2 === 0 ? "left" : "right")
      : (branchConfigByLine.get(position.lane)?.side === "left" ? "left" : "right");
    return {
      plot,
      index,
      position,
      nodeColor,
      side: laneSide,
      priority: timelinePlotPriority(plot),
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
  const positionLabel = `${position.lane} · 第 ${plotSequence(plot)} 章`;
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
      <span>${escapeHtml(timelinePlotChapter(plot))} · 第 ${escapeHtml(plotSequence(plot))} 章</span>
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
  document.querySelectorAll(".timeline-jump").forEach((item) => {
    item.addEventListener("click", (event) => {
      event.stopPropagation();
      openPlotDetail(Number(item.dataset.plotId));
    });
  });
  document.querySelectorAll(".timeline-node-focus").forEach((item) => {
    item.addEventListener("click", (event) => {
      event.stopPropagation();
      showTimelineFloat(item);
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
  float.setAttribute("role", "dialog");
  float.setAttribute("aria-label", "剧情节点预览");
  float.innerHTML = `
    <button class="timeline-float-close" id="timelineFloatClose" type="button" aria-label="关闭剧情预览">×</button>
    <span id="timelineFloatLane"></span>
    <strong id="timelineFloatTitle"></strong>
    <p id="timelineFloatText"></p>
    <button class="timeline-float-open icon-action is-hidden" id="timelineFloatOpen" type="button" aria-label="打开完整文章" title="打开完整文章">${uiIcon("convert")}</button>
  `;
  document.querySelector(".timeline-board")?.append(float);
  float.querySelector("#timelineFloatClose")?.addEventListener("click", hideTimelineFloat);
  return float;
}

function showTimelineFloat(target) {
  const float = ensureTimelineFloat();
  if (!float) return;
  const plot = plots.find((item) => item.id === Number(target.dataset.plotId));
  const lane = target.dataset.lane || "剧情线";
  const activeLane = lane.split(" / ").map((item) => item.trim()).filter(Boolean)[0] || lane;
  const openButton = float.querySelector("#timelineFloatOpen");
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
  document.querySelector("#timelineFloatText").textContent = plot
    ? markdownExcerpt(timelinePlotSummary(plot), 150)
    : "这条剧情线连接了相关事件，点击节点可查看剧情预览。";
  openButton?.classList.toggle("is-hidden", !plot);
  if (openButton && plot) {
    openButton.onclick = () => openPlotDetail(Number(plot.id));
  }
  if (plot && target instanceof Element) {
    const board = document.querySelector(".timeline-board");
    const boardRect = board?.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    if (boardRect) {
      const cardWidth = 286;
      const preferredLeft = targetRect.right - boardRect.left + 14;
      const left = Math.max(18, Math.min(preferredLeft, boardRect.width - cardWidth - 18));
      const top = Math.max(24, Math.min(
        targetRect.top - boardRect.top + targetRect.height / 2,
        boardRect.height - 90,
      ));
      float.style.left = `${left}px`;
      float.style.right = "auto";
      float.style.top = `${top}px`;
    }
  } else {
    float.style.removeProperty("left");
    float.style.right = "20px";
    float.style.top = "50%";
  }
}

function hideTimelineFloat() {
  document.querySelector("#timelineFloat")?.remove();
  if (timelineModel) timelineModel.focusLane = "";
  scheduleTimelineViewportRender(true);
  document.querySelectorAll(".timeline-summary-card.is-hidden-by-focus").forEach((item) => item.classList.remove("is-hidden-by-focus"));
  document.querySelectorAll(".timeline-node.is-muted-by-focus").forEach((item) => item.classList.remove("is-muted-by-focus"));
}

let timelineEditorDraft = null;
let timelineEditorSelectedPlotId = null;
let timelineEditorSelectedLine = "";
let timelineEditorDraggedPlotId = null;
let timelineEditorUnassignedOnly = false;
let timelineEditorEditingLine = "";

function timelineEditorColor(index) {
  const colors = ["#d65f8f", "#d8b64a", "#3f7fc1", "#d99a2e", "#2aa79b", "#7d6bd6", "#d95b6b", "#6676c7"];
  return colors[index % colors.length];
}

function setTimelineEditorStatus(message = "", type = "") {
  if (!timelineEditorStatus) return;
  timelineEditorStatus.textContent = message;
  timelineEditorStatus.className = type ? `is-${type}` : "";
}

function timelineEditorAssignment(plotId) {
  if (!timelineEditorDraft) return [];
  return timelineEditorDraft.assignments[String(plotId)] || [];
}

function buildTimelineEditorDraft() {
  const normalized = normalizeTimelineConfig(timelineConfig);
  const lines = normalized.lineConfigs.map((line, index) => ({
    name: line.name,
    color: /^#[0-9a-f]{6}$/i.test(String(line.color || "")) ? line.color : timelineEditorColor(index),
    side: line.name === normalized.mainLine ? "center" : (line.side === "left" ? "left" : "right"),
    startPlotId: line.startPlotId || "",
    endPlotId: line.endPlotId || "",
  }));
  const knownLines = new Set(lines.map((line) => line.name));
  const assignments = {};
  plots.forEach((plot) => {
    assignments[String(plot.id)] = (plot.lanes || [])
      .map((lane) => String(lane || "").trim())
      .filter((lane, index, values) => knownLines.has(lane) && values.indexOf(lane) === index);
  });
  return {
    mainLine: normalized.mainLine,
    lineSpacing: Number(normalized.lineSpacing || 72),
    topPadding: Number(normalized.topPadding || 64),
    sidePadding: Number(normalized.sidePadding || 36),
    pixelsPerStoryUnit: Number(normalized.pixelsPerStoryUnit || 760),
    lines,
    assignments,
  };
}

function timelineEditorPlotOptions(selectedId = "") {
  return plots.map((plot) => `
    <option value="${escapeHtml(plot.id)}" ${String(plot.id) === String(selectedId) ? "selected" : ""}>
      第 ${escapeHtml(plotSequence(plot))} 章 · ${escapeHtml(plot.title)}
    </option>
  `).join("");
}

function renderTimelineEditorLines() {
  if (!timelineEditorDraft || !timelineEditorLineList) return;
  timelineEditorLineCount.textContent = `${timelineEditorDraft.lines.length} 条`;
  timelineEditorLineList.innerHTML = timelineEditorDraft.lines.map((line) => {
    const count = Object.values(timelineEditorDraft.assignments).filter((lanes) => lanes.includes(line.name)).length;
    return `
      <div class="timeline-editor-line-entry">
        <button
          class="timeline-editor-line-row ${timelineEditorSelectedLine === line.name ? "is-active" : ""}"
          data-line="${escapeHtml(line.name)}"
          type="button"
          style="--accent:${escapeHtml(line.color)}"
        >
          <i aria-hidden="true"></i>
          <span><strong>${escapeHtml(line.name)}</strong><small>${line.name === timelineEditorDraft.mainLine ? "主线" : (line.side === "left" ? "左侧分支" : "右侧分支")}</small></span>
          <b>${count}</b>
        </button>
        <button class="timeline-editor-line-settings-trigger icon-action ${timelineEditorEditingLine === line.name ? "is-active" : ""}" data-line="${escapeHtml(line.name)}" type="button" aria-label="设置${escapeHtml(line.name)}" title="设置剧情线">${uiIcon("layout")}</button>
      </div>
    `;
  }).join("");
  timelineEditorLineList.querySelectorAll(".timeline-editor-line-row").forEach((button) => {
    button.addEventListener("click", () => {
      timelineEditorSelectedLine = button.dataset.line;
      timelineEditorSelectedPlotId = null;
      timelineEditorUnassignedOnly = false;
      timelineEditorEditingLine = "";
      renderTimelineEditor();
    });
    button.addEventListener("dragover", (event) => {
      event.preventDefault();
      button.classList.add("is-drop-target");
    });
    button.addEventListener("dragleave", () => button.classList.remove("is-drop-target"));
    button.addEventListener("drop", (event) => {
      event.preventDefault();
      button.classList.remove("is-drop-target");
      const plotId = timelineEditorDraggedPlotId || Number(event.dataTransfer?.getData("text/plain"));
      assignTimelineEditorPlot(plotId, button.dataset.line);
    });
  });
  timelineEditorLineList.querySelectorAll(".timeline-editor-line-settings-trigger").forEach((button) => {
    button.addEventListener("click", () => {
      timelineEditorSelectedLine = button.dataset.line;
      timelineEditorSelectedPlotId = null;
      timelineEditorUnassignedOnly = false;
      timelineEditorEditingLine = button.dataset.line;
      renderTimelineEditor();
    });
  });
  const unassigned = Object.values(timelineEditorDraft.assignments).filter((lanes) => !lanes.length).length;
  timelineEditorUnassignedCount.textContent = String(unassigned);
  timelineEditorUnassigned.classList.toggle("is-active", timelineEditorUnassignedOnly);
}

function renderTimelineEditorEvents() {
  if (!timelineEditorDraft || !timelineEditorEventList) return;
  const keyword = String(timelineEditorSearch?.value || "").trim().toLowerCase();
  const selectedLine = timelineEditorSelectedLine;
  const visiblePlots = plots.filter((plot) => (
    (!timelineEditorUnassignedOnly || !timelineEditorAssignment(plot.id).length)
    && (!selectedLine || timelineEditorAssignment(plot.id).includes(selectedLine))
    && (!keyword || `${plot.title} ${plot.summary || ""} ${plotSequence(plot)}`.toLowerCase().includes(keyword))
  ));
  const eventsHead = timelineEditorEventList.previousElementSibling;
  const eventsTitle = eventsHead?.querySelector("strong");
  const eventsHint = eventsHead?.querySelector("span");
  if (eventsTitle) eventsTitle.textContent = selectedLine ? `${selectedLine} · 文章节点` : (timelineEditorUnassignedOnly ? "未编排剧情" : "文章节点");
  if (eventsHint) eventsHint.textContent = selectedLine
    ? `只显示属于“${selectedLine}”的文章，纵向顺序仍跟随文章`
    : "纵向顺序固定跟随文章；拖到左侧可切换剧情线";
  timelineEditorEventList.innerHTML = visiblePlots.length ? visiblePlots.map((plot) => {
    const lanes = timelineEditorAssignment(plot.id);
    const primaryLine = timelineEditorDraft.lines.find((line) => line.name === lanes[0]);
    return `
      <button
        class="timeline-editor-event-row ${Number(timelineEditorSelectedPlotId) === Number(plot.id) ? "is-active" : ""} ${!lanes.length ? "is-unassigned" : ""}"
        data-plot-id="${escapeHtml(plot.id)}"
        draggable="true"
        type="button"
        style="--accent:${escapeHtml(primaryLine?.color || "#9aa7b2")}"
      >
        <span class="timeline-editor-event-sequence">${escapeHtml(plotSequence(plot))}</span>
        <span class="timeline-editor-event-copy">
          <strong>${escapeHtml(plot.title)}</strong>
          <small>${lanes.length ? escapeHtml(lanes.join(" / ")) : "未编排剧情"}</small>
        </span>
        <span aria-hidden="true">↔</span>
      </button>
    `;
  }).join("") : '<div class="timeline-editor-empty">没有匹配的文章。</div>';
  timelineEditorEventList.querySelectorAll(".timeline-editor-event-row").forEach((button) => {
    button.addEventListener("click", () => {
      timelineEditorSelectedPlotId = Number(button.dataset.plotId);
      timelineEditorEditingLine = "";
      renderTimelineEditor();
    });
    button.addEventListener("dragstart", (event) => {
      timelineEditorDraggedPlotId = Number(button.dataset.plotId);
      event.dataTransfer?.setData("text/plain", button.dataset.plotId);
      event.dataTransfer.effectAllowed = "move";
      button.classList.add("is-dragging");
    });
    button.addEventListener("dragend", () => {
      timelineEditorDraggedPlotId = null;
      button.classList.remove("is-dragging");
    });
  });
}

function assignTimelineEditorPlot(plotId, lineName = "") {
  if (!timelineEditorDraft || !plots.some((plot) => Number(plot.id) === Number(plotId))) return;
  const current = timelineEditorAssignment(plotId);
  timelineEditorDraft.assignments[String(plotId)] = lineName
    ? [lineName, ...current.filter((lane) => lane !== lineName)]
    : [];
  timelineEditorSelectedPlotId = Number(plotId);
  timelineEditorEditingLine = "";
  setTimelineEditorStatus("时间线有未保存的修改。", "dirty");
  renderTimelineEditor();
}

function renderTimelineEditorPlotInspector(plot) {
  const lanes = timelineEditorAssignment(plot.id);
  timelineEditorInspector.innerHTML = `
    <div class="timeline-editor-inspector-head">
      <span>文章节点</span>
      <h4>${escapeHtml(plot.title)}</h4>
      <p>第 ${escapeHtml(plotSequence(plot))} 章 · 节点位置由文章顺序决定</p>
    </div>
    <label class="timeline-editor-field">
      <span>主要剧情线</span>
      <select id="timelineEditorPrimaryLine">
        <option value="">未编排</option>
        ${timelineEditorDraft.lines.map((line) => `<option value="${escapeHtml(line.name)}" ${lanes[0] === line.name ? "selected" : ""}>${escapeHtml(line.name)}</option>`).join("")}
      </select>
    </label>
    <fieldset class="timeline-editor-lane-checks">
      <legend>同时关联的剧情线</legend>
      ${timelineEditorDraft.lines.map((line) => `
        <label><input type="checkbox" value="${escapeHtml(line.name)}" ${lanes.includes(line.name) ? "checked" : ""} /><span>${escapeHtml(line.name)}</span></label>
      `).join("")}
    </fieldset>
    <div class="timeline-editor-note">标题、摘要和正文由文章负责，时间线不会保存第二份副本。</div>
    <button class="timeline-editor-open-plot icon-action" id="timelineEditorOpenPlot" type="button" aria-label="打开这篇文章" title="打开这篇文章">${uiIcon("convert")}</button>
  `;
  document.querySelector("#timelineEditorPrimaryLine")?.addEventListener("change", (event) => {
    assignTimelineEditorPlot(plot.id, event.target.value);
  });
  timelineEditorInspector.querySelectorAll(".timeline-editor-lane-checks input").forEach((input) => {
    input.addEventListener("change", () => {
      const selected = [...timelineEditorInspector.querySelectorAll(".timeline-editor-lane-checks input:checked")]
        .map((item) => item.value);
      const primary = document.querySelector("#timelineEditorPrimaryLine")?.value || "";
      timelineEditorDraft.assignments[String(plot.id)] = primary
        ? [primary, ...selected.filter((lane) => lane !== primary)]
        : selected;
      setTimelineEditorStatus("时间线有未保存的修改。", "dirty");
      renderTimelineEditor();
    });
  });
  document.querySelector("#timelineEditorOpenPlot")?.addEventListener("click", () => {
    closeTimelineEditor();
    openPlotDetail(Number(plot.id));
  });
}

function renameTimelineEditorLine(previousName, nextName) {
  const name = String(nextName || "").trim();
  if (!name || name.length > 60) {
    setTimelineEditorStatus("剧情线名称长度需要在 1 到 60 个字符之间。", "error");
    return false;
  }
  if (timelineEditorDraft.lines.some((line) => line.name === name && line.name !== previousName)) {
    setTimelineEditorStatus("已经存在同名剧情线。", "error");
    return false;
  }
  const line = timelineEditorDraft.lines.find((item) => item.name === previousName);
  if (!line || name === previousName) return true;
  line.name = name;
  if (timelineEditorDraft.mainLine === previousName) timelineEditorDraft.mainLine = name;
  Object.keys(timelineEditorDraft.assignments).forEach((plotId) => {
    timelineEditorDraft.assignments[plotId] = timelineEditorDraft.assignments[plotId]
      .map((lane) => lane === previousName ? name : lane);
  });
  timelineEditorSelectedLine = name;
  if (timelineEditorEditingLine === previousName) timelineEditorEditingLine = name;
  setTimelineEditorStatus("剧情线名称及文章归属已同步修改，尚未保存。", "dirty");
  return true;
}

function moveTimelineEditorLine(lineName, direction) {
  if (lineName === timelineEditorDraft.mainLine) return;
  const index = timelineEditorDraft.lines.findIndex((line) => line.name === lineName);
  const target = index + direction;
  if (index < 0 || target < 1 || target >= timelineEditorDraft.lines.length) return;
  const [line] = timelineEditorDraft.lines.splice(index, 1);
  timelineEditorDraft.lines.splice(target, 0, line);
  setTimelineEditorStatus("剧情线显示顺序已调整，尚未保存。", "dirty");
  renderTimelineEditor();
}

function deleteTimelineEditorLine(lineName) {
  if (lineName === timelineEditorDraft.mainLine) return;
  const assignedCount = Object.values(timelineEditorDraft.assignments).filter((lanes) => lanes.includes(lineName)).length;
  const transfer = document.querySelector("#timelineEditorTransferLine")?.value || "";
  if (assignedCount && !transfer) {
    setTimelineEditorStatus("请先选择接收这些剧情的目标线。", "error");
    return;
  }
  Object.keys(timelineEditorDraft.assignments).forEach((plotId) => {
    const lanes = timelineEditorDraft.assignments[plotId];
    if (!lanes.includes(lineName)) return;
    timelineEditorDraft.assignments[plotId] = [
      ...(transfer ? [transfer] : []),
      ...lanes.filter((lane) => lane !== lineName && lane !== transfer),
    ];
  });
  timelineEditorDraft.lines = timelineEditorDraft.lines.filter((line) => line.name !== lineName);
  timelineEditorSelectedLine = timelineEditorDraft.mainLine;
  timelineEditorEditingLine = "";
  setTimelineEditorStatus(`“${lineName}”已从草稿删除，保存后生效。`, "dirty");
  renderTimelineEditor();
}

function renderTimelineEditorLineNodes(line) {
  const linePlots = plots.filter((plot) => timelineEditorAssignment(plot.id).includes(line.name));
  timelineEditorInspector.innerHTML = `
    <div class="timeline-editor-inspector-head">
      <span>当前剧情线</span>
      <h4>文章节点</h4>
      <p>${escapeHtml(line.name)} · ${linePlots.length} 篇</p>
    </div>
    <div class="timeline-editor-line-nodes">
      ${linePlots.length ? linePlots.map((plot) => `
        <button class="timeline-editor-line-node" data-plot-id="${escapeHtml(plot.id)}" type="button">
          <span>${escapeHtml(plotSequence(plot))}</span>
          <strong>${escapeHtml(plot.title)}</strong>
        </button>
      `).join("") : '<div class="timeline-editor-empty">这条剧情线还没有文章节点。</div>'}
    </div>
  `;
  timelineEditorInspector.querySelectorAll(".timeline-editor-line-node").forEach((button) => {
    button.addEventListener("click", () => {
      timelineEditorSelectedPlotId = Number(button.dataset.plotId);
      renderTimelineEditor();
    });
  });
}

function renderTimelineEditorLineSettings(line) {
  const isMain = line.name === timelineEditorDraft.mainLine;
  const assignedCount = plots.filter((plot) => timelineEditorAssignment(plot.id).includes(line.name)).length;
  const transferOptions = timelineEditorDraft.lines
    .filter((item) => item.name !== line.name)
    .map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}</option>`)
    .join("");
  timelineEditorInspector.innerHTML = `
    <div class="timeline-editor-inspector-head">
      <span>剧情线设置</span>
      <h4>编辑“${escapeHtml(line.name)}”</h4>
      <p>修改结构后需要保存时间线</p>
    </div>
    <label class="timeline-editor-field"><span>剧情线名称</span><input id="timelineEditorLineName" maxlength="60" value="${escapeHtml(line.name)}" /></label>
    <label class="timeline-editor-field timeline-editor-color-field"><span>剧情线颜色</span><input id="timelineEditorLineColor" type="color" value="${escapeHtml(line.color)}" /></label>
    <label class="timeline-editor-field"><span>显示方向</span><select id="timelineEditorLineSide" ${isMain ? "disabled" : ""}><option value="left" ${line.side === "left" ? "selected" : ""}>主线左侧</option><option value="right" ${line.side !== "left" ? "selected" : ""}>主线右侧</option></select></label>
    ${isMain ? '<div class="timeline-editor-note">主线始终贯穿全部阅读顺序，不设置分支和汇合点。</div>' : `
      <label class="timeline-editor-field"><span>从这篇文章后分出</span><select id="timelineEditorStartPlot"><option value="">自动按首个节点</option>${timelineEditorPlotOptions(line.startPlotId)}</select></label>
      <label class="timeline-editor-field"><span>在这篇文章前汇合</span><select id="timelineEditorEndPlot"><option value="">自动按最后节点</option>${timelineEditorPlotOptions(line.endPlotId)}</select></label>
    `}
    <div class="timeline-editor-order-actions"><button class="icon-action" id="timelineEditorMoveLineUp" type="button" aria-label="向前显示" title="向前显示" ${isMain ? "disabled" : ""}>${uiIcon("up")}</button><button class="icon-action" id="timelineEditorMoveLineDown" type="button" aria-label="向后显示" title="向后显示" ${isMain ? "disabled" : ""}>${uiIcon("down")}</button></div>
    ${isMain ? "" : `
      <div class="timeline-editor-delete-line">
        <strong>删除剧情线</strong>
        <p>${assignedCount ? `需要先转移 ${assignedCount} 篇文章。` : "这条线没有文章，可以直接删除。"}</p>
        ${assignedCount ? `<select id="timelineEditorTransferLine"><option value="">选择接收剧情线</option>${transferOptions}</select>` : ""}
        <button class="icon-action is-danger" id="timelineEditorDeleteLine" type="button" aria-label="删除这条剧情线" title="删除剧情线">${uiIcon("trash")}</button>
      </div>
    `}
  `;
  document.querySelector("#timelineEditorLineName")?.addEventListener("change", (event) => {
    if (renameTimelineEditorLine(line.name, event.target.value)) renderTimelineEditor();
  });
  document.querySelector("#timelineEditorLineColor")?.addEventListener("input", (event) => {
    line.color = event.target.value;
    setTimelineEditorStatus("剧情线颜色已修改，尚未保存。", "dirty");
    renderTimelineEditorLines();
    renderTimelineEditorEvents();
  });
  document.querySelector("#timelineEditorLineSide")?.addEventListener("change", (event) => {
    line.side = event.target.value;
    setTimelineEditorStatus("剧情线方向已修改，尚未保存。", "dirty");
    renderTimelineEditorLines();
  });
  document.querySelector("#timelineEditorStartPlot")?.addEventListener("change", (event) => {
    line.startPlotId = event.target.value ? Number(event.target.value) : "";
    setTimelineEditorStatus("分支锚点已修改，尚未保存。", "dirty");
  });
  document.querySelector("#timelineEditorEndPlot")?.addEventListener("change", (event) => {
    line.endPlotId = event.target.value ? Number(event.target.value) : "";
    setTimelineEditorStatus("汇合锚点已修改，尚未保存。", "dirty");
  });
  document.querySelector("#timelineEditorMoveLineUp")?.addEventListener("click", () => moveTimelineEditorLine(line.name, -1));
  document.querySelector("#timelineEditorMoveLineDown")?.addEventListener("click", () => moveTimelineEditorLine(line.name, 1));
  document.querySelector("#timelineEditorDeleteLine")?.addEventListener("click", () => deleteTimelineEditorLine(line.name));
}

function renderTimelineEditorUnassignedInspector() {
  const unassignedPlots = plots.filter((plot) => !timelineEditorAssignment(plot.id).length);
  timelineEditorInspector.innerHTML = `
    <div class="timeline-editor-inspector-head">
      <span>待处理</span>
      <h4>未编排剧情</h4>
      <p>${unassignedPlots.length} 篇文章尚未进入剧情线</p>
    </div>
    <div class="timeline-editor-line-nodes">
      ${unassignedPlots.length ? unassignedPlots.map((plot) => `
        <button class="timeline-editor-line-node" data-plot-id="${escapeHtml(plot.id)}" type="button">
          <span>${escapeHtml(plotSequence(plot))}</span>
          <strong>${escapeHtml(plot.title)}</strong>
        </button>
      `).join("") : '<div class="timeline-editor-empty">所有文章都已经完成编排。</div>'}
    </div>
  `;
  timelineEditorInspector.querySelectorAll(".timeline-editor-line-node").forEach((button) => {
    button.addEventListener("click", () => {
      timelineEditorSelectedPlotId = Number(button.dataset.plotId);
      renderTimelineEditor();
    });
  });
}

function renderTimelineEditorInspector() {
  if (!timelineEditorDraft || !timelineEditorInspector) return;
  const plot = plots.find((item) => Number(item.id) === Number(timelineEditorSelectedPlotId));
  if (plot) {
    renderTimelineEditorPlotInspector(plot);
    return;
  }
  if (timelineEditorUnassignedOnly) {
    renderTimelineEditorUnassignedInspector();
    return;
  }
  const editingLine = timelineEditorDraft.lines.find((item) => item.name === timelineEditorEditingLine);
  if (editingLine) {
    renderTimelineEditorLineSettings(editingLine);
    return;
  }
  const line = timelineEditorDraft.lines.find((item) => item.name === timelineEditorSelectedLine);
  if (line) renderTimelineEditorLineNodes(line);
}

function renderTimelineEditor() {
  renderTimelineEditorLines();
  renderTimelineEditorEvents();
  renderTimelineEditorInspector();
}

async function refreshTimelineEditorAccess() {
  if (!timelineEditTrigger) return;
  try {
    await initializeRefactorWorkspace();
    timelineEditTrigger.classList.toggle("is-hidden", !refactorCapability?.writable);
  } catch {
    timelineEditTrigger.classList.add("is-hidden");
  }
}

async function openTimelineEditor() {
  if (!timelineEditorDialog || timelineEditorDialog.open) return;
  if (timelineEditorDialog.parentElement !== document.body) document.body.append(timelineEditorDialog);
  setTimelineEditorStatus("正在读取时间线结构…");
  try {
    await Promise.all([ensureTimelineConfig(), initializeRefactorWorkspace()]);
    if (!refactorCapability?.writable) throw new Error("当前页面是只读模式，请用 run.sh 启动本地服务");
    timelineEditorDraft = buildTimelineEditorDraft();
    timelineEditorSelectedPlotId = plots[0]?.id || null;
    timelineEditorSelectedLine = "";
    timelineEditorUnassignedOnly = false;
    timelineEditorEditingLine = "";
    if (timelineEditorSearch) timelineEditorSearch.value = "";
    renderTimelineEditor();
    setTimelineEditorStatus("拖动文章可以切换主要剧情线；所有修改会在保存时一次写入。", "ready");
    timelineEditorDialog.showModal();
  } catch (error) {
    setTimelineEditorStatus(error.message, "error");
  }
}

function closeTimelineEditor() {
  if (timelineEditorDialog?.open) timelineEditorDialog.close();
  timelineEditorDraft = null;
  timelineEditorDraggedPlotId = null;
}

function addTimelineEditorLine() {
  if (!timelineEditorDraft) return;
  let number = timelineEditorDraft.lines.length + 1;
  let name = `新剧情线 ${number}`;
  while (timelineEditorDraft.lines.some((line) => line.name === name)) {
    number += 1;
    name = `新剧情线 ${number}`;
  }
  timelineEditorDraft.lines.push({
    name,
    color: timelineEditorColor(timelineEditorDraft.lines.length),
    side: timelineEditorDraft.lines.length % 2 ? "right" : "left",
    startPlotId: "",
    endPlotId: "",
  });
  timelineEditorSelectedLine = name;
  timelineEditorSelectedPlotId = null;
  timelineEditorEditingLine = name;
  setTimelineEditorStatus("新剧情线已加入草稿，请设置名称和分支锚点。", "dirty");
  renderTimelineEditor();
}

async function saveTimelineEditor() {
  if (!timelineEditorDraft || !timelineEditorSave) return;
  timelineEditorSave.disabled = true;
  timelineEditorCancel.disabled = true;
  setTimelineEditorStatus("正在保存剧情线结构和文章归属…");
  try {
    const result = await refactorApi("/api/timeline/update", {
      project: currentProjectId(),
      config: {
        mainLine: timelineEditorDraft.mainLine,
        lineSpacing: timelineEditorDraft.lineSpacing,
        topPadding: timelineEditorDraft.topPadding,
        sidePadding: timelineEditorDraft.sidePadding,
        pixelsPerStoryUnit: timelineEditorDraft.pixelsPerStoryUnit,
        lines: timelineEditorDraft.lines,
      },
      assignments: plots.map((plot) => ({
        plotId: Number(plot.id),
        lanes: timelineEditorAssignment(plot.id),
      })),
    });
    setTimelineEditorStatus(`已保存 ${result.lineCount} 条剧情线和 ${result.plotCount} 个文章节点，正在刷新…`, "success");
    window.sessionStorage?.setItem("story-teller-open-view", "timeline");
    window.setTimeout(() => window.location.reload(), 420);
  } catch (error) {
    setTimelineEditorStatus(error.message, "error");
    timelineEditorSave.disabled = false;
    timelineEditorCancel.disabled = false;
  }
}
