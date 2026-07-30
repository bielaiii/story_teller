const { test, expect } = require("@playwright/test");

const primaryKey = process.platform === "darwin" ? "Meta" : "Control";

test("碎片与剧情可以通过编辑器双向放入并保留删除入口", async ({ page }) => {
  await page.goto("/?project=novel#/fragments");
  await page.getByRole("button", { name: "写灵感碎片" }).click();
  const fragmentEditor = page.locator(".fragment-editor-dialog");
  await fragmentEditor.getByRole("button", { name: /灵感设置/ }).click();
  await fragmentEditor.getByRole("textbox", { name: "标题" }).fill("转换流程测试");
  await fragmentEditor.locator(".cm-content").fill("## 雨夜\n\n林秋沿着码头继续追查。");
  await fragmentEditor.locator(".cm-content").press(`${primaryKey}+s`);
  await expect(fragmentEditor.getByRole("button", { name: "删除碎片" })).toBeVisible();
  await expect(fragmentEditor.getByRole("button", { name: "放入剧情" })).toBeVisible();

  await fragmentEditor.getByRole("button", { name: "放入剧情" }).click();
  const toPlot = page.getByRole("alertdialog");
  await expect(toPlot).toContainText("自动分配下一个章号");
  await toPlot.getByRole("button", { name: "放入剧情" }).click();

  const reader = page.locator(".story-reader-page");
  await expect(reader).toBeVisible();
  await expect(reader.locator(".story-reader-article > header > div > p")).toHaveText("转换流程测试");
  const plotTitle = await reader.locator(".story-reader-article h1").textContent();
  const afterPlot = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  const convertedPlot = afterPlot.plots.find((item) => item.title === plotTitle);
  expect(convertedPlot.summary).toBe("转换流程测试");
  expect(convertedPlot.chapterId).toBe("");
  const plotDetail = await (await page.request.get(
    `/api/v1/projects/novel/entities/${encodeURIComponent(convertedPlot.entityId)}`,
  )).json();
  expect(plotDetail.data.body).toContain("林秋沿着码头继续追查");

  await reader.getByRole("button", { name: `编辑${plotTitle}` }).click();
  const plotEditor = page.locator(".editor-dialog").filter({ has: page.locator(".markdown-workspace") });
  await expect(plotEditor.getByRole("button", { name: "删除剧情" })).toBeVisible();
  await expect(plotEditor.getByRole("button", { name: "放入碎片箱" })).toBeVisible();
  await plotEditor.getByRole("button", { name: "放入碎片箱" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "放入碎片箱" }).click();

  await expect(page.locator(".story-page")).toBeVisible();
  await expect(page.locator(".fragments-page-new")).not.toBeVisible();
  const afterFragment = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  const convertedFragment = afterFragment.fragments.find((item) => item.title === plotTitle);
  expect(convertedFragment).toBeTruthy();
  const fragmentDetail = await (await page.request.get(
    `/api/v1/projects/novel/entities/${encodeURIComponent(convertedFragment.entityId)}`,
  )).json();
  expect(fragmentDetail.data.body).toContain("林秋沿着码头继续追查");
  await page.getByRole("button", { name: "碎片" }).click();
  await page.locator(".fragment-card-new").filter({ hasText: plotTitle }).click();
  await expect(page.locator(".reader-prose")).toContainText("林秋沿着码头继续追查");
  await page.getByRole("button", { name: "关闭阅读" }).click();

  const trash = await (await page.request.get("/api/v1/projects/novel/trash")).json();
  expect(trash.items.some((item) => item.kind === "fragment" && item.title === "转换流程测试")).toBe(true);
  expect(trash.items.some((item) => item.kind === "plot" && item.entityId === convertedPlot.entityId)).toBe(true);
});
