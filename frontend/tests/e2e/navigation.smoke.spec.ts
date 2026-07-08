import { expect, test } from "@playwright/test";

import { monitorBrowser } from "./support/browser-monitor";

const destinations = [
  { path: "/", label: "Dashboard" },
  { path: "/library", label: "Library" },
  { path: "/search", label: "Search" },
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
  await page.goto("/settings");

  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByText("Settings").first()).toBeVisible();
});
