const { test, expect } = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");

const runtimeProject = path.join(__dirname, ".runtime-content", "novel");

test("所有正文编辑器共享人物和设定智能提示", async ({ page }) => {
  await page.goto("/?project=novel");
  await page.locator('[data-view="story"]').click();
  await page.locator('.plot-card[data-plot-id="1"]').click();
  await page.locator(".plot-edit-btn").click();

  const body = page.locator("#plotCreateBody");
  await body.fill("#旧");
  await expect(page.locator("#smartSuggestPopover")).not.toBeVisible();
  await body.fill("http://旧");
  await expect(page.locator("#smartSuggestPopover")).not.toBeVisible();

  await body.fill("");
  await body.dispatchEvent("compositionstart");
  await body.fill("@陆");
  await expect(page.locator("#smartSuggestPopover")).not.toBeVisible();
  await body.dispatchEvent("compositionend");
  await expect(page.locator("#smartSuggestPopover")).toBeVisible();
  await body.press("Escape");

  await body.fill("@luchenzhou");
  await expect(page.locator("#smartSuggestPopover")).toContainText("陆沉舟");
  await expect(page.locator("#smartSuggestPopover")).toContainText("拼音：lu chen zhou");
  await body.press("Escape");
  await body.fill("@lcz");
  await expect(page.locator("#smartSuggestPopover")).toContainText("陆沉舟");
  await body.press("Escape");
  await body.fill("/jiugang");
  await expect(page.locator("#smartSuggestPopover")).toContainText("旧港");
  await body.press("Escape");
  await body.fill("/jg");
  await expect(page.locator("#smartSuggestPopover")).toContainText("旧港");
  await body.press("Escape");

  await page.locator('#plotCreatePeople option[value="2"]').evaluate((option) => { option.selected = false; });
  await body.fill("@陆");
  await expect(page.locator("#smartSuggestPopover")).toBeVisible();
  await expect(page.locator(".smart-suggest-head")).toContainText("人物");
  await expect(page.locator(".smart-suggest-option").first()).toContainText("陆沉舟");
  await body.press("Enter");
  await expect(body).toHaveValue("陆沉舟");
  await expect(page.locator('#plotCreatePeople option[value="2"]')).toHaveJSProperty("selected", true);

  await page.locator('#plotCreateEntries option[value="old-port"]').evaluate((option) => { option.selected = false; });
  await body.press("End");
  await body.type("来到/旧");
  await expect(page.locator("#smartSuggestPopover")).toBeVisible();
  await expect(page.locator(".smart-suggest-head")).toContainText("设定与名词");
  await expect(page.locator(".smart-suggest-option").first()).toContainText("旧港");
  await body.press("Enter");
  await body.type("见面。");
  await expect(body).toHaveValue("陆沉舟来到旧港见面。");
  await expect(page.locator('#plotCreateEntries option[value="old-port"]')).toHaveJSProperty("selected", true);
  await page.locator("#plotCreateSubmit").click();
  await expect(page.locator("#plotCreateDialog")).not.toBeVisible();

  const readback = await (await page.request.get("/api/project-data?project=novel")).json();
  expect(readback.documents["plots/001-初见.md"]).toContain("陆沉舟来到旧港见面。");
  expect(readback.documents["plots/001-初见.md"]).toMatch(/people:.*2/);
  expect(readback.documents["plots/001-初见.md"]).toMatch(/entries:.*old-port/);
  const exportedPlot = fs.readFileSync(path.join(runtimeProject, "plots", "001-初见.md"), "utf8");
  expect(exportedPlot).toContain("陆沉舟来到旧港见面。");
  expect(exportedPlot).toMatch(/entries:.*old-port/);

  await page.locator('[data-view="characters"]').click();
  await page.locator('.character-list-item[data-id="2"]').click();
  await page.getByRole("button", { name: /编辑陆沉舟的档案/ }).click();
  await page.locator("#ceIntro").fill("/旧");
  await expect(page.locator("#smartSuggestPopover")).toContainText("旧港");
  await page.locator("#ceIntro").press("Enter");
  await expect(page.locator("#ceIntro")).toHaveValue("旧港");
  await page.locator("#contentEditorCancel").click();

  await page.locator('[data-view="places"]').click();
  await page.locator('.place-list-item[data-id="old-port"]').click();
  await page.getByRole("button", { name: "编辑旧港" }).click();
  await page.locator("#ceBody").fill("@陆");
  await expect(page.locator("#smartSuggestPopover")).toContainText("陆沉舟");
  await page.locator("#ceBody").press("Enter");
  await expect(page.locator("#ceBody")).toHaveValue("陆沉舟");
  await page.locator("#contentEditorCancel").click();

  await page.locator('[data-view="fragments"]').click();
  await page.getByRole("button", { name: "编辑雨夜草稿" }).click();
  await page.locator("#ceBody").fill("@陆");
  await expect(page.locator("#smartSuggestPopover")).toContainText("陆沉舟");
  await page.locator("#ceBody").press("Enter");
  await expect(page.locator("#ceBody")).toHaveValue("陆沉舟");
  await page.locator("#contentEditorCancel").click();
});
