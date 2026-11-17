import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// WCAG 2.2 A/AA checks on the main pages, in both themes and at phone width
// (#1499). A failure lists each rule and the elements that break it.

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

const pages = [
  { path: "/", ready: "Dashboard" },
  { path: "/library", ready: "Library" },
  { path: "/search", ready: "Search" },
  { path: "/wanted", ready: "Wanted" },
  { path: "/releases", ready: "Releases" },
  { path: "/activity", ready: "Activity" },
  { path: "/settings", ready: "Settings" },
  { path: "/settings?section=downloads", ready: "Settings" },
  { path: "/series/a11y", ready: "Accessible Adventures", heading: true },
];

const layouts = [
  { name: "light", colorScheme: "light", viewport: null },
  { name: "dark", colorScheme: "dark", viewport: null },
  {
    name: "phone",
    colorScheme: "light",
    viewport: { width: 390, height: 844 },
  },
] as const;

const issues = Array.from({ length: 6 }, (_, index) => ({
  IssueID: `a11y-${index + 1}`,
  ComicID: "a11y",
  Issue_Number: String(index + 1),
  IssueName: `Chapter ${index + 1}`,
  IssueDate: "2025-01-01",
  Status: index % 2 ? "Downloaded" : "Wanted",
  displayState: index % 2 ? "Downloaded" : "Wanted",
  acquisitionIntent: "policy",
  fulfillment: index % 2 ? "owned" : "missing",
  missing: index % 2 === 0,
  monitored: true,
  eligible: true,
}));

async function mockSeries(page: Page) {
  await page.route("**/api/series/a11y", async (route, request) => {
    if (request.method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      json: {
        comic: {
          ComicID: "a11y",
          ComicName: "Accessible Adventures",
          ComicYear: "2025",
          ComicPublisher: "Example Press",
          Status: "Active",
          Description: "A series used to check row actions.",
        },
        issues,
        annuals: [],
        summary: { total: issues.length, owned: 3, missing: 3 },
      },
    });
  });
}

for (const layout of layouts) {
  for (const target of pages) {
    test(`${target.path} meets WCAG A/AA (${layout.name})`, async ({
      page,
    }) => {
      await page.emulateMedia({ colorScheme: layout.colorScheme });
      if (layout.viewport) await page.setViewportSize(layout.viewport);
      await mockSeries(page);
      await page.goto(target.path);
      const ready =
        "heading" in target
          ? page.getByRole("heading", { name: target.ready })
          : page.getByText(target.ready).first();
      await expect(ready).toBeVisible();
      await page.waitForLoadState("networkidle");

      const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
      const violations = results.violations.map((violation) => ({
        rule: violation.id,
        impact: violation.impact,
        nodes: violation.nodes.map(
          (node) => `${node.target.join(" ")} ${node.html.slice(0, 160)}`,
        ),
      }));
      expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
    });
  }
}
