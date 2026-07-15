const { test, expect } = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");

const runtimeProject = path.join(__dirname, ".runtime-content", "novel");

test("碎片可以编写长剧本且不会自动进入剧情", async ({ page }) => {
  await page.goto("/?project=novel");
  await page.locator('[data-view="fragments"]').click();
  await page.getByRole("button", { name: "编辑雨夜草稿" }).click();

  const dialog = page.locator("#contentEditorDialog");
  await expect(dialog).toHaveClass(/is-fragment-writer/);
  await expect(dialog).toContainText("保存后仍只在碎片箱中");
  await expect(page.locator(".fragment-editor-meta")).not.toHaveAttribute("open", "");

  await page.locator("#ceBody").fill("# 雨夜重逢\n\n沈清妙推开仓库门。\n\n- 门外有脚步声\n- 灯光突然熄灭");
  await expect(page.locator("#fragmentEditorPreview")).toContainText("雨夜重逢");
  await expect(page.locator("#fragmentEditorPreview li")).toHaveCount(2);
  await page.locator("#contentEditorSubmit").click();

  await expect(dialog).not.toBeVisible();
  await expect(page.locator("#fragment-scene-draft")).toContainText("沈清妙推开仓库门");
  await expect(page.locator('[data-page="fragments"]')).toHaveClass(/is-active/);
  await expect(page.locator('[data-page="story"]')).not.toHaveClass(/is-active/);
  expect(fs.readFileSync(path.join(runtimeProject, "fragments", "scene-draft.md"), "utf8")).toContain("雨夜重逢");
  expect(fs.readdirSync(path.join(runtimeProject, "plots")).filter((name) => name.endsWith(".md"))).toHaveLength(12);
});
