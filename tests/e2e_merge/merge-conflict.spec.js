const { test, expect } = require("@playwright/test");

test("数据库冲突阻止写入，并通过清晰选择完成合并", async ({ page }) => {
  await page.goto("/?project=novel#/story");

  const dialog = page.getByRole("alertdialog", { name: "完成内容合并后继续写作" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("无冲突的修改已经自动合入");
  await expect(dialog.getByRole("button", { name: "关闭" })).toHaveCount(0);
  await expect(dialog).toContainText("当前电脑保留的摘要");
  await expect(dialog).toContainText("另一台电脑写下的新摘要");
  await page.screenshot({
    path: "test-results/merge-conflict-dialog.png",
    fullPage: true,
  });

  const meta = await (await page.request.get("/api/v1/meta?project=novel")).json();
  const snapshot = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  const blocked = await page.request.patch("/api/v1/projects/novel/plots/plot:1", {
    headers: { "X-Story-Teller-Token": meta.mutationToken },
    data: {
      baseRevision: snapshot.project.revision,
      entityRevision: snapshot.plots.find((item) => item.entityId === "plot:1").revision,
      summary: "合并前不应允许的新修改",
    },
  });
  expect(blocked.status()).toBe(423);
  expect((await blocked.json()).code).toBe("merge_required");

  await dialog.getByRole("button", { name: /采用远程更新/ }).click();
  await dialog.getByRole("button", { name: "保存这项选择" }).click();
  const finish = dialog.getByRole("button", { name: "完成合并，进入工作台" });
  await expect(finish).toBeEnabled();
  await finish.click();

  await expect(dialog).toBeHidden();
  const resolvedMeta = await (await page.request.get("/api/v1/meta?project=novel")).json();
  expect(resolvedMeta.mergeRequired).toBe(false);
  expect(resolvedMeta.contentWritable).toBe(true);
  const detail = await (
    await page.request.get("/api/v1/projects/novel/entities/plot:1")
  ).json();
  expect(detail.data.summary).toBe("另一台电脑写下的新摘要");

  const latest = await (await page.request.get("/api/v1/projects/novel/snapshot")).json();
  const writable = await page.request.patch("/api/v1/projects/novel/plots/plot:1", {
    headers: { "X-Story-Teller-Token": resolvedMeta.mutationToken },
    data: {
      baseRevision: latest.project.revision,
      entityRevision: latest.plots.find((item) => item.entityId === "plot:1").revision,
      summary: "合并完成后允许的新修改",
    },
  });
  expect(writable.status()).toBe(200);
});
