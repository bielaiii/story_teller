const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

async function openEditor(page) {
  await page.goto('/?project=novel#/story');
  await page.locator('.plot-card').first().click();
  await page.locator('.story-reader-page').getByRole('button', { name: /^编辑/ }).click();
  const dialog = page.locator('.editor-dialog').filter({ has: page.locator('.markdown-workspace') });
  await expect(dialog.locator('.cm-content')).toBeVisible();
  return dialog;
}
async function latest(page) {
  return (await page.request.get('/api/v1/projects/novel/snapshot')).json();
}
async function externalEdit(page, id, body) {
  const snapshot = await latest(page);
  const meta = await (await page.request.get('/api/v1/meta?project=novel')).json();
  const detail = await (await page.request.get(`/api/v1/projects/novel/entities/${encodeURIComponent(id)}`)).json();
  const response = await page.request.patch(`/api/v1/projects/novel/plots/${encodeURIComponent(id)}`, {
    headers: { 'X-Story-Teller-Token': meta.mutationToken },
    data: { baseRevision: snapshot.project.revision, entityRevision: detail.revision, body },
  });
  expect(response.ok()).toBeTruthy();
}
function readBodyFromDisk(id) {
  const root = fs.readFileSync(path.resolve(__dirname, '../e2e/.runtime-content/v3-project-root.txt'), 'utf8');
  return execFileSync(path.resolve(__dirname, '../../scripts/python.sh'), ['-c',
    'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute("select body_markdown from plots where entity_id=?",(sys.argv[2],)).fetchone()[0],end="")',
    path.join(root, 'story.db'), id], { encoding: 'utf8' });
}

test('旧草稿先对比，确认后保存并从 SQLite 回读，连续保存保持版本正确', async ({ page }) => {
  let dialog = await openEditor(page);
  const snapshot = await latest(page);
  const id = snapshot.plots[0].entityId;
  const key = `story-teller:browser-draft:direct:novel:plot:${encodeURIComponent(id)}`;
  await dialog.locator('.cm-content').fill('跨重启保留的旧草稿');
  await expect.poll(() => page.evaluate(key => JSON.parse(localStorage.getItem(key) || '{}').version, key)).toBe(2);
  await externalEdit(page, id, '另一个窗口已经保存的新版正文');
  await page.evaluate(() => history.replaceState({}, '', '/?project=novel#/story'));
  await page.reload();
  dialog = await openEditor(page);
  await expect(dialog.locator('.cm-content')).toHaveText('跨重启保留的旧草稿');
  await expect(dialog.getByLabel('草稿版本冲突')).toBeVisible();
  await dialog.getByRole('button', { name: /保存（/ }).click();
  await expect(dialog.locator('.editor-footer')).toContainText('先对比');
  expect(readBodyFromDisk(id)).toBe('另一个窗口已经保存的新版正文');
  await dialog.getByRole('button', { name: '对比草稿与最新内容' }).click();
  await expect(dialog.locator('.draft-comparison')).toContainText('另一个窗口已经保存的新版正文');
  await page.screenshot({ path: test.info().outputPath('draft-comparison.png') });
  await dialog.locator('.cm-content').fill('手动合并后的正文');
  await dialog.getByRole('button', { name: '已对比，使用当前草稿继续编辑' }).click();
  for (const body of ['手动合并后的正文', '同一编辑器第二次保存']) {
    await dialog.locator('.cm-content').fill(body);
    const response = page.waitForResponse(r => r.request().method() === 'PATCH' && r.url().includes('/plots/'));
    await dialog.getByRole('button', { name: /保存（/ }).click();
    expect((await response).ok()).toBeTruthy();
    await expect(dialog.locator('.editor-footer')).toContainText('已保存');
    expect(readBodyFromDisk(id)).toBe(body);
    await expect(page.locator('.story-reader-prose')).toContainText(body);
  }
});

test('服务启动失败不会加载静态快照，重连后保留编辑器和草稿', async ({ page }) => {
  const staticRequests = [];
  page.on('request', r => { if (r.url().includes('project.snapshot.json')) staticRequests.push(r.url()); });
  await page.route('**/api/v1/meta?*', route => route.abort());
  await page.goto('/?project=novel#/story');
  await expect(page.getByRole('heading', { name: '本地服务暂时不可用' })).toBeVisible();
  expect(staticRequests).toEqual([]);
  await page.unroute('**/api/v1/meta?*');
  await page.getByRole('button', { name: '重新连接' }).click();
  await page.locator('.plot-card').first().click();
  await page.locator('.story-reader-page').getByRole('button', { name: /^编辑/ }).click();
  const dialog = page.locator('.editor-dialog').filter({ has: page.locator('.markdown-workspace') });
  const editor = dialog.locator('.cm-content');
  await editor.fill('断线期间仍在编辑的正文');
  await editor.evaluate(node => { window.retainedEditor = node; });
  await page.route('**/api/v1/projects/*/snapshot', route => route.abort());
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(page.locator('.connection-warning')).toBeVisible();
  await expect(editor).toHaveText('断线期间仍在编辑的正文');
  await page.unroute('**/api/v1/projects/*/snapshot');
  await page.getByRole('button', { name: '立即重试' }).click();
  await expect(page.locator('.connection-warning')).toHaveCount(0);
  expect(await editor.evaluate(node => node === window.retainedEditor)).toBe(true);
  const response = page.waitForResponse(r => r.request().method() === 'PATCH' && r.url().includes('/plots/'));
  await dialog.getByRole('button', { name: /保存（/ }).click();
  const result = await (await response).json();
  await expect(dialog.locator('.editor-footer')).toContainText('已保存');
  expect(readBodyFromDisk(result.changed.plots[0].entityId)).toBe('断线期间仍在编辑的正文');
  expect(staticRequests).toEqual([]);
});

test('浏览器存储写入失败显示真实提示，断线不承诺草稿已保存', async ({ page }) => {
  await page.addInitScript(() => { Storage.prototype.setItem = function() { throw new DOMException('Quota exceeded', 'QuotaExceededError'); }; });
  const dialog = await openEditor(page);
  await dialog.locator('.cm-content').fill('仅在页面中的正文');
  await expect(dialog.getByText(/浏览器草稿保存失败/)).toBeVisible();
  await expect(dialog.locator('.editor-footer')).not.toContainText('已暂存在浏览器');
  await page.route('**/api/v1/projects/*/plots/*', route => route.abort());
  await dialog.getByRole('button', { name: /保存（/ }).click();
  await expect(dialog.locator('.editor-footer')).toContainText('请保留当前页面');
  await expect(page.getByText(/草稿已保存/)).toHaveCount(0);
  await page.unroute('**/api/v1/projects/*/plots/*');
  const response = page.waitForResponse(r => r.request().method() === 'PATCH' && r.url().includes('/plots/'));
  await dialog.getByRole('button', { name: /保存（/ }).click();
  const result = await (await response).json();
  await expect(dialog.locator('.editor-footer')).toContainText('已保存');
  expect(readBodyFromDisk(result.changed.plots[0].entityId)).toBe('仅在页面中的正文');
});
