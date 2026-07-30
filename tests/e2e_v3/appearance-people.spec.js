const { test, expect } = require("@playwright/test");
const primaryKey = process.platform === "darwin" ? "Meta" : "Control";

test("碎片设置会识别已有人物并把正文中的新姓名建为一次性角色", async ({ page }) => {
  await page.goto("/?project=novel#/fragments");
  await page.getByRole("button", { name: "新建碎片" }).click();

  const editor = page.locator(".fragment-editor-dialog");
  await editor.getByRole("textbox", { name: "章节标题" }).fill("出场人物浏览器验证");
  await editor.locator(".cm-content").fill(
    "## 雨夜会面\n\n林秋在码头见到了温砚。温砚把档案交给林秋。",
  );

  await expect(editor.locator(".appearance-people-field")).toContainText("出场人物");
  await expect(editor.locator(".appearance-people-list")).toContainText("林秋");

  await editor.getByRole("textbox", { name: "新增出场人物姓名" }).fill("周既明");
  await editor.getByRole("button", { name: "添加出场人物" }).click();
  await expect(editor.getByRole("alert")).toContainText("没有出现在当前正文中");

  await editor.getByRole("textbox", { name: "新增出场人物姓名" }).fill("温砚");
  await editor.getByRole("button", { name: "添加出场人物" }).click();
  await expect(editor.locator(".appearance-people-list")).toContainText("保存后建为临时人物");

  await editor.locator(".cm-content").press(`${primaryKey}+s`);
  await expect(editor.locator(".editor-footer")).toContainText("已保存");

  const snapshot = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  const fragment = snapshot.fragments.find((item) => item.title === "出场人物浏览器验证");
  const temporary = snapshot.characters.find((item) => item.name === "温砚");
  const known = snapshot.characters.find((item) => item.name === "林秋");
  expect(fragment).toBeTruthy();
  expect(temporary?.characterScope).toBe("一次性角色");
  const detail = await (await page.request.get(
    `/api/v1/projects/novel/entities/${encodeURIComponent(fragment.entityId)}`,
  )).json();
  expect(detail.data.references).toEqual(expect.arrayContaining([
    known.entityId,
    temporary.entityId,
  ]));

  await editor.getByRole("button", { name: "关闭" }).click();
  await page.getByRole("button", { name: "人物", exact: true }).click();
  await page.getByRole("button", { name: /临时角色/ }).click();
  await page.locator(".character-list-new button").filter({ hasText: "温砚" }).click();

  const relatedFragment = page.locator(".character-related-plots button")
    .filter({ hasText: "出场人物浏览器验证" });
  await expect(relatedFragment).toContainText("灵感碎片");
  await relatedFragment.click();
  await expect(page.getByRole("dialog", { name: "阅读出场人物浏览器验证" })).toBeVisible();
});

test("全局搜索显示命中上下文并避开顶部导航", async ({ page }) => {
  await page.goto("/?project=novel#/story");
  await page.getByRole("button", { name: "全局搜索" }).click();
  await page.getByPlaceholder("搜索人物、剧情、设定和正文").fill("第三个抽屉");

  const result = page.locator(".command-results button").filter({ hasText: "第三个抽屉" });
  await expect(result).toBeVisible();
  await expect(result.locator("mark")).toHaveText("第三个抽屉");

  const navigationBox = await page.locator(".main-nav").boundingBox();
  const panelBox = await page.locator(".command-panel").boundingBox();
  expect(navigationBox).not.toBeNull();
  expect(panelBox).not.toBeNull();
  expect(panelBox.y).toBeGreaterThanOrEqual(navigationBox.y + navigationBox.height + 8);
});
