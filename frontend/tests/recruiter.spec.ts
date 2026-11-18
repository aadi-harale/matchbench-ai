import { expect, test } from "@playwright/test";

test("recruiter can verify an exclusion and recompute a decision", async ({ page }) => {
  const failures: string[] = [];
  page.on("pageerror", error => failures.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Find the jobs you");
  await expect(page.getByRole("heading", { name: "Job explorer" })).toBeVisible();
  await page.getByRole("button", { name: "Inspect a rejected match" }).click();
  await expect(page.getByRole("heading", { name: "Senior AI Search & Backend Engineer" })).toBeVisible();
  await expect(page.getByText("Why it was excluded")).toBeVisible();
  await expect(page.locator(".decision-note")).toContainText("5+ years required");
  await page.getByRole("button", { name: /Agent Infrastructure Intern/ }).click();
  await page.getByRole("button", { name: "What if?" }).click();
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await expect(page.locator(".compare-grid")).toContainText("With hypothetical change");
  await expect(page.locator(".compare-grid")).toContainText("Eligible");
  await page.getByRole("button", { name: "Decision trace" }).click();
  await expect(page.getByText("Open stored run")).toBeVisible();
  await page.getByRole("button", { name: "View benchmark" }).click();
  await expect(page.getByRole("heading", { name: "Ranking benchmark" })).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "Hybrid + personalization" })).toContainText("0.849");
  expect(failures).toEqual([]);
});

test("preference review persists and refreshes ranking", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Job explorer" })).toBeVisible();
  await page.getByRole("navigation").getByRole("button", { name: "Memory" }).click();
  await page.getByRole("button", { name: "No frontend-heavy roles" }).click();
  await page.getByRole("button", { name: "Interpret preference" }).click();
  await expect(page.getByRole("heading", { name: "Proposed change" })).toBeVisible();
  await page.getByRole("button", { name: "Confirm change" }).click();
  await expect(page.getByText("Saved to memory v2", { exact: false })).toBeVisible();
  await page.getByRole("navigation").getByRole("button", { name: "Explorer" }).click();
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText("Memory v1", { exact: false })).toBeVisible();
  await page.reload();
  await page.getByRole("navigation").getByRole("button", { name: "Memory" }).click();
  await expect(page.getByRole("button", { name: "Remove frontend from Excluded roles" })).toBeVisible();
});

for (const width of [320, 768, 1024, 1440]) {
  test(`fits and supports keyboard navigation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    const search = page.getByRole("searchbox");
    await expect(search).toBeVisible();
    await expect(page.locator(".job-row").first()).toBeVisible();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to workspace" })).toBeFocused();
    const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
    expect(fits).toBeTruthy();
    if (process.env.MATCHBENCH_SCREENSHOT_DIR) {
      await page.evaluate(() => { (document.activeElement as HTMLElement).blur(); window.scrollTo(0, 0); });
      await page.screenshot({ path: `${process.env.MATCHBENCH_SCREENSHOT_DIR}/matchbench-${width}.png`, fullPage: true });
    }
  });
}
