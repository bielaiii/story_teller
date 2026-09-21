const { test, expect } = require('@playwright/test');

async function openEditor(page, index) {
  await page.goto('/?project=novel#/story');
  await page.locator('.plot-card').nth(index).click();
  await page.locator('.story-reader-page').getByRole('button', { name: /^编辑/ }).click();
  const dialog = page.locator('.editor-dialog').filter({ has: page.locator('.markdown-workspace') });
  await expect(dialog.locator('.cm-content')).toBeVisible();
  return dialog;
}
async function save(page, dialog, body) {
  await dialog.locator('.cm-content').fill(body);
  const pending = page.waitForResponse(r => r.request().method() === 'PATCH' && r.url().includes('/plots/'));
  await dialog.getByRole('button', { name: /保存（/ }).click();
  const response = await pending;
  expect(response.ok()).toBeTruthy();
  await expect(dialog.locator('.editor-footer')).toContainText('已保存');
  return response.json();
}
test('旧窗口保存补齐其他剧情，激活同步保留草稿并拒绝覆盖新正文', async ({ browser }) => {
  const a = await browser.newContext();
  const b = await browser.newContext();
  const pageA = await a.newPage();
  const pageB = await b.newPage();
  try {
    const editorA = await openEditor(pageA, 0);
    const editorB = await openEditor(pageB, 1);
    const first = await save(pageA, editorA, '窗口甲的完整正文');
    const readSnapshot = pageB.waitForResponse(r => r.url().includes('/snapshot'));
    const second = await save(pageB, editorB, '窗口乙的完整正文');
    const synced = await (await readSnapshot).json();
    expect(synced.plots.find(p => p.entityId === first.changed.plots[0].entityId).bodyPreview).toContain('窗口甲');
    expect(synced.project.revision).toBeGreaterThanOrEqual(second.projectRevision);
    // A second save in the same editor must use its new baseline.
    await save(pageB, editorB, '窗口乙第二次保存');
    const input = editorA.locator('.cm-content');
    await input.fill('甲尚未保存的草稿');
    await input.evaluate(node => { window.originalEditor = node; });
    const id = first.changed.plots[0].entityId;
    const detail = await (await pageB.request.get(`/api/v1/projects/novel/entities/${encodeURIComponent(id)}`)).json();
    const meta = await (await pageB.request.get('/api/v1/meta?project=novel')).json();
    const latest = await (await pageB.request.get('/api/v1/projects/novel/snapshot')).json();
    const external = await pageB.request.patch(`/api/v1/projects/novel/plots/${encodeURIComponent(id)}`, {
      headers: { 'X-Story-Teller-Token': meta.mutationToken },
      data: { baseRevision: latest.project.revision, entityRevision: detail.revision, body: '其他窗口更新同一正文' },
    });
    expect(external.ok()).toBeTruthy();
    const activated = pageA.waitForResponse(r => r.url().includes('/snapshot'));
    await pageA.evaluate(() => window.dispatchEvent(new Event('focus')));
    await activated;
    await expect(pageA.locator('.story-reader-prose')).toContainText('其他窗口更新同一正文');
    await expect(input).toHaveText('甲尚未保存的草稿');
    expect(await input.evaluate(node => node === window.originalEditor)).toBe(true);
    const conflict = pageA.waitForResponse(r => r.status() === 409);
    await editorA.getByRole('button', { name: /保存（/ }).click();
    await conflict;
    await expect(editorA.locator('.editor-footer')).toContainText('合并');
    const persisted = await (await pageA.request.get(`/api/v1/projects/novel/entities/${encodeURIComponent(id)}`)).json();
    expect(persisted.data.body).toBe('其他窗口更新同一正文');
    await expect(input).toHaveText('甲尚未保存的草稿');
  } finally {
    await a.close(); await b.close();
  }
});
