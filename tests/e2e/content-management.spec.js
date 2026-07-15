const { test, expect } = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");

const runtimeProject = path.join(__dirname, ".runtime-content", "novel");

test("人物档案信息和补充设定完整显示并可无刷新保存", async ({ page }) => {
  await page.goto("/?project=novel");
  await page.locator('[data-view="characters"]').click();
  await page.locator('.character-list-item[data-id="1"]').click();
  await page.evaluate(() => { window.__characterSupplementsSentinel = "alive"; });

  const facts = page.locator(".character-facts");
  await expect(page.locator(".character-facts-section")).toBeVisible();
  await expect(page.locator(".character-fact")).toHaveCount(3);
  await expect(page.locator(".character-fact").nth(2)).toContainText("阵营");
  expect(await facts.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(" ").length)).toBe(2);
  await expect(page.locator(".character-supplement-item")).toHaveCount(6);
  await expect(page.locator(".character-supplement-section")).toContainText("不愿在公开场合谈论旧案");

  await page.getByRole("button", { name: "编辑沈清妙的档案" }).click();
  await expect(page.locator("#ceIntro")).toHaveValue("旧人物设定");
  await page.locator("#ceSupplements").fill("保留旧案剪报。\n压力过大时会反复确认门锁。\n不在雨天做最终决定。");
  await page.locator("#contentEditorSubmit").click();
  await expect(page.locator("#contentEditorDialog")).not.toBeVisible();
  await expect(page.locator(".character-supplement-item")).toHaveCount(3);
  await expect(page.locator(".character-supplement-section")).toContainText("不在雨天做最终决定");
  expect(await page.evaluate(() => window.__characterSupplementsSentinel)).toBe("alive");

  const databaseReadback = await (await page.request.get("/api/project-data?project=novel")).json();
  expect(databaseReadback.documents["characters/1-沈清妙.md"]).toContain("压力过大时会反复确认门锁");
  expect(fs.readFileSync(path.join(runtimeProject, "characters", "1-沈清妙.md"), "utf8")).toContain("不在雨天做最终决定");

  await page.setViewportSize({ width: 600, height: 900 });
  expect(await facts.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(" ").length)).toBe(1);
});

test("新建人物时可以直接写入核心和补充设定", async ({ page }) => {
  await page.goto("/?project=novel");
  await page.locator('[data-view="characters"]').click();
  await page.evaluate(() => { window.__characterCreateSentinel = "alive"; });
  await page.locator("#characterCreateTrigger").click();
  await page.locator("#characterCreateName").fill("顾遥");
  await page.locator("#characterCreateIntro").fill("追查旧港失踪案。\n逐步学会信任同伴。");
  await page.locator("#characterCreateSupplements").fill("随身携带录音笔。\n会避开没有第二出口的房间。");
  await page.locator("#characterCreateSubmit").click();

  await expect(page.locator("#characterCreateDialog")).not.toBeVisible();
  await expect(page.getByRole("heading", { name: "顾遥" })).toBeVisible();
  await expect(page.locator(".character-supplement-item")).toHaveCount(2);
  await expect(page.locator(".character-supplement-section")).toContainText("随身携带录音笔");
  expect(await page.evaluate(() => window.__characterCreateSentinel)).toBe("alive");

  const databaseReadback = await (await page.request.get("/api/project-data?project=novel")).json();
  expect(databaseReadback.documents["characters/3-顾遥.md"]).toContain("会避开没有第二出口的房间");
});

