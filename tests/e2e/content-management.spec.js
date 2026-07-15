const { test, expect } = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");

const runtimeProject = path.join(__dirname, ".runtime-content", "novel");

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
