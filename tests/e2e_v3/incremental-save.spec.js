const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

async function exported(page) {
  await expect.poll(async () => (await (await page.request.get('/api/v1/projects/novel/exports')).json()).status).toBe('ready');
}
function root() { return fs.readFileSync(path.resolve(__dirname, '../e2e/.runtime-content/v3-project-root.txt'), 'utf8'); }
function articleStats() {
  const index = JSON.parse(fs.readFileSync(path.join(root(), 'export-index.json'), 'utf8'));
  return Object.fromEntries(Object.entries(index.paths).map(([id, files]) => [id, files.map(file => {
    const stat = fs.statSync(path.join(root(), file));
    return { file, inode: stat.ino, mtime: stat.mtimeMs };
  })]));
}
test('改标题不提交正文，改正文不重排章节，无关文章导出文件保持不变', async ({ page }) => {
  await page.goto('/?project=novel#/story');
  const snapshot = await (await page.request.get('/api/v1/projects/novel/snapshot')).json();
  const id = snapshot.plots[0].entityId;
  const originalTitle = snapshot.plots[0].title;
  const meta = await (await page.request.get('/api/v1/meta?project=novel')).json();
  expect((await page.request.post('/api/v1/projects/novel/exports', { headers: { 'X-Story-Teller-Token': meta.mutationToken } })).ok()).toBeTruthy();
  await exported(page);
  await page.locator('.plot-card').first().click();
  await page.locator('.story-reader-page').getByRole('button', { name: /^编辑/ }).click();
  const editor = page.locator('.editor-dialog').filter({ has: page.locator('.markdown-workspace') });
  await editor.getByRole('button', { name: '剧情设置', exact: true }).click();
  const title = editor.getByLabel('剧情标题');
  const before = articleStats();
  const save = async () => {
    const requested = page.waitForRequest(r => r.method() === 'PATCH' && r.url().includes('/plots/'));
    await editor.getByRole('button', { name: /保存（/ }).click();
    const request = await requested;
    await expect(editor.locator('.editor-footer')).toContainText('已保存');
    await exported(page);
    return request.postDataJSON();
  };
  await title.fill(`${originalTitle}增量测试`);
  await editor.getByRole("dialog", { name: "剧情设置", exact: true }).getByRole("button", { name: "关闭剧情设置" }).click();
  const titlePayload = await save();
  expect(titlePayload).not.toHaveProperty('body');
  expect(titlePayload).not.toHaveProperty('chapterNumber');
  expect(titlePayload).not.toHaveProperty('tags');
  const after = articleStats();
  for (const identifier of Object.keys(before).filter(value => value !== id)) expect(after[identifier]).toEqual(before[identifier]);
  await editor.locator('.cm-content').fill('增量保存：只更新当前文章的正文。');
  const bodyPayload = await save();
  expect(bodyPayload.body).toBe('增量保存：只更新当前文章的正文。');
  expect(bodyPayload).not.toHaveProperty('title');
  expect(bodyPayload).not.toHaveProperty('chapterNumber');
  const final = articleStats();
  for (const identifier of Object.keys(after).filter(value => value !== id)) expect(final[identifier]).toEqual(after[identifier]);
  const readback = await (await page.request.get(`/api/v1/projects/novel/entities/${encodeURIComponent(id)}`)).json();
  expect(readback.data.body).toBe(bodyPayload.body);
  const currentFile = final[id][0].file;
  expect(fs.readFileSync(path.join(root(), currentFile), 'utf8')).toContain(bodyPayload.body);
  await expect(page.locator('.story-reader-prose')).toContainText(bodyPayload.body);
  expect(JSON.parse(fs.readFileSync(path.join(root(), 'project.snapshot.json'), 'utf8')).format).toBe('story-teller-export-journal');
});