test("剧情状态筛选只显示真实状态且默认全部选中", async ({ page }) => {
  await page.goto("/?project=novel");
  await page.locator('[data-view="story"]').click();
  const statusButtons = page.locator("#statusFilter .filter-chip");
  await expect(statusButtons).toHaveCount(2);
  expect(await statusButtons.allTextContents()).not.toContain("全部");
  await expect(statusButtons.first()).toHaveAttribute("aria-pressed", "true");
  await expect(statusButtons.nth(1)).toHaveAttribute("aria-pressed", "true");
  await statusButtons.first().click();
  await expect(statusButtons.first()).toHaveAttribute("aria-pressed", "true");
  await expect(statusButtons.nth(1)).toHaveAttribute("aria-pressed", "false");
  await statusButtons.first().click();
  await expect(statusButtons.first()).toHaveAttribute("aria-pressed", "true");
  await expect(statusButtons.nth(1)).toHaveAttribute("aria-pressed", "true");

  const tagButtons = page.locator("#tagFilter .filter-chip");
  await expect(tagButtons).toHaveCount(3);
  await tagButtons.first().evaluate((element) => { element.dataset.identityProbe = "preserved"; });
  await tagButtons.first().click();
  await expect(tagButtons.first()).toHaveAttribute("data-identity-probe", "preserved");
  await expect(tagButtons.first()).toHaveAttribute("aria-pressed", "true");
  await expect(tagButtons.nth(1)).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator("#plotStrip .plot-card").first()).toHaveClass(/is-filter-result/);
  await expect(tagButtons.first()).toBeFocused();
  await tagButtons.first().click();
  await expect(tagButtons.first()).toHaveAttribute("data-identity-probe", "preserved");
  await expect(tagButtons.nth(1)).toHaveAttribute("aria-pressed", "true");
});

test("人物编辑重命名、删除、预览和恢复保持页面状态", async ({ page }) => {
  await page.goto("/?project=novel");
  await page.locator('[data-view="characters"]').click();
  await expect(page.locator('[data-page="characters"]')).toHaveClass(/is-active/);

  await page.evaluate(() => { window.__storyTellerE2ESentinel = "alive"; });
  await page.locator('.character-list-item[data-id="1"]').click();
  await page.getByRole("button", { name: "编辑沈清妙的档案" }).click();
  await page.locator("#ceName").fill("沈清妍");
  await page.locator("#ceIntro").fill("第一条设定\n第二条设定");
  await page.locator("#contentEditorSubmit").click();
  await expect(page.locator("#contentEditorRenamePreview")).toBeVisible();
  await page.locator("#contentEditorSubmit").click();
  await expect(page.locator("#contentEditorDialog")).not.toBeVisible();
  await expect(page.getByRole("heading", { name: "沈清妍" })).toBeVisible();
  expect(await page.evaluate(() => window.__storyTellerE2ESentinel)).toBe("alive");

  const renamedCharacter = path.join(runtimeProject, "characters", "1-沈清妍.md");
  await expect.poll(() => fs.existsSync(renamedCharacter)).toBe(true);
  expect(fs.readFileSync(renamedCharacter, "utf8")).toContain("第一条设定\n第二条设定");
  expect(fs.readFileSync(path.join(runtimeProject, "plots", "001-初见.md"), "utf8")).toContain("沈清妍与陆沉舟");

  await page.locator('.character-list-item[data-id="2"]').click();
  await page.getByRole("button", { name: "删除陆沉舟" }).click();
  const confirmDialog = page.locator("#appConfirmDialog");
  await expect(confirmDialog).toBeVisible();
  await expect(confirmDialog).toContainText("内容会保留 7 天");
  await page.getByRole("button", { name: "取消删除陆沉舟" }).click();
  await expect(confirmDialog).not.toBeVisible();
  await expect(page.locator('.character-list-item[data-id="2"]')).toBeVisible();
  await page.getByRole("button", { name: "删除陆沉舟" }).click();
  await page.getByRole("button", { name: "确认删除陆沉舟" }).click();
  await expect(page.locator('.character-list-item[data-id="2"]')).toHaveCount(0);
  expect(await page.evaluate(() => window.__storyTellerE2ESentinel)).toBe("alive");

  await page.locator('[data-view="diagnostics"]').click();
  await page.locator("#plotTrashTrigger").click();
  const trashItem = page.locator(".plot-trash-item").filter({ hasText: "陆沉舟" });
  await trashItem.getByRole("button", { name: "预览陆沉舟" }).click();
  await expect(page.locator(".plot-trash-preview-body")).toContainText("可以恢复的人物设定");
  await trashItem.getByRole("button", { name: "恢复陆沉舟" }).click();
  await expect(page.locator(".plot-trash-item").filter({ hasText: "陆沉舟" })).toHaveCount(0);
  expect(await page.evaluate(() => window.__storyTellerE2ESentinel)).toBe("alive");
  await expect.poll(() => fs.existsSync(path.join(runtimeProject, "characters", "2-陆沉舟.md"))).toBe(true);
});
