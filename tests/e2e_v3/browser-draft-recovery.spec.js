const { test, expect } = require("@playwright/test");

test("人物草稿在页面重载后恢复，并在写入令牌失效后直接保存", async ({ page }) => {
  await page.goto("/?project=novel#/characters");
  const snapshot = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  const character = snapshot.characters[0];
  const characterButton = page.locator(".character-list-new > button").filter({ hasText: character.name }).first();
  await characterButton.click();
  await page.getByRole("button", { name: "编辑人物档案" }).click();

  let editor = page.getByRole("dialog", { name: "编辑人物档案" });
  await editor.getByRole("textbox", { name: "分组" }).fill("浏览器恢复测试");
  await expect(editor.locator(".editor-footer")).toContainText("已暂存在浏览器");

  await page.reload();
  await page.locator(".character-list-new > button").filter({ hasText: character.name }).first().click();
  await page.getByRole("button", { name: "编辑人物档案" }).click();
  editor = page.getByRole("dialog", { name: "编辑人物档案" });
  await expect(editor.getByRole("textbox", { name: "分组" })).toHaveValue("浏览器恢复测试");

  let rejectedOldToken = false;
  await page.route("**/api/v1/projects/novel/characters/**", async (route) => {
    if (route.request().method() === "PATCH" && !rejectedOldToken) {
      rejectedOldToken = true;
      await route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ detail: "写入授权已失效，请刷新本地服务能力" }),
      });
      return;
    }
    await route.continue();
  });

  await editor.getByRole("button", { name: /保存（/ }).click();
  await expect(editor.locator(".editor-footer")).toContainText("已保存");
  expect(rejectedOldToken).toBe(true);
  const saved = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  expect(saved.characters.find((item) => item.entityId === character.entityId).group).toBe("浏览器恢复测试");
});
