const { test, expect } = require("@playwright/test");

test("静态快照可以完整阅读且不会调用本地写入接口", async ({ page }) => {
  const projectRequests = [];
  const writes = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/v1/projects/")) projectRequests.push(request.url());
    if (request.method() !== "GET") writes.push(`${request.method()} ${request.url()}`);
  });
  await page.goto("/?project=novel#/story");
  const staticSnapshot = await (await page.request.get("/project.snapshot.json")).json();
  await expect(page.locator(".mode-indicator")).toHaveText("只读快照");
  await expect(page.getByRole("button", { name: "写新剧情" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "编辑篇章与阅读顺序" })).toHaveCount(0);

  const firstCard = page.locator(".plot-card").first();
  const title = await firstCard.locator(".plot-card-copy > h2").textContent();
  await firstCard.click();
  const reader = page.getByRole("region", { name: `阅读${title}` });
  await expect(reader).toBeVisible();
  await expect(reader.locator(".story-reader-prose")).not.toBeEmpty();
  await expect(reader.getByRole("button", { name: /^编辑/ })).toHaveCount(0);
  await reader.getByRole("button", { name: "返回剧情列表" }).click();

  await page.getByRole("button", { name: "碎片" }).click();
  await expect(page.locator(".fragment-card-new .icon-button")).toHaveCount(0);
  await page.locator(".fragment-card-new").first().click();
  await expect(page.locator(".reader-dialog .reader-prose")).toContainText(staticSnapshot.fragments[0].body.slice(0, 20));
  await page.getByRole("button", { name: "关闭阅读" }).click();

  await page.getByRole("button", { name: "检查" }).click();
  await expect(page.getByRole("heading", { name: "快照内容" })).toBeVisible();
  await expect(page.locator(".static-summary")).toContainText("本地 SQLite 服务");
  expect(projectRequests).toEqual([]);
  expect(writes).toEqual([]);
});
