const { test, expect } = require("@playwright/test");

test("时间线编辑器预览跟随焦点并表达插入删除", async ({ page }) => {
  await page.goto("/?project=novel");
  await page.locator('[data-view="timeline"]').click();
  await page.getByRole("button", { name: "编辑时间线" }).click();

  const preview = page.locator("#timelineEditorPreviewViewport");
  await expect(preview).toBeVisible();
  await expect(page.locator('.timeline-editor-preview-lane[data-preview-line="主线"]')).toBeVisible();
  await expect(page.locator('.timeline-editor-preview-lane[data-preview-line="支线"]')).toBeVisible();

  await page.locator('.timeline-editor-event-row[data-plot-id="12"]').click();
  await expect(page.locator('.timeline-editor-preview-node[data-preview-plot-id="12"]')).toHaveClass(/is-active/);
  await expect.poll(() => preview.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);

  await page.locator('.timeline-editor-line-row[data-line="支线"]').click();
  await expect(page.locator('.timeline-editor-preview-lane[data-preview-line="支线"]')).toHaveClass(/is-focused/);
  await expect(page.locator("#timelineEditorEventList .timeline-editor-event-row")).toHaveCount(6);

  await page.getByRole("button", { name: "新建剧情线" }).click();
  const insertedLine = page.locator(".timeline-editor-preview-lane.is-inserting");
  await expect(insertedLine).toBeVisible();
  const insertedName = await insertedLine.getAttribute("data-preview-line");
  await expect(page.locator(`.timeline-editor-line-row[data-line="${insertedName}"]`)).toHaveClass(/is-active/);

  await page.getByRole("button", { name: "删除这条剧情线" }).click();
  await expect(page.locator("#appConfirmDialog")).toBeVisible();
  await page.getByRole("button", { name: `确认删除剧情线${insertedName}` }).click();
  await expect(page.locator(`.timeline-editor-preview-lane.is-removing[data-preview-line="${insertedName}"]`)).toBeVisible();
  await expect(page.locator('.timeline-editor-preview-lane.is-receiving[data-preview-line="主线"]')).toBeVisible();
  await expect(page.locator(`.timeline-editor-line-row[data-line="${insertedName}"]`)).toHaveCount(0);

  await expect(page.locator(".timeline-editor-preview-lane.is-removing")).toHaveCount(0);
  await page.locator('.timeline-editor-line-settings-trigger[data-line="支线"]').click();
  await page.locator("#timelineEditorTransferLine").selectOption({ label: "主线" });
  await page.getByRole("button", { name: "删除这条剧情线" }).click();
  await page.getByRole("button", { name: "确认删除剧情线支线" }).click();
  await expect(page.locator('.timeline-editor-preview-lane.is-removing[data-preview-line="支线"]')).toBeVisible();
  await expect(page.locator('.timeline-editor-preview-lane.is-receiving[data-preview-line="主线"]')).toBeVisible();
  await expect(page.locator('.timeline-editor-preview-node.is-active[data-line="主线"]')).toBeVisible();

  await page.getByRole("button", { name: "保存时间线" }).click();
  await expect(page.locator("#timelineEditorDialog")).not.toBeVisible();

  await page.locator('[data-view="diagnostics"]').click();
  await page.getByRole("button", { name: "查看回收站" }).click();
  await page.locator("#plotTrashKindFilter").selectOption("timeline");
  const deletedLine = page.locator(".plot-trash-item").filter({ hasText: "支线" });
  await expect(deletedLine).toContainText("剧情线");
  await deletedLine.getByRole("button", { name: "预览支线" }).click();
  await expect(page.locator("#plotTrashPreview")).toContainText("恢复会撤销这次结构删除");
  await deletedLine.getByRole("button", { name: "恢复支线" }).click();
  await expect(page.locator(".plot-trash-item").filter({ hasText: "支线" })).toHaveCount(0);

  await page.getByRole("button", { name: "关闭回收站" }).click();
  await page.locator('[data-view="timeline"]').click();
  await page.getByRole("button", { name: "编辑时间线" }).click();
  await expect(page.locator('.timeline-editor-line-row[data-line="支线"]')).toBeVisible();
});
