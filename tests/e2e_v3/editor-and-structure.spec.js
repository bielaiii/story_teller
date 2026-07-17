const { test, expect } = require("@playwright/test");
const primaryKey = process.platform === "darwin" ? "Meta" : "Control";

function colorSpread(value) {
  const spreads = [];
  for (const match of value.matchAll(/rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/gi)) {
    const channels = match.slice(1, 4).map(Number);
    spreads.push(Math.max(...channels) - Math.min(...channels));
  }
  for (const match of value.matchAll(/color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)/gi)) {
    const channels = match.slice(1, 4).map((channel) => Number(channel) * 255);
    spreads.push(Math.max(...channels) - Math.min(...channels));
  }
  for (const match of value.matchAll(/#([\da-f]{6})/gi)) {
    const channels = [0, 2, 4].map((index) => Number.parseInt(match[1].slice(index, index + 2), 16));
    spreads.push(Math.max(...channels) - Math.min(...channels));
  }
  return Math.max(0, ...spreads);
}

function colorChannels(value) {
  const rgb = value.match(/rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i);
  if (rgb) return rgb.slice(1, 4).map(Number);
  const srgb = value.match(/color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)/i);
  if (srgb) return srgb.slice(1, 4).map((channel) => Number(channel) * 255);
  const hex = value.match(/#([\da-f]{6})/i);
  return hex ? [0, 2, 4].map((index) => Number.parseInt(hex[1].slice(index, index + 2), 16)) : [];
}

test("根地址采用本地服务配置的默认项目", async ({ page }) => {
  await page.goto("/#/story");
  await expect(page.getByRole("heading", { name: "雾港纪事", exact: true })).toBeVisible();
  await expect(page.locator(".brand")).toBeHidden();
  const response = await page.request.get("/api/v1/meta");
  expect((await response.json()).project).toBe("novel");
});

test("内容承载面保持白底且状态和强调保留主题色", async ({ page }) => {
  await page.goto("/?project=novel#/story");
  const themeColors = Object.fromEntries(await page.locator(":root").evaluate((root) => {
    const style = getComputedStyle(root);
    return ["--paper", "--surface", "--surface-solid", "--surface-soft", "--surface-blue", "--surface-rose", "--surface-gold", "--field", "--line"]
      .map((name) => [name, style.getPropertyValue(name).trim()]);
  }));
  for (const name of ["--paper", "--surface", "--surface-solid", "--field"]) {
    const channels = colorChannels(themeColors[name]);
    expect(Math.min(...channels), `${name} 应是明亮的白色承载面`).toBeGreaterThanOrEqual(250);
    expect(colorSpread(themeColors[name]), `${name} 不应让页面产生整体偏色`).toBeLessThanOrEqual(2);
  }
  for (const name of ["--surface-soft", "--surface-blue", "--surface-rose", "--surface-gold", "--line"]) {
    const value = themeColors[name];
    expect(colorSpread(value), `${name} 不应是黑白灰中性色`).toBeGreaterThanOrEqual(8);
  }

  const whiteSurfaces = [
    ["/?project=novel#/story", ".plot-card"],
    ["/?project=novel#/characters", ".profile-kv-grid > div"],
    ["/?project=novel#/entries", ".sticky-detail"],
    ["/?project=novel#/fragments", ".fragment-card-new"],
    ["/?project=novel#/checks", ".check-panel"],
    ["/?project=novel#/graph", ".graph-canvas"],
    ["/?project=novel#/timeline", ".timeline-canvas-new"],
  ];
  for (const [url, selector] of whiteSurfaces) {
    await page.goto(url);
    const surface = page.locator(selector).first();
    await expect(surface).toBeVisible();
    const background = await surface.evaluate((element) => getComputedStyle(element).backgroundColor);
    const channels = colorChannels(background);
    expect(Math.min(...channels), `${selector} 应恢复为明亮白底`).toBeGreaterThanOrEqual(250);
    expect(colorSpread(background), `${selector} 不应被统一染色`).toBeLessThanOrEqual(2);
  }

  await page.goto("/?project=novel#/story");
  const activeFilter = page.locator(".filter-chips button.is-active").first();
  await expect(activeFilter).toBeVisible();
  const activeFilterBackground = await activeFilter.evaluate((element) => `${getComputedStyle(element).backgroundColor} ${getComputedStyle(element).backgroundImage}`);
  expect(colorSpread(activeFilterBackground), "状态和选中态仍应保留主题色").toBeGreaterThanOrEqual(8);
});

