const { test, expect } = require("@playwright/test");

test("碎片图谱使用白色无边界画布与悬浮工具栏", async ({ page }) => {
  await page.goto("/?project=novel#/fragments/board");

  const shell = page.locator(".fragment-board-shell");
  const toolbar = page.locator(".fragment-board-toolbar");
  const canvas = page.locator(".fragment-board-canvas");
  await expect(canvas).toBeVisible();
  const layout = await page.evaluate(() => {
    const shellElement = document.querySelector(".fragment-board-shell");
    const toolbarElement = document.querySelector(".fragment-board-toolbar");
    const canvasElement = document.querySelector(".fragment-board-canvas");
    const shellStyle = getComputedStyle(shellElement);
    const toolbarStyle = getComputedStyle(toolbarElement);
    const canvasStyle = getComputedStyle(canvasElement);
    const shellBounds = shellElement.getBoundingClientRect();
    const canvasBounds = canvasElement.getBoundingClientRect();
    return {
      shellBorder: shellStyle.borderTopWidth,
      shellRadius: shellStyle.borderTopLeftRadius,
      shellShadow: shellStyle.boxShadow,
      toolbarPosition: toolbarStyle.position,
      toolbarBorder: toolbarStyle.borderBottomWidth,
      toolbarBackground: toolbarStyle.backgroundColor,
      canvasBackground: canvasStyle.backgroundColor,
      canvasStartsAtShell: Math.abs(canvasBounds.top - shellBounds.top) <= 1,
    };
  });

  expect(layout).toEqual({
    shellBorder: "0px",
    shellRadius: "0px",
    shellShadow: "none",
    toolbarPosition: "absolute",
    toolbarBorder: "0px",
    toolbarBackground: "rgba(0, 0, 0, 0)",
    canvasBackground: "rgb(255, 255, 255)",
    canvasStartsAtShell: true,
  });
  await expect(shell).toBeVisible();
  await expect(toolbar).toBeVisible();
  await expect(page.getByRole("heading", { name: "灵感碎片箱" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "从剪贴板导入" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "卡片", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "图", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "新建碎片", exact: true })).toBeVisible();
});

test("拖动画布时不会选中节点文字，阅读正文仍可选择", async ({ page }) => {
  await page.goto("/?project=novel#/fragments/board");

  const node = page.locator(".fragment-board-node").first();
  const nodeText = node.locator("strong");
  await expect(node).toBeVisible();
  expect(await nodeText.evaluate((element) => getComputedStyle(element).userSelect)).toBe("none");

  const nodeBox = await node.boundingBox();
  expect(nodeBox).not.toBeNull();
  await page.mouse.move(nodeBox.x + nodeBox.width / 2, nodeBox.y + nodeBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(nodeBox.x + nodeBox.width / 2 + 120, nodeBox.y + nodeBox.height / 2 + 36, { steps: 8 });
  await page.mouse.up();
  expect(await page.evaluate(() => window.getSelection()?.toString() || "")).toBe("");

  await node.click();
  const readerText = page.locator(".fragment-board-reader-prose");
  await expect(readerText).toBeVisible();
  expect(await readerText.evaluate((element) => getComputedStyle(element).userSelect)).not.toBe("none");
});

test("碎片画布切换、阅读、拖动持久化和重新整理不修改项目内容", async ({ page }) => {
  const before = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  expect(before.fragments.length).toBeGreaterThan(0);

  await page.goto("/?project=novel#/fragments");
  await page.getByRole("button", { name: "图", exact: true }).click();
  await expect(page).toHaveURL(/#\/fragments\/board$/);
  await expect(page.locator(".fragment-board-shell")).toBeVisible();
  await expect(page.getByText(`${before.fragments.length} 个碎片`, { exact: true })).toBeVisible();
  await expect(page.locator(".fragment-board-node").first()).toBeVisible();

  const firstNode = page.locator(".fragment-board-node").first();
  const entityId = await firstNode.getAttribute("data-entity-id");
  const initialStyle = await firstNode.getAttribute("style");
  const box = await firstNode.boundingBox();
  expect(box).not.toBeNull();
  await firstNode.hover();
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 96, box.y + box.height / 2 + 52, { steps: 8 });
  await page.mouse.up();

  const movedNode = page.locator(`.fragment-board-node[data-entity-id="${entityId}"]`);
  await expect.poll(() => movedNode.getAttribute("style")).not.toBe(initialStyle);
  const movedStyle = await movedNode.getAttribute("style");
  await expect(page.locator(".fragment-board-reader")).toHaveCount(0);
  await page.waitForTimeout(220);

  await page.reload();
  await expect(page.locator(`.fragment-board-node[data-entity-id="${entityId}"]`)).toHaveAttribute("style", movedStyle);
  await page.locator(`.fragment-board-node[data-entity-id="${entityId}"]`).click();
  const reader = page.locator(".fragment-board-reader");
  await expect(reader).toBeVisible();
  await expect(reader.getByRole("button", { name: "复制正文" })).toBeVisible();
  await expect(reader.getByRole("button", { name: "沉浸阅读" })).toBeVisible();
  await reader.getByRole("button", { name: "关闭画布阅读" }).click();

  await page.locator(`.fragment-board-node[data-entity-id="${entityId}"]`).focus();
  await page.keyboard.press("Enter");
  await expect(reader).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(reader).toHaveCount(0);

  await page.getByRole("button", { name: "重新整理画布" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "重新整理" }).click();
  await expect(page.locator(`.fragment-board-node[data-entity-id="${entityId}"]`)).not.toHaveAttribute("style", movedStyle);

  const after = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  expect(after.project.revision).toBe(before.project.revision);

  await page.getByRole("button", { name: "卡片", exact: true }).click();
  await expect(page).toHaveURL(/#\/fragments$/);
  await expect(page.locator(".fragment-board-shell")).toHaveCount(0);
  await expect(page.locator(".fragment-card-new").first()).toBeVisible();
});

test("图视图隐藏标签筛选，切回卡片后恢复", async ({ page }) => {
  const snapshot = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  const tags = [...new Set(snapshot.fragments.flatMap((item) => item.tags))];
  test.skip(tags.length < 1, "fixture needs fragment tags");

  await page.goto("/?project=novel#/fragments/board");
  await expect(page.getByText(`${snapshot.fragments.length} 个碎片`, { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: tags[0], exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "卡片", exact: true }).click();
  await expect(page.getByRole("button", { name: tags[0], exact: true })).toBeVisible();
});

test("窄屏阅读层覆盖画布，关闭后回到原节点", async ({ page }) => {
  await page.setViewportSize({ width: 760, height: 720 });
  await page.goto("/?project=novel#/fragments/board");
  const node = page.locator(".fragment-board-node").first();
  const entityId = await node.getAttribute("data-entity-id");
  await node.click();

  const shell = page.locator(".fragment-board-shell");
  const reader = page.locator(".fragment-board-reader");
  await expect(reader).toBeVisible();
  const [shellBox, readerBox, position] = await Promise.all([
    shell.boundingBox(),
    reader.boundingBox(),
    reader.evaluate((element) => getComputedStyle(element).position),
  ]);
  expect(position).toBe("absolute");
  expect(Math.abs(readerBox.width - shellBox.width)).toBeLessThanOrEqual(2);

  await reader.getByRole("button", { name: "关闭画布阅读" }).click();
  await expect(page.locator(`.fragment-board-node[data-entity-id="${entityId}"]`)).toBeVisible();
});
