const { test, expect } = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");

const runtimeProject = path.join(__dirname, ".runtime-content", "novel");

test("碎片可以编写长剧本且不会自动进入剧情", async ({ page }) => {
  await page.goto("/?project=novel");
  await page.locator('[data-view="fragments"]').click();
  const fragmentCard = page.locator("#fragment-scene-draft");
  await expect(fragmentCard).not.toContainText("CARD_TAIL_HIDDEN");
  await expect(fragmentCard.locator(".fragment-body")).toHaveCSS("overflow", "hidden");
  await page.getByRole("button", { name: "编辑雨夜草稿" }).click();

  const dialog = page.locator("#contentEditorDialog");
  await expect(dialog).toHaveClass(/is-fragment-writer/);
  await expect(dialog).toContainText("保存后仍只在碎片箱中");
  await expect(page.locator(".fragment-editor-meta")).not.toHaveAttribute("open", "");

  const longDraft = Array.from({ length: 36 }, (_, index) => `## 场景 ${index + 1}\n\n沈清妙推开第 ${index + 1} 扇仓库门。`).join("\n\n");
  await page.locator("#ceBody").fill(longDraft);
  await expect(page.locator("#fragmentEditorPreview")).toContainText("场景 1");
  await expect(page.locator("#fragmentEditorPreview")).toContainText("场景 36");

  await page.locator("#ceBody").evaluate((element) => {
    element.scrollTop = (element.scrollHeight - element.clientHeight) * 0.72;
    element.dispatchEvent(new Event("scroll"));
  });
  await expect.poll(() => page.evaluate(() => {
    const source = document.querySelector("#ceBody");
    const preview = document.querySelector("#fragmentEditorPreview");
    const sourceProgress = source.scrollTop / Math.max(1, source.scrollHeight - source.clientHeight);
    const previewProgress = preview.scrollTop / Math.max(1, preview.scrollHeight - preview.clientHeight);
    return Math.abs(sourceProgress - previewProgress);
  })).toBeLessThan(0.06);

  await page.locator("#fragmentEditorPreview").evaluate((element) => {
    element.scrollTop = (element.scrollHeight - element.clientHeight) * 0.28;
    element.dispatchEvent(new Event("scroll"));
  });
  await expect.poll(() => page.evaluate(() => {
    const source = document.querySelector("#ceBody");
    const preview = document.querySelector("#fragmentEditorPreview");
    const sourceProgress = source.scrollTop / Math.max(1, source.scrollHeight - source.clientHeight);
    const previewProgress = preview.scrollTop / Math.max(1, preview.scrollHeight - preview.clientHeight);
    return Math.abs(sourceProgress - previewProgress);
  })).toBeLessThan(0.06);

  await page.getByRole("button", { name: "进入沉浸写作" }).click();
  await expect(dialog).toHaveClass(/is-immersive/);
  await expect(page.getByRole("button", { name: "退出沉浸写作" })).toBeVisible();
  const immersiveSize = await dialog.boundingBox();
  expect(immersiveSize.width).toBeGreaterThan(1200);
  expect(immersiveSize.height).toBeGreaterThan(700);
  await page.getByRole("button", { name: "退出沉浸写作" }).click();
  await expect(dialog).not.toHaveClass(/is-immersive/);
  await expect(page.locator("#ceBody")).toHaveValue(longDraft);
  await page.locator("#contentEditorSubmit").click();

  await expect(dialog).not.toBeVisible();
  await expect(page.locator("#fragment-scene-draft")).toContainText("沈清妙推开第 1 扇仓库门");
  await expect(page.locator('[data-page="fragments"]')).toHaveClass(/is-active/);
  await expect(page.locator('[data-page="story"]')).not.toHaveClass(/is-active/);
  expect(fs.readFileSync(path.join(runtimeProject, "fragments", "scene-draft.md"), "utf8")).toContain("场景 36");
  expect(fs.readdirSync(path.join(runtimeProject, "plots")).filter((name) => name.endsWith(".md"))).toHaveLength(12);
});