test("时间线、图谱和剧情筛选保持可见且一致的交互表现", async ({ page }) => {
  await page.goto("/?project=novel#/story");
  const statusChips = page.locator(".filter-panel > .filter-group .filter-chips");
  const tagChips = page.locator(".filter-panel > .filter-details .filter-chips");
  await expect(statusChips).toBeVisible();
  await expect(tagChips).toBeVisible();
  const statusBox = await statusChips.boundingBox();
  const tagBox = await tagChips.boundingBox();
  expect(Math.abs(statusBox.x - tagBox.x)).toBeLessThan(1);
  await expect(page.locator(".filter-details summary small")).toHaveCount(0);
  await expect(page.locator(".filter-details summary")).toHaveText("标签");

  await page.goto("/?project=novel#/timeline");
  await expect(page.locator(".timeline-track-canvas")).toBeVisible();
  const timelineLegend = page.getByRole("complementary", { name: "时间线图示" });
  const legendBox = await timelineLegend.boundingBox();
  const timelineEdit = page.getByRole("button", { name: "编辑时间线" });
  const editBox = await timelineEdit.boundingBox();
  expect(legendBox.width).toBeLessThanOrEqual(120);
  expect(legendBox.x + legendBox.width).toBeGreaterThan(1100);
  expect(Math.abs(editBox.x + editBox.width / 2 - (legendBox.x + legendBox.width / 2))).toBeLessThan(1);
  expect(legendBox.y).toBeGreaterThanOrEqual(editBox.y + editBox.height + 6);
  expect(await timelineEdit.evaluate((element) => getComputedStyle(element).borderRadius)).toBe("50%");
  const lineOptions = timelineLegend.locator(".timeline-line-options");
  await expect(lineOptions).toBeVisible();
  await expect(timelineLegend.getByRole("button", { name: /展开时间线图示|收起时间线图示/ })).toHaveCount(0);
  const optionsBox = await lineOptions.boundingBox();
  expect(optionsBox.width).toBeLessThanOrEqual(120);
  expect(await lineOptions.locator("strong").first().evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBeLessThanOrEqual(10);
  await expect(timelineLegend.getByText("全部剧情线", { exact: true })).toHaveCount(0);
  const origin = page.locator(".timeline-origin").first();
  await expect(origin).toBeVisible();
  const originBox = await origin.boundingBox();
  const timelineBox = await page.locator(".timeline-canvas-new").boundingBox();
  const firstNodeBox = await page.locator(".timeline-node-new > span").first().boundingBox();
  expect(originBox.y).toBeGreaterThanOrEqual(70);
  expect(Math.abs(originBox.x + originBox.width / 2 - (timelineBox.x + timelineBox.width / 2))).toBeLessThan(1);
  expect(Math.abs(firstNodeBox.x + firstNodeBox.width / 2 - (timelineBox.x + timelineBox.width / 2))).toBeLessThan(1);
  await expect(page.locator(".timeline-node-new strong, .timeline-node-new small")).toHaveCount(0);
  await expect(page.locator(".timeline-endpoint")).toHaveCount(0);
  await page.locator(".timeline-node-new").first().click();
  await expect(page.locator(".timeline-plot-preview > *").first()).toBeVisible();
  await expect(page.getByText("正在打开页面…")).toHaveCount(0);
  await expect(lineOptions.locator("button")).not.toHaveCount(0);

  await page.goto("/?project=novel#/graph");
  await expect(page.locator(".graph-page-header .rail-search")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "重置图谱视角" })).toHaveCount(0);
  const node = page.locator(".graph-node").first();
  await expect(node).toBeVisible();
  const restingNodeShape = await node.evaluate((element) => {
    const nodeStyle = getComputedStyle(element);
    const avatarStyle = getComputedStyle(element.querySelector(":scope > span"));
    const labelStyle = getComputedStyle(element.querySelector(":scope > strong"));
    return {
      nodeRadius: nodeStyle.borderRadius,
      nodeWidth: nodeStyle.width,
      nodeHeight: nodeStyle.height,
      nodeBackground: nodeStyle.backgroundColor,
      nodeBorderWidth: nodeStyle.borderTopWidth,
      avatarRadius: avatarStyle.borderRadius,
      avatarWidth: avatarStyle.width,
      avatarHeight: avatarStyle.height,
      avatarBorderWidth: avatarStyle.borderTopWidth,
      avatarOverflow: avatarStyle.overflow,
      labelBackground: labelStyle.backgroundColor,
      labelShadow: labelStyle.boxShadow,
    };
  });
  expect(restingNodeShape).toEqual({
    nodeRadius: "50%",
    nodeWidth: "64px",
    nodeHeight: "64px",
    nodeBackground: "rgba(0, 0, 0, 0)",
    nodeBorderWidth: "2px",
    avatarRadius: "50%",
    avatarWidth: "48px",
    avatarHeight: "48px",
    avatarBorderWidth: "0px",
    avatarOverflow: "hidden",
    labelBackground: "rgba(0, 0, 0, 0)",
    labelShadow: "none",
  });
  const dragStart = await node.boundingBox();
  const graphPositionsBefore = await page.locator(".graph-node").evaluateAll((elements) => elements.map((element) => {
    const bounds = element.getBoundingClientRect();
    return { left: bounds.left, top: bounds.top };
  }));
  const graphCanvasBox = await page.locator(".graph-canvas").boundingBox();
  expect(dragStart).not.toBeNull();
  expect(graphCanvasBox).not.toBeNull();
  const dragX = dragStart.x + dragStart.width / 2;
  const dragY = dragStart.y + dragStart.height / 2;
  const dragDx = dragX < graphCanvasBox.x + graphCanvasBox.width / 2 ? 90 : -90;
  const dragDy = dragY < graphCanvasBox.y + graphCanvasBox.height / 2 ? 60 : -60;
  await page.mouse.move(dragX, dragY);
  await page.mouse.down();
  await page.mouse.move(dragX + dragDx, dragY + dragDy, { steps: 8 });
  await page.mouse.up();
  await expect(page.locator(".graph-node.is-selected")).toHaveCount(0);
  await expect.poll(async () => {
    const box = await node.boundingBox();
    return box ? Math.hypot(box.x - dragStart.x, box.y - dragStart.y) : 0;
  }).toBeGreaterThan(70);
  await expect.poll(async () => {
    const positions = await page.locator(".graph-node").evaluateAll((elements) => elements.map((element) => {
      const bounds = element.getBoundingClientRect();
      return { left: bounds.left, top: bounds.top };
    }));
    return Math.max(...positions.slice(1).map((position, index) => Math.hypot(
      position.left - graphPositionsBefore[index + 1].left,
      position.top - graphPositionsBefore[index + 1].top,
    )));
  }).toBeGreaterThan(20);
  const before = await node.evaluate((element) => getComputedStyle(element).transform);
  await page.waitForTimeout(500);
  const after = await node.evaluate((element) => getComputedStyle(element).transform);
  expect(after).not.toBe(before);
  const nodeLayer = page.locator(".graph-node-layer");
  const defaultViewport = await nodeLayer.evaluate((element) => getComputedStyle(element).transform);
  await node.click();
  await expect(node).toHaveClass(/is-selected/);
  expect(await node.evaluate((element) => getComputedStyle(element).outlineStyle)).toBe("none");
  expect(await node.locator(":scope > span").evaluate((element) => getComputedStyle(element).borderRadius)).toBe("50%");
  await expect(page.locator(".graph-profile-card")).toBeVisible();
  const focusedViewport = await nodeLayer.evaluate((element) => getComputedStyle(element).transform);
  expect(focusedViewport).not.toBe(defaultViewport);
  await page.locator(".graph-canvas").click({ position: { x: 12, y: 12 } });
  await expect(page.locator(".graph-node.is-selected")).toHaveCount(0);
  await expect(page.locator(".graph-node.is-muted")).toHaveCount(0);
  await expect(page.locator(".graph-profile-card")).toHaveCount(0);
  await expect.poll(() => nodeLayer.evaluate((element) => getComputedStyle(element).transform)).toBe(defaultViewport);
  const selectedName = await node.locator("strong").textContent();
  await node.click();
  await page.getByRole("button", { name: "进入人物详情" }).click();
  await expect(page.locator(".profile-detail-panel h2")).toHaveText(selectedName);
  await page.getByRole("button", { name: "图谱", exact: true }).click();
  await expect(page.locator(".graph-node.is-selected")).toHaveCount(0);
  await expect(page.locator(".graph-node.is-muted")).toHaveCount(0);
  await expect(page.locator(".graph-profile-card")).toHaveCount(0);
  await expect.poll(() => page.locator(".graph-node-layer").evaluate((element) => getComputedStyle(element).transform)).toBe(defaultViewport);
});

