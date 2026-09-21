const { test, expect } = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
function readSnapshot(root) {
  return JSON.parse(execFileSync(path.resolve(__dirname, "../../scripts/python.sh"), ["-c", "import json,sys; from storyteller.exports.incremental import load_snapshot; print(json.dumps(load_snapshot(sys.argv[1])))", path.join(root, "project.snapshot.json")], { encoding: "utf8" }));
}
function projectRoot() {
  return fs.readFileSync(path.resolve(__dirname, "../e2e/.runtime-content/v3-project-root.txt"), "utf8");
}

test("保存立即回读正文，后台导出完成前保留编辑器和输入", async ({ page }) => {
  await page.goto("/?project=novel#/story");
  await page.locator(".plot-card").first().click();
  await page.locator(".story-reader-page").getByRole("button", { name: /^编辑/ }).click();
  const dialog = page.locator(".editor-dialog").filter({ has: page.locator(".markdown-workspace") });
  const editor = dialog.locator(".cm-content");
  const body = "后台导出验收：正文先提交到 SQLite。";
  await editor.fill(body);
  await editor.evaluate((node) => { window.__savedEditor = node; });
  const responsePromise = page.waitForResponse((response) => response.request().method() === "PATCH" && response.url().includes("/plots/"));
  await dialog.getByRole("button", { name: /保存（/ }).click();
  const response = await responsePromise;
  expect(response.ok()).toBeTruthy();
  const result = await response.json();
  expect(result.export.status).toBe("pending");
  await expect(dialog.locator(".editor-footer")).toContainText("已保存");
  await expect(page.locator(".export-status")).toContainText("正文已保存，正在更新导出");
  await page.screenshot({ path: test.info().outputPath("export-pending.png") });
  const changedPlot = result.changed.plots[0];
  const detail = await (await page.request.get(`/api/v1/projects/novel/entities/${encodeURIComponent(changedPlot.entityId)}`)).json();
  expect(detail.data.body).toBe(body);
  await editor.fill(`${body}\n导出时继续写的新草稿。`);
  await expect.poll(async () => (await (await page.request.get("/api/v1/projects/novel/exports")).json()).status).toBe("ready");
  const exported = readSnapshot(projectRoot());
  expect(exported.project.revision).toBe(result.projectRevision);
  expect(exported.plots.find((plot) => plot.entityId === changedPlot.entityId).body).toBe(body);
  await expect(page.locator(".export-status")).toHaveCount(0);
  await expect(editor).toContainText("导出时继续写的新草稿");
  expect(await editor.evaluate((node) => node === window.__savedEditor)).toBe(true);
  expect(await page.evaluate(() => performance.getEntriesByType("navigation").length)).toBe(1);
});


test("导出失败时正文仍已保存，下一次保存恢复导出状态", async ({ page }) => {
  const marker = path.join(projectRoot(), ".fail-export");
  await page.goto("/?project=novel#/story");
  await page.locator(".plot-card").first().click();
  await page.locator(".story-reader-page").getByRole("button", { name: /^编辑/ }).click();
  const dialog = page.locator(".editor-dialog").filter({ has: page.locator(".markdown-workspace") });
  const editor = dialog.locator(".cm-content");
  fs.writeFileSync(marker, "fail derived export only");
  try {
    await editor.fill("导出故障期间保存的正文");
    const responsePromise = page.waitForResponse((response) => response.request().method() === "PATCH" && response.url().includes("/plots/"));
    await dialog.getByRole("button", { name: /保存（/ }).click();
    const result = await (await responsePromise).json();
    await expect(dialog.locator(".editor-footer")).toContainText("已保存");
    await expect(page.locator(".export-status")).toContainText("正文已保存，导出失败：test export disk failure");
    await page.screenshot({ path: test.info().outputPath("export-failed.png") });
    const detail = await (await page.request.get(`/api/v1/projects/novel/entities/${encodeURIComponent(result.changed.plots[0].entityId)}`)).json();
    expect(detail.data.body).toBe("导出故障期间保存的正文");
  } finally {
    fs.rmSync(marker, { force: true });
  }
  await editor.fill("故障恢复后继续保存的正文");
  await dialog.getByRole("button", { name: /保存（/ }).click();
  await expect(dialog.locator(".editor-footer")).toContainText("已保存");
  await expect.poll(async () => (await (await page.request.get("/api/v1/projects/novel/exports")).json()).status).toBe("ready");
  await expect(page.locator(".export-status")).toHaveCount(0);
  const exported = readSnapshot(projectRoot());
  expect(exported.plots.some((plot) => plot.body === "故障恢复后继续保存的正文")).toBe(true);
  await expect(editor).toHaveText("故障恢复后继续保存的正文");
});
