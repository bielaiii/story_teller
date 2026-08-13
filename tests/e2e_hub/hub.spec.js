const { test, expect } = require("@playwright/test");
const { execFileSync } = require("node:child_process");
const { existsSync } = require("node:fs");

function projectBodies(contentRoot, project) {
  const script = [
    "import json, sqlite3, sys",
    "con=sqlite3.connect(sys.argv[1])",
    "print(json.dumps([row[0] for row in con.execute(\"SELECT body_markdown FROM plots\")], ensure_ascii=False))",
  ].join(";");
  return JSON.parse(execFileSync("python3", ["-c", script, `${contentRoot}/${project}/story.db`], { encoding: "utf8" }));
}

test("manages two content roots, multiple projects, and MCP lifecycle", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Story Teller Hub" })).toBeVisible();

  const alpha = page.locator("article").filter({ hasText: "Alpha Content" });
  const beta = page.locator("article").filter({ hasText: "Beta Content" });
  await expect(alpha).toContainText("demo");
  await expect(alpha).toContainText("side-story");
  await expect(beta).toContainText("Web 运行中");
  await expect(beta).toContainText("MCP 运行中");
  await expect(beta).toContainText("跟随 Web");

  const promptValues = ["browser-project", "浏览器新项目"];
  const answerPrompt = (dialog) => dialog.accept(promptValues.shift());
  page.on("dialog", answerPrompt);
  await alpha.getByRole("button", { name: "新建 Project" }).click();
  await expect(alpha).toContainText("browser-project");
  page.off("dialog", answerPrompt);
  const registered = await (await page.request.get("/api/v1/contents")).json();
  const alphaRoot = registered.workspaces.find((item) => item.displayName === "Alpha Content").contentRoot;
  expect(existsSync(`${alphaRoot}/browser-project/story.db`)).toBe(true);
  await alpha.locator("details").getByText("运行诊断").click();
  await alpha.getByRole("button", { name: "查看 Web 日志" }).click();
  await expect(page.getByRole("dialog")).toContainText("Content 运行日志");
  await page.getByRole("dialog").getByRole("button", { name: "关闭" }).click();

  const sideStory = alpha.locator(".project").filter({ hasText: "side-story" });
  await sideStory.getByRole("link", { name: "打开" }).click();
  await expect(page.getByRole("application", { name: /人物关系图谱/ })).toBeVisible();
  await expect(page).toHaveURL(/\/w\/workspace-[^/]+\/\?project=side-story/);

  await page.goto("/");
  const refreshedBeta = page.locator("article").filter({ hasText: "Beta Content" });
  await refreshedBeta.getByRole("button", { name: "开启 MCP 独立运行" }).click();
  await expect(refreshedBeta).toContainText("独立运行");
  page.once("dialog", (dialog) => dialog.accept());
  await refreshedBeta.getByRole("button", { name: "停止 Content" }).click();
  await expect(refreshedBeta).toContainText("Web 已停止");
  await expect(refreshedBeta).toContainText("MCP 运行中");
  await refreshedBeta.getByRole("button", { name: "改为跟随 Web" }).click();
  await expect(refreshedBeta).toContainText("MCP 已停止");
  await refreshedBeta.getByRole("button", { name: "启动 Content" }).click();
  await expect(refreshedBeta).toContainText("Web 运行中");
  await expect(refreshedBeta).toContainText("MCP 运行中");
  await expect(refreshedBeta).toContainText("Hub 托管");
});