test("设定筛选、标签间距和内容预览保持紧凑", async ({ page }) => {
  await page.goto("/?project=novel#/entries");
  await expect(page.getByRole("combobox", { name: "类型" })).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "搜索设定" })).toHaveCount(0);
  const tagFilter = page.locator(".entries-page-new > .filter-details");
  const headerTagFilter = page.locator(".entry-header-tools > .filter-details");
  await expect(tagFilter).toHaveCount(0);
  await expect(headerTagFilter).toBeVisible();
  await expect(headerTagFilter.locator(".filter-chips")).toBeHidden();
  const workspaceBeforeTags = await page.locator(".entries-page-new .two-column-workspace").boundingBox();
  await headerTagFilter.locator("summary").click();
  await expect(headerTagFilter.locator(".filter-chips")).toBeVisible();
  const workspaceWithTags = await page.locator(".entries-page-new .two-column-workspace").boundingBox();
  expect(Math.abs(workspaceWithTags.y - workspaceBeforeTags.y)).toBeLessThan(1);
  await headerTagFilter.locator("summary").click();
  await expect(headerTagFilter.locator(".filter-chips")).toBeHidden();
  await expect(headerTagFilter.locator("summary")).toHaveAttribute("aria-label", "标签筛选");
  await expect(headerTagFilter.locator("summary .filter-label > span")).toHaveCount(0);
  await page.getByRole("button", { name: "搜索设定" }).click();
  const search = page.getByRole("textbox", { name: "搜索设定" });
  await expect(search).toBeVisible();
  await search.fill("旧港");
  await search.press("Escape");
  await expect(search).toHaveCount(0);

  const workspace = await page.locator(".entries-page-new .two-column-workspace").boundingBox();
  const library = await page.locator(".entries-page-new .entry-library").boundingBox();
  const detail = await page.locator(".entries-page-new .entry-detail-panel").boundingBox();
  expect(library.width).toBeLessThanOrEqual(280);
  expect(detail.width / workspace.width).toBeGreaterThan(.7);
  expect(workspace.y).toBeLessThan(155);
  expect(workspace.height).toBeGreaterThan(540);

  const spacing = await page.locator(".entry-detail-panel").evaluate((panel) => {
    const header = panel.querySelector(":scope > header").getBoundingClientRect();
    const tag = panel.querySelector(":scope > .metadata-tags > span").getBoundingClientRect();
    const section = panel.querySelector(":scope > section").getBoundingClientRect();
    return { top: tag.top - header.bottom, bottom: section.top - tag.bottom };
  });
  expect(Math.abs(spacing.top - spacing.bottom)).toBeLessThan(1);
  expect(spacing.top).toBeGreaterThanOrEqual(8);
  await expect(page.locator(".entry-detail-panel .entry-body-preview.rendered-markdown")).toBeVisible();
});

