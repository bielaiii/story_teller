const { test, expect } = require("@playwright/test");

test("常用筛选、搜索和时间线操作不会闪烁整个页面", async ({ page }) => {
  await page.goto("/?project=novel");

  await page.locator('[data-view="story"]').click();
  const storyPage = page.locator('[data-page="story"]');
  const storyTags = page.locator("#tagFilter");
  await storyPage.evaluate((element) => { element.dataset.surfaceProbe = "story"; });
  await storyTags.evaluate((element) => { element.dataset.surfaceProbe = "tags"; });
  await page.locator('.chapter-btn[data-chapter="act1"]').click();
  await expect(storyPage).toHaveAttribute("data-surface-probe", "story");
  await expect(storyTags).toHaveAttribute("data-surface-probe", "tags");
  await expect(page.locator("#plotStrip .plot-card").first()).toHaveClass(/is-filter-result/);

  const nextPage = page.locator("#plotPagination").getByRole("button", { name: "下一页" });
  await nextPage.click();
  await expect(storyPage).toHaveAttribute("data-surface-probe", "story");
  await expect(page.locator("#plotStrip .plot-card").first()).toHaveClass(/is-filter-result/);

  await page.locator('[data-view="characters"]').click();
  const characterPage = page.locator('[data-page="characters"]');
  const characterFilters = page.locator("#characterCategoryFilter");
  const characterDetail = page.locator("#characterDetail");
  await characterPage.evaluate((element) => { element.dataset.surfaceProbe = "characters"; });
  await characterFilters.evaluate((element) => { element.dataset.surfaceProbe = "character-filters"; });
  await characterDetail.evaluate((element) => { element.dataset.surfaceProbe = "character-detail"; });
  await page.locator("#characterSearch").fill("沈");
  await expect(characterPage).toHaveAttribute("data-surface-probe", "characters");
  await expect(characterFilters).toHaveAttribute("data-surface-probe", "character-filters");
  await expect(characterDetail).toHaveAttribute("data-surface-probe", "character-detail");

  await page.locator('[data-view="places"]').click();
  const placePage = page.locator('[data-page="places"]');
  const entryTypes = page.locator("#entryTypeFilter");
  const placeDetail = page.locator("#placeDetail");
  await placePage.evaluate((element) => { element.dataset.surfaceProbe = "places"; });
  await entryTypes.evaluate((element) => { element.dataset.surfaceProbe = "entry-types"; });
  await placeDetail.evaluate((element) => { element.dataset.surfaceProbe = "place-detail"; });
  await page.locator("#placeSearch").fill("旧港");
  await expect(placePage).toHaveAttribute("data-surface-probe", "places");
  await expect(entryTypes).toHaveAttribute("data-surface-probe", "entry-types");
  await expect(placeDetail).toHaveAttribute("data-surface-probe", "place-detail");

  await page.locator('[data-view="timeline"]').click();
  const timelinePage = page.locator('[data-page="timeline"]');
  await expect(page.locator(".timeline-board")).toBeVisible();
  await timelinePage.evaluate((element) => {
    element.dataset.surfaceProbe = "timeline";
    window.__timelineDisplayedLoadingDuringDirectionChange = false;
    const observer = new MutationObserver(() => {
      if (element.querySelector(".timeline-loading")) window.__timelineDisplayedLoadingDuringDirectionChange = true;
    });
    observer.observe(element, { childList: true, subtree: true });
    window.__timelineLoadingObserver = observer;
  });
  await page.locator("#timelineDirectionBtn").click();
  await expect(page.locator("#timelineDirectionBtn")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".timeline-board")).toBeVisible();
  await expect(timelinePage).toHaveAttribute("data-surface-probe", "timeline");
  expect(await page.evaluate(() => window.__timelineDisplayedLoadingDuringDirectionChange)).toBe(false);
  await page.evaluate(() => window.__timelineLoadingObserver?.disconnect());
});