test("writes through the workspace gateway only to the selected content database", async ({ page }) => {
  await page.goto("/");
  const alpha = page.locator("article").filter({ hasText: "Alpha Content" });
  const alphaDemo = alpha.locator(".project").filter({ hasText: "demo" });
  await alphaDemo.getByRole("link", { name: "打开" }).click();
  await page.getByRole("button", { name: "剧情", exact: true }).click();
  await page.getByRole("button", { name: "写新剧情" }).click();
  const dialog = page.locator(".editor-dialog").filter({ has: page.locator(".markdown-workspace") });
  const settings = dialog.getByRole("button", { name: /剧情设置/ });
  await settings.click();
  await dialog.getByRole("textbox", { name: "剧情标题" }).fill("Hub 隔离验证剧情");
  await dialog.getByRole("spinbutton", { name: "章号" }).fill("977");
  await dialog.locator(".editor-settings-popover").getByRole("button", { name: "关闭剧情设置" }).click();
  const marker = "Hub 跨 Content 写入隔离验证";
  const editor = dialog.locator(".cm-content");
  await editor.fill(`## ${marker}\n\n这段内容只能进入 Alpha Content。`);
  await editor.press("Control+s");
  await expect(dialog.locator(".editor-footer")).toContainText("已保存");

  const contents = await (await page.request.get("/api/v1/contents")).json();
  const alphaRoot = contents.workspaces.find((item) => item.displayName === "Alpha Content").contentRoot;
  const betaRoot = contents.workspaces.find((item) => item.displayName === "Beta Content").contentRoot;
  expect(projectBodies(alphaRoot, "demo").some((body) => body.includes(marker))).toBe(true);
  expect(projectBodies(betaRoot, "demo").some((body) => body.includes(marker))).toBe(false);
});

test("keeps the browser draft and recovers after its content worker returns", async ({ browser }) => {
  const writer = await browser.newPage();
  const manager = await browser.newPage();
  await manager.goto("/");
  const alpha = manager.locator("article").filter({ hasText: "Alpha Content" });
  const writerHref = await alpha.locator(".project").filter({ hasText: "demo" }).getByRole("link", { name: "打开" }).getAttribute("href");
  await writer.goto(writerHref);
  await writer.getByRole("button", { name: "剧情", exact: true }).click();
  await writer.getByRole("button", { name: "写新剧情" }).click();
  const dialog = writer.locator(".editor-dialog").filter({ has: writer.locator(".markdown-workspace") });
  const settings = dialog.getByRole("button", { name: /剧情设置/ });
  await settings.click();
  await dialog.getByRole("textbox", { name: "剧情标题" }).fill("Worker 恢复草稿");
  await dialog.getByRole("spinbutton", { name: "章号" }).fill("978");
  await dialog.locator(".editor-settings-popover").getByRole("button", { name: "关闭剧情设置" }).click();
  const editor = dialog.locator(".cm-content");
  await editor.fill("## Worker 恢复草稿\n\n服务停止时这段文字仍留在浏览器中。");

  await manager.goto("/");
  const managedAlpha = manager.locator("article").filter({ hasText: "Alpha Content" });
  manager.once("dialog", (nativeDialog) => nativeDialog.accept());
  await managedAlpha.getByRole("button", { name: "停止 Content" }).click();
  await expect(managedAlpha).toContainText("Web 已停止");
  await editor.press("Control+s");
  await expect(writer.getByText("服务正在重启，草稿已保存，正在等待恢复…")).toBeVisible();
  await managedAlpha.getByRole("button", { name: "启动 Content" }).click();
  await expect(managedAlpha).toContainText("Web 运行中");
  await expect(writer.getByText("服务已恢复，可以继续保存")).toBeVisible({ timeout: 15_000 });
  await expect(editor).toContainText("服务停止时这段文字仍留在浏览器中");
  await editor.press("Control+s");
  await expect(dialog.locator(".editor-footer")).toContainText("已保存");
  await writer.close();
  await manager.goto("/");
  const beta = manager.locator("article").filter({ hasText: "Beta Content" });
  const registry = await (await manager.request.get("/api/v1/contents")).json();
  const betaRoot = registry.workspaces.find((item) => item.displayName === "Beta Content").contentRoot;
  manager.once("dialog", (nativeDialog) => nativeDialog.accept());
  await beta.getByRole("button", { name: "从 Hub 移除" }).click();
  await expect(beta).toHaveCount(0);
  expect(existsSync(`${betaRoot}/demo/story.db`)).toBe(true);
  await manager.close();
});
