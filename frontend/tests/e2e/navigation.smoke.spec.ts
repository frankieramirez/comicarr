import { expect, test } from "@playwright/test";

import { monitorBrowser } from "./support/browser-monitor";

const destinations = [
  { path: "/", label: "Dashboard" },
  { path: "/library", label: "Library" },
  // Chat leaves the app shell; "Back to Comicarr" is present whether or not an
  // AI provider is configured.
  { path: "/chat", label: "Back to Comicarr" },
  { path: "/search", label: "Search" },
  { path: "/wanted", label: "Wanted" },
  { path: "/activity", label: "Activity" },
  { path: "/settings", label: "Settings" },
];

test("protected core navigation renders without API regressions", async ({
  page,
}, testInfo) => {
  const browserMonitor = monitorBrowser(
    page,
    testInfo.project.use.baseURL as string,
  );

  for (const destination of destinations) {
    await page.goto(destination.path);
    await expect(page.getByText(destination.label).first()).toBeVisible();
  }

  await browserMonitor.expectClean();
});

test("SPA fallback serves authenticated deep links", async ({ page }) => {
  await page.goto("/wanted");

  await expect(page).toHaveURL(/\/wanted$/);
  await expect(page.getByText("Wanted").first()).toBeVisible();
  await page.reload();
  await expect(page.getByText("Wanted").first()).toBeVisible();
});