test("人物资料使用紧凑表格且正文卡片渲染 Markdown", async ({ page }) => {
  await page.goto("/?project=novel#/characters");
  const roleViewToggle = page.getByRole("button", { name: /临时角色/ });
  await roleViewToggle.click();
  await expect(page.getByRole("button", { name: /主要角色/ })).toBeVisible();
  await page.getByRole("button", { name: /主要角色/ }).click();
  await page.getByRole("button", { name: "编辑人物档案" }).click();
  const core = page.getByRole("region", { name: "核心人设" });
  await expect(core.locator(".persona-kv-head")).toBeVisible();
  const coreHeader = await core.locator(":scope > header").boundingBox();
  expect(coreHeader.height).toBeLessThanOrEqual(44);
  expect(await core.locator("h3").evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBeLessThanOrEqual(14);
  await page.getByRole("dialog", { name: "编辑人物档案" }).getByRole("button", { name: "关闭" }).click();

  await page.goto("/?project=novel#/story");
  await expect(page.locator(".plot-card .plot-card-preview.rendered-markdown").first()).toBeVisible();
  const cardLayout = await page.locator(".plot-card").evaluateAll((cards) => cards.map((card) => {
    const bounds = card.getBoundingClientRect();
    const preview = card.querySelector(".plot-card-copy").getBoundingClientRect();
    const tags = card.querySelector(":scope > .metadata-tags").getBoundingClientRect();
    const meta = card.querySelector(".card-meta");
    const previewCopy = card.querySelector(".plot-card-copy");
    return { height: bounds.height, previewBottom: preview.bottom, tagsTop: tags.top, metaAlign: getComputedStyle(meta).justifyContent, clipped: previewCopy.scrollHeight > previewCopy.clientHeight + 1 };
  }));
  expect(cardLayout.every((item) => item.previewBottom <= item.tagsTop && item.metaAlign === "flex-end" && !item.clipped)).toBe(true);
  const cardHeights = cardLayout.map((item) => item.height);
  expect(Math.max(...cardHeights) - Math.min(...cardHeights)).toBeLessThanOrEqual(1);
  expect(Math.max(...cardHeights)).toBeLessThanOrEqual(230);
  const compactCardStyle = await page.locator(".plot-card").first().evaluate((card) => ({
    paddingLeft: parseFloat(getComputedStyle(card).paddingLeft),
    titleSize: parseFloat(getComputedStyle(card.querySelector("h2")).fontSize),
    previewSize: parseFloat(getComputedStyle(card.querySelector(".plot-card-preview")).fontSize),
  }));
  expect(compactCardStyle.paddingLeft).toBeLessThanOrEqual(14);
  expect(compactCardStyle.titleSize).toBeLessThanOrEqual(18);
  expect(compactCardStyle.previewSize).toBeLessThanOrEqual(14);
  await expect(page.locator(".plot-card .plot-card-meta-item").first()).toBeVisible();
  await expect(page.locator(".plot-card .plot-card-meta-item small")).toHaveCount(0);
  const ribbon = page.locator(".plot-card-ribbon").first();
  await expect(ribbon).toBeVisible();
  expect(await ribbon.evaluate((element) => parseFloat(getComputedStyle(element).width))).toBeGreaterThanOrEqual(140);
  expect(await ribbon.evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(12);
  const firstStoryCard = page.locator(".plot-card").first();
  const storyTitle = await firstStoryCard.locator(":scope > .plot-card-copy > h2").textContent();
  await firstStoryCard.click();
  const storyReader = page.getByRole("region", { name: `阅读${storyTitle}` });
  await expect(storyReader).toBeVisible();
  await expect(storyReader.locator(".story-reader-rail")).toBeVisible();
  await expect(storyReader.locator(".story-reader-tools")).toBeVisible();
  await expect(page.locator(".editor-dialog")).toHaveCount(0);
  const progressFillTop = await storyReader.locator(".story-reader-progress b").evaluate((element) => getComputedStyle(element).top);
  expect(progressFillTop).toBe("0px");
  const progressTrack = storyReader.locator(".story-reader-progress i");
  const progressLabels = progressTrack.locator("strong");
  await expect(progressLabels).toHaveCount(2);
  await expect(progressLabels.nth(1)).toHaveClass(/is-inverted/);
  await expect(progressLabels.nth(1)).toHaveAttribute("aria-hidden", "true");
  const outlineLinks = storyReader.locator(".story-reader-rail nav a");
  const outlineCount = await outlineLinks.count();
  if (outlineCount) {
    const outlineLink = outlineLinks.nth(outlineCount - 1);
    const href = await outlineLink.getAttribute("href");
    expect(href).toMatch(/^#/);
    const targetId = href.slice(1);
    const target = page.locator(`#${targetId}`);
    const expectedTop = await target.evaluate((element) => {
      const absoluteTop = element.getBoundingClientRect().top + window.scrollY;
      const maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      return Math.round(absoluteTop - Math.min(maxScroll, Math.max(0, absoluteTop - 82)));
    });
    await outlineLink.click();
    await expect.poll(() => target.evaluate((element) => Math.round(element.getBoundingClientRect().top))).toBe(expectedTop);
  }
  await page.evaluate(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "auto" }));
  const progressBar = storyReader.getByRole("progressbar");
  await expect.poll(async () => Number(await progressBar.getAttribute("aria-valuenow"))).toBe(100);
  const progressColors = await progressTrack.evaluate((element) => {
    const [base, inverted] = element.querySelectorAll("strong");
    return {
      base: getComputedStyle(base).color,
      inverted: getComputedStyle(inverted).color,
      progress: element.style.getPropertyValue("--progress"),
    };
  });
  expect(progressColors.base).not.toBe(progressColors.inverted);
  expect(progressColors.progress).toBe("100%");
  await storyReader.getByRole("button", { name: "返回剧情列表" }).click();
  await page.goto("/?project=novel#/fragments");
  await expect(page.locator(".fragment-card-new .fragment-card-preview.rendered-markdown").first()).toBeVisible();
  await expect(page.locator(".fragment-card-new > p")).toHaveCount(0);
});

test("新建剧情首次保存后原位转为可继续编辑的实体", async ({ page }) => {
  await page.goto("/?project=novel#/story");
  await page.getByRole("button", { name: "写新剧情" }).click();
  const dialog = page.locator(".editor-dialog").filter({ has: page.locator(".markdown-workspace") });
  const settings = dialog.getByRole("button", { name: /剧情设置/ });
  await settings.click();
  await dialog.getByRole("textbox", { name: "标题", exact: true }).fill("连续保存回归剧情");
  const editor = dialog.locator(".cm-content");
  await editor.fill("## 第一次保存\n\n这段正文不会让编辑器重建。");
  await dialog.getByRole("button", { name: /人物拼音检索/ }).click();
  const referenceCommand = page.getByRole("dialog", { name: "人物拼音检索" });
  for (const letter of ["L", "Q"]) {
    await referenceCommand.dispatchEvent("keydown", {
      key: "Process", code: `Key${letter}`, keyCode: 229, isComposing: true,
    });
  }
  await expect(referenceCommand).toContainText("lq");
  await expect(referenceCommand).toContainText("林秋");
  await referenceCommand.press("Enter");
  await expect(referenceCommand).not.toBeVisible();
  await expect(editor).toContainText("林秋");
  await editor.fill("## 第一次保存\n\n这段正文不会让编辑器重建。");
  await editor.evaluate((element) => { window.__createdEditorNode = element; });

  await editor.press(`${primaryKey}+Shift+p`);
  await expect(dialog.locator(".markdown-workspace")).toHaveClass(/preview-hidden/);
  await editor.press(`${primaryKey}+Shift+p`);
  await expect(dialog.locator(".markdown-workspace")).not.toHaveClass(/preview-hidden/);
  await editor.press(`${primaryKey}+Shift+f`);
  await expect(dialog.locator(".markdown-workspace")).toHaveClass(/is-immersive/);
  await editor.press("Escape");
  await expect(dialog.locator(".markdown-workspace")).not.toHaveClass(/is-immersive/);

  const createdDetail = page.waitForResponse((response) =>
    response.request().method() === "GET" && response.url().includes("/entities/plot%3A"),
  );
  await editor.press(`${primaryKey}+s`);
  await createdDetail;
  await expect(dialog.getByRole("button", { name: "删除剧情" })).toBeVisible();
  expect(await editor.evaluate((element) => window.__createdEditorNode === element)).toBe(true);
  await expect(settings).toHaveAttribute("aria-expanded", "true");

  await editor.fill("## 第二次保存\n\n同一个实体继续写入，不会重复新建。");
  await editor.press(`${primaryKey}+s`);
  await expect(dialog.locator(".editor-footer")).toContainText("已保存");
  expect(await editor.evaluate((element) => window.__createdEditorNode === element)).toBe(true);

  const titleInput = dialog.getByRole("textbox", { name: "标题", exact: true });
  await titleInput.fill("连续保存回归剧情·字段快捷保存");
  const metadataSave = page.waitForResponse((response) =>
    response.request().method() === "PATCH" && response.url().includes("/plots/plot%3A"),
  );
  await titleInput.press(`${primaryKey}+s`);
  await metadataSave;
  expect(await editor.evaluate((element) => window.__createdEditorNode === element)).toBe(true);

  const snapshot = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  const matches = snapshot.plots.filter((item) => item.title === "连续保存回归剧情·字段快捷保存");
  expect(matches).toHaveLength(1);
  const detail = await (await page.request.get(`/api/v1/projects/novel/entities/${encodeURIComponent(matches[0].entityId)}`)).json();
  expect(detail.data.body).toContain("第二次保存");

  await dialog.getByRole("button", { name: "删除剧情" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "移入回收站" }).click();
  await expect(dialog).not.toBeVisible();
});

test("正文原位保存并保持编辑器、折叠状态和页面实例", async ({ page }) => {
  await page.goto("/?project=novel#/story");
  await expect(page.getByRole("heading", { name: "雾港纪事", exact: true })).toBeVisible();
  await page.evaluate(() => { window.__storyTellerPageIdentity = "still-here"; });

  const firstCard = page.locator(".plot-card").first();
  await firstCard.click();
  const reader = page.locator(".story-reader-page");
  await expect(reader).toBeVisible();
  await reader.getByRole("button", { name: /^编辑/ }).click();
  const dialog = page.locator(".editor-dialog").filter({ has: page.locator(".markdown-workspace") });
  await expect(dialog).toBeVisible();
  const settings = dialog.getByRole("button", { name: /剧情设置/ });
  await expect(settings).toHaveAttribute("aria-expanded", "false");
  const editor = dialog.locator(".cm-content");
  await editor.fill("## 浏览器回读\n\n沈清妙在旧港确认了新的线索。");
  await dialog.getByRole("button", { name: /保存（/ }).click();
  await expect(dialog.locator(".editor-footer")).toContainText("已保存");
  await expect(settings).toHaveAttribute("aria-expanded", "false");
  await expect(dialog).toBeVisible();
  expect(await page.evaluate(() => window.__storyTellerPageIdentity)).toBe("still-here");
  expect(await page.evaluate(() => performance.getEntriesByType("navigation").length)).toBe(1);

  const snapshot = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  const detail = await (await page.request.get(`/api/v1/projects/novel/entities/${encodeURIComponent(snapshot.plots[0].entityId)}`)).json();
  expect(detail.data.body).toContain("浏览器回读");
  expect(detail.data.body).toContain("新的线索");
});

test("篇章与阅读顺序在一个事务中保存且不改写故事时间", async ({ page }) => {
  await page.goto("/?project=novel#/story");
  const before = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  const storyTime = new Map(before.timeline.nodes.map((item) => [`${item.plotId}\0${item.lineId}`, item.storySortKey]));
  await page.evaluate(() => { window.__structurePageIdentity = "still-here"; });

  await page.getByRole("button", { name: "编辑篇章与阅读顺序" }).click();
  const dialog = page.getByRole("dialog", { name: "编辑篇章与阅读顺序" });
  await expect(dialog).toBeVisible();
  const firstChapterName = dialog.locator(".chapter-editor-list input").first();
  await firstChapterName.fill("浏览器改名篇");
  const secondPlot = dialog.locator(".plot-order-list article").nth(1);
  const movedTitle = await secondPlot.locator("strong").textContent();
  await secondPlot.getByRole("button", { name: /^上移/ }).click();
  await dialog.getByRole("button", { name: "保存结构" }).click();
  await expect(dialog.locator("footer")).toContainText("篇章与阅读顺序已保存");
  await expect(dialog).toBeVisible();
  expect(await page.evaluate(() => window.__structurePageIdentity)).toBe("still-here");

  const after = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  expect(after.chapters[0].label).toBe("浏览器改名篇");
  expect(after.plots[0].title).toBe(movedTitle);
  expect(new Map(after.timeline.nodes.map((item) => [`${item.plotId}\0${item.lineId}`, item.storySortKey]))).toEqual(storyTime);
});

test("人物关系可新增、编辑并进入统一回收站", async ({ page }) => {
  await page.goto("/?project=novel#/characters");
  const snapshot = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  const existing = new Set(snapshot.relationships.map((item) => `${item.from}\0${item.to}`));
  const pair = snapshot.characters.flatMap((left) => snapshot.characters.map((right) => [left, right]))
    .find(([left, right]) => left.entityId !== right.entityId && !existing.has(`${left.entityId}\0${right.entityId}`));
  expect(pair).toBeTruthy();

  await page.locator(".character-list-new > button").filter({ hasText: pair[0].name }).click();
  await page.getByRole("button", { name: `为${pair[0].name}建立人物关系` }).click();
  const dialog = page.getByRole("dialog", { name: "编辑人物关系" });
  const selects = dialog.locator(".relationship-settings select");
  await selects.nth(0).selectOption(pair[0].entityId);
  await selects.nth(1).selectOption(pair[1].entityId);
  await dialog.locator(".relationship-settings input").nth(2).fill("浏览器协作");
  await dialog.locator(".cm-content").fill("两人在档案室建立了临时协作。");
  await dialog.getByRole("button", { name: /保存（/ }).click();
  await expect(dialog.locator(".editor-footer")).toContainText("已保存");
  await expect(dialog.getByRole("button", { name: "删除人物关系" })).toBeVisible();

  await dialog.getByRole("button", { name: "删除人物关系" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "移入回收站" }).click();
  await expect(dialog).not.toBeVisible();
  await page.getByRole("button", { name: "检查" }).click();
  await expect(page.locator(".trash-list-new")).toContainText("浏览器协作");
  await expect(page.locator(".trash-list-new")).toContainText("关系");
  await page.locator(".trash-list-new article").filter({ hasText: "浏览器协作" }).locator(".trash-preview-main").click();
  const preview = page.locator(".trash-preview-dialog");
  await expect(preview).toContainText("两人在档案室建立了临时协作");
  await expect(preview.locator(".trash-preview-prose")).toBeVisible();
  await preview.getByRole("button", { name: "关闭预览" }).click();
});

test("图谱布局参数、人物锚点、距离与分组都可以在网页保存", async ({ page }) => {
  await page.goto("/?project=novel#/graph");
  const before = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  await page.getByRole("button", { name: "编辑人物图谱" }).click();
  const dialog = page.getByRole("dialog", { name: "编辑人物图谱" });
  await dialog.getByRole("spinbutton", { name: "节点间距" }).fill("149");
  await dialog.getByRole("spinbutton", { name: "锚点 X" }).fill("333");
  await dialog.getByRole("spinbutton", { name: "锚点 Y" }).fill("222");

  await dialog.getByText("人物距离约束", { exact: false }).click();
  await dialog.getByRole("button", { name: "添加人物距离约束" }).click();
  await dialog.getByText("视觉分组", { exact: false }).click();
  await dialog.getByRole("button", { name: "添加图谱分组" }).click();
  const clusterName = dialog.getByRole("textbox", { name: /分组 \d+ 名称/ }).last();
  await clusterName.fill("浏览器图谱组");
  await dialog.getByText(before.characters[0].name, { exact: true }).last().click();
  await dialog.getByRole("button", { name: "保存图谱布局" }).click();
  await expect(dialog.locator("footer")).toContainText("图谱布局已保存");
  await expect(dialog).toBeVisible();

  const after = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  expect(after.graph.settings.node_spacing).toBe(149);
  const node = after.graph.nodes.find((item) => item.character_id === before.characters[0].entityId);
  expect(node.anchor_x).toBe(333);
  expect(node.anchor_y).toBe(222);
  expect(after.graph.distances).toHaveLength(before.graph.distances.length + 1);
  expect(after.graph.clusters.some((item) => item.label === "浏览器图谱组" && item.members.includes(before.characters[0].entityId))).toBe(true);
});

test("时间线节点顺序独立于阅读顺序且删除剧情线会转移节点", async ({ page }) => {
  await page.goto("/?project=novel#/timeline");
  const before = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  const readingOrder = before.plots.map((item) => item.entityId);
  const nodeCount = new Map(before.timeline.lines.map((line) => [
    line.entityId,
    before.timeline.nodes.filter((node) => node.lineId === line.entityId).length,
  ]));
  const selectedLine = [...before.timeline.lines].sort((left, right) => nodeCount.get(right.entityId) - nodeCount.get(left.entityId))[0];
  expect(nodeCount.get(selectedLine.entityId)).toBeGreaterThan(1);

  await page.getByRole("button", { name: "编辑时间线" }).click();
  const dialog = page.getByRole("dialog", { name: "编辑时间线" });
  const selectors = dialog.locator(".timeline-editor-toolbar select");
  await selectors.first().selectOption(selectedLine.entityId);
  const chapterSelect = selectors.nth(1);
  const chapterIds = await chapterSelect.locator("option:not([value=''])").evaluateAll((options) => options.slice(0, 2).map((option) => option.value));
  const [firstPlotId, secondPlotId] = chapterIds;
  const firstTitle = before.plots.find((item) => item.entityId === firstPlotId).title;
  const secondTitle = before.plots.find((item) => item.entityId === secondPlotId).title;
  await chapterSelect.selectOption(secondPlotId);
  const activeNode = dialog.locator(`.timeline-editor-track-node[data-plot-id="${secondPlotId}"][data-line-id="${selectedLine.entityId}"]`);
  await expect(activeNode).toHaveClass(/is-active/);
  await expect.poll(async () => {
    const nodeBox = await activeNode.boundingBox();
    const viewportBox = await dialog.locator(".timeline-editor-visual-scroll").boundingBox();
    return Boolean(nodeBox && viewportBox && nodeBox.y >= viewportBox.y && nodeBox.y + nodeBox.height <= viewportBox.y + viewportBox.height);
  }).toBe(true);
  await dialog.getByRole("button", { name: `上移${secondTitle}` }).click();
  await dialog.getByRole("button", { name: "保存时间线" }).click();
  await expect(dialog).not.toBeVisible();

  const reordered = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  expect(reordered.plots.map((item) => item.entityId)).toEqual(readingOrder);
  const titleByPlot = new Map(reordered.plots.map((item) => [item.entityId, item.title]));
  const lineOrder = reordered.timeline.nodes
    .filter((node) => node.lineId === selectedLine.entityId)
    .sort((left, right) => left.storySortKey.localeCompare(right.storySortKey))
    .map((node) => titleByPlot.get(node.plotId));
  expect(lineOrder.slice(0, 2)).toEqual([secondTitle, firstTitle]);

  await page.getByRole("button", { name: "编辑时间线" }).click();
  const deleteDialog = page.getByRole("dialog", { name: "编辑时间线" });
  await deleteDialog.locator(".timeline-editor-toolbar select").first().selectOption(selectedLine.entityId);
  await deleteDialog.getByRole("button", { name: `删除${selectedLine.name}` }).click();
  const confirm = page.getByRole("alertdialog");
  const replacement = await confirm.locator("select").inputValue();
  const affectedPlots = reordered.timeline.nodes
    .filter((node) => node.lineId === selectedLine.entityId)
    .map((node) => node.plotId);
  await confirm.getByRole("button", { name: "转移并删除" }).click();
  await deleteDialog.getByRole("button", { name: "保存时间线" }).click();
  await expect(deleteDialog).not.toBeVisible();
  const afterDelete = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  expect(afterDelete.timeline.lines.some((line) => line.entityId === selectedLine.entityId)).toBe(false);
  for (const plotId of affectedPlots) {
    expect(afterDelete.timeline.nodes.some((node) => node.plotId === plotId && node.lineId === replacement)).toBe(true);
  }
});

test("人物档案使用结构化核心人设、补充人设和档案 KV", async ({ page }) => {
  await page.goto("/?project=novel#/characters");
  await page.getByRole("button", { name: "编辑人物档案" }).click();
  const editor = page.getByRole("dialog", { name: "编辑人物档案" });
  await expect(editor.locator(".markdown-workspace")).toHaveCount(0);

  const core = editor.getByRole("region", { name: "核心人设" });
  await core.getByRole("textbox", { name: "核心人设 1 名称" }).fill("核心欲望");
  await core.getByRole("textbox", { name: "核心人设 1 内容" }).fill("夺回选择自己命运的权力");

  const supplement = editor.getByRole("region", { name: "补充人设" });
  await supplement.getByRole("button", { name: "添加补充人设", exact: true }).click();
  await supplement.locator("input").last().fill("生活习惯");
  await supplement.locator("textarea").last().fill("思考时会按颜色整理便签");

  const facts = editor.getByRole("region", { name: "人物档案" });
  await facts.getByRole("button", { name: "添加人物档案", exact: true }).click();
  await facts.locator("input").last().fill("当前身份");
  await facts.locator("textarea").last().fill("投资人");

  await editor.getByRole("button", { name: /保存（/ }).click();
  await expect(editor.locator(".editor-footer")).toContainText("已保存");
  const snapshot = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  const character = snapshot.characters.find((item) => item.corePersona?.some((trait) => trait.key === "核心欲望"));
  expect(character.corePersona[0]).toEqual({ key: "核心欲望", value: "夺回选择自己命运的权力" });
  expect(character.supplementPersona[0]).toEqual({ key: "生活习惯", value: "思考时会按颜色整理便签" });
  expect(character.facts["当前身份"]).toBe("投资人");
});

test("人物档案内的重命名会确认影响并可整体撤销", async ({ page }) => {
  await page.goto("/?project=novel#/characters");
  const before = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  const character = before.characters[0];
  await page.locator(".character-list-new > button").filter({ hasText: character.name }).click();
  await page.getByRole("button", { name: "编辑人物档案" }).click();
  const editor = page.getByRole("dialog", { name: "编辑人物档案" });
  await editor.getByRole("button", { name: /人物档案设置/ }).click();
  await editor.getByRole("textbox", { name: "姓名" }).fill(`${character.name}·浏览器`);
  await editor.getByRole("button", { name: /保存（/ }).click();
  const rename = page.getByRole("alertdialog", { name: new RegExp(`重命名为“${character.name}·浏览器”`) });
  await expect(rename).toContainText("稳定 ID 不会改变");
  await rename.getByRole("button", { name: "确认重命名" }).click();
  await expect(editor.locator(".editor-footer")).toContainText("已保存");
  await editor.getByRole("button", { name: "关闭" }).click();

  const renamed = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  expect(renamed.characters.find((item) => item.entityId === character.entityId).name).toBe(`${character.name}·浏览器`);
  await page.getByRole("button", { name: "检查" }).click();
  const operation = page.locator(".operation-list-new article").filter({ hasText: "重命名人物" }).first();
  await operation.getByRole("button", { name: /撤销重命名人物/ }).click();
  const undoDialog = page.getByRole("alertdialog", { name: "撤销这项操作？" });
  await undoDialog.getByRole("button", { name: "撤销操作" }).click();
  await expect(undoDialog).not.toBeVisible();
  const restored = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  expect(restored.characters.find((item) => item.entityId === character.entityId).name).toBe(character.name);
});

test("检查页报告可证明的问题并记录可撤销的忽略原因", async ({ page }) => {
  await page.goto("/?project=novel#/characters");
  await page.getByRole("button", { name: "编辑人物档案" }).click();
  const editor = page.getByRole("dialog", { name: "编辑人物档案" });
  await editor.getByRole("button", { name: "删除人物" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "移入回收站" }).click();
  await page.getByRole("button", { name: "检查" }).click();
  const diagnostic = page.locator(".diagnostic-list-new article.is-warning").first();
  await expect(diagnostic).toBeVisible();
  const title = await diagnostic.locator("strong").textContent();
  await diagnostic.getByRole("button", { name: /^忽略/ }).click();
  const confirm = page.getByRole("alertdialog", { name: "暂时忽略这条提醒？" });
  await confirm.getByRole("textbox", { name: "忽略原因" }).fill("浏览器回归：等待角色线确认");
  await confirm.getByRole("button", { name: "记录并忽略" }).click();
  await expect(page.locator(".ignored-diagnostics")).toContainText(title || "");
  await expect(page.locator(".ignored-diagnostics")).toContainText("等待角色线确认");
});
