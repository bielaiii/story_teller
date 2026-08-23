const { test, expect } = require("@playwright/test");

const primaryKey = process.platform === "darwin" ? "Meta" : "Control";

test("剧情页 Markdown 导入入口保持横向单行", async ({ page }) => {
  await page.goto("/?project=novel#/story");
  const importButton = page.getByRole("button", { name: "导入 Markdown" });

  await expect(importButton).toHaveText("导入");
  const layout = await importButton.evaluate((element) => {
    const styles = getComputedStyle(element);
    const bounds = element.getBoundingClientRect();
    return {
      whiteSpace: styles.whiteSpace,
      writingMode: styles.writingMode,
      width: bounds.width,
      height: bounds.height,
    };
  });

  expect(layout.whiteSpace).toBe("nowrap");
  expect(layout.writingMode).toBe("horizontal-tb");
  expect(layout.width).toBeGreaterThan(layout.height);
});

test("剧情设置使用单选下拉框且卡片标题不与正文重叠", async ({ page }) => {
  await page.goto("/?project=novel#/story");
  await page.getByRole("button", { name: "写新剧情" }).click();

  const editor = page.getByRole("dialog", { name: "写新剧情" });
  await editor.getByRole("button", { name: "剧情设置", exact: true }).click();
  const storySelect = editor.getByRole("combobox", { name: "故事", exact: true });
  await expect(storySelect).toBeVisible();
  expect(await storySelect.getAttribute("multiple")).toBeNull();
  await expect(storySelect.locator("option").first()).toHaveText("主线（默认）");
  await editor.getByRole("button", { name: "关闭", exact: true }).click();

  const cards = page.locator(".plot-card");
  await expect(cards.first()).toBeVisible();
  const overlappingTitles = await cards.evaluateAll((items) => items.flatMap((card) => {
    const title = card.querySelector(".plot-card-title");
    const preview = card.querySelector(".complete-block-preview");
    if (!title || !preview) return [];
    return title.getBoundingClientRect().bottom > preview.getBoundingClientRect().top + 1
      ? [title.textContent || "未命名剧情"]
      : [];
  }));
  expect(overlappingTitles).toEqual([]);
});

test("碎片与剧情可以通过编辑器双向放入并保留删除入口", async ({ page }) => {
  await page.goto("/?project=novel#/fragments");
  await page.getByRole("button", { name: "新建碎片" }).click();
  const fragmentEditor = page.locator(".fragment-editor-dialog");
  await fragmentEditor.getByRole("textbox", { name: "标题" }).fill("转换流程测试");
  await fragmentEditor.locator(".editor-settings-popover").getByRole("button", { name: "关闭章节设置" }).click();
  await fragmentEditor.locator(".cm-content").fill("## 雨夜\n\n林秋沿着码头继续追查。");
  await fragmentEditor.locator(".cm-content").press(`${primaryKey}+s`);
  await expect(fragmentEditor.getByRole("button", { name: "删除碎片" })).toBeVisible();
  await expect(fragmentEditor.getByRole("button", { name: "放入剧情" })).toBeVisible();

  await fragmentEditor.getByRole("button", { name: "放入剧情" }).click();
  const toPlot = page.getByRole("alertdialog");
  await expect(toPlot).toContainText("转正时必须指定正式章号");
  await toPlot.getByRole("spinbutton", { name: "正式章号" }).fill("7777");
  await toPlot.getByRole("button", { name: "放入剧情" }).click();

  const reader = page.locator(".story-reader-page");
  await expect(reader).toBeVisible();
  const plotHeading = reader.getByRole("heading", { name: "转换流程测试", level: 1 });
  await expect(plotHeading).toBeVisible();
  const plotTitle = await plotHeading.textContent();
  const afterPlot = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  const convertedPlot = afterPlot.plots.find((item) => item.title === plotTitle);
  expect(convertedPlot.summary).toBe("");
  expect(convertedPlot.chapterId).toBe("");
  expect(convertedPlot.chapterNumber).toBe(7777);
  const plotDetail = await (await page.request.get(
    `/api/v1/projects/novel/entities/${encodeURIComponent(convertedPlot.entityId)}`,
  )).json();
  expect(plotDetail.data.body).toContain("林秋沿着码头继续追查");

  await reader.getByRole("button", { name: `编辑${plotTitle}` }).click();
  const plotEditor = page.locator(".editor-dialog").filter({ has: page.locator(".markdown-workspace") });
  await expect(plotEditor.getByRole("button", { name: "删除剧情" })).toBeVisible();
  const moveToFragments = plotEditor.getByRole("button", { name: "放入碎片箱" });
  const settingsToggle = plotEditor.getByRole("button", { name: /剧情设置/ });
  await expect(moveToFragments).toBeVisible();
  const settingsBox = await settingsToggle.boundingBox();
  const moveBox = await moveToFragments.boundingBox();
  expect(settingsBox).not.toBeNull();
  expect(moveBox).not.toBeNull();
  expect(moveBox.x - (settingsBox.x + settingsBox.width)).toBeGreaterThanOrEqual(6);
  await moveToFragments.click();
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

test("保存已有碎片后回到列表会按最近修改时间置顶", async ({ page }) => {
  await page.goto("/?project=novel#/fragments");
  const cards = page.locator(".fragment-grid-new > .fragment-card-new");
  await expect(cards.nth(2)).toBeVisible();
  const target = cards.nth(2);
  const targetTitle = await target.locator(".fragment-card-copy > h2").innerText();
  await target.getByRole("button", { name: `编辑${targetTitle}`, exact: true }).click();

  const editor = page.locator(".fragment-editor-dialog");
  await expect(editor).toBeVisible();
  const body = editor.locator(".cm-content");
  await body.fill("## 最近修改验证\n\n保存之后，这条碎片应该出现在列表最前面。");
  await body.press(`${primaryKey}+s`);
  await expect(editor.locator(".editor-footer")).toContainText("已保存");
  await editor.getByRole("button", { name: "关闭", exact: true }).click();

  await expect(cards.first().locator(".fragment-card-copy > h2")).toHaveText(targetTitle);
  const snapshot = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  expect(snapshot.fragments[0].title).toBe(targetTitle);
  const detail = await (await page.request.get(
    `/api/v1/projects/novel/entities/${encodeURIComponent(snapshot.fragments[0].entityId)}`,
  )).json();
  expect(detail.data.body).toContain("保存之后，这条碎片应该出现在列表最前面");
});
