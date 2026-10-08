import { expect, test, type Locator, type Page } from "@playwright/test";

async function assertTitleTakesHalfTheRow(row: Locator) {
  const title = row.locator("[data-grid-title]");
  const rowBox = await row.boundingBox();
  const titleBox = await title.boundingBox();
  expect(rowBox).toBeTruthy();
  expect(titleBox).toBeTruthy();
  expect(titleBox!.width).toBeGreaterThanOrEqual(rowBox!.width * 0.5);
}

async function assertNoHorizontalScroll(container: Locator) {
  const overflowed = await container.evaluate(
    (node) => node.scrollWidth > node.clientWidth + 1,
  );
  expect(overflowed).toBe(false);
}

test("search list and weekly pull keep the title readable on a phone", async ({
  page,
}) => {
  await page.route("**/api/search/comics", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      json: {
        results: [
          {
            comicid: "12345",
            name: "Amazing Spider-Man",
            comicyear: "2022",
            issues: 75,
            publisher: "Marvel",
          },
        ],
        pagination: { total: 1, limit: 20, offset: 0, returned: 1 },
      },
    });
  });
  await page.route("**/api/weekly", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: [
        {
          COMIC: "Absolute Batman",
          ISSUE: "19",
          PUBLISHER: "DC Comics",
          SHIPDATE: "2026-08-12",
          STATUS: "Wanted",
          ComicID: "comic-1",
        },
      ],
    });
  });
  await page.route("**/api/config", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    const response = await route.fetch();
    const json = (await response.json()) as Record<string, unknown>;
    await route.fulfill({
      contentType: "application/json",
      json: { ...json, comicvine_api_set: true, comicvine_enabled: true },
    });
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/search?q=spider&type=comic&view=list");
  const searchRow = page.getByTestId("search-result-row").first();
  await expect(searchRow).toBeVisible();
  await expect(searchRow.getByTestId("phone-row-id")).toBeVisible();
  await expect(searchRow.getByTestId("phone-row-id")).toContainText("2022");
  await expect(searchRow.getByTestId("phone-row-id")).toContainText("Marvel");
  await assertTitleTakesHalfTheRow(searchRow);
  await assertNoHorizontalScroll(page.getByTestId("search-results-table"));

  await page.goto("/releases?view=all");
  const weeklyRow = page.getByTestId("weekly-release-row").first();
  await expect(weeklyRow).toBeVisible();
  await expect(weeklyRow.getByTestId("phone-row-id")).toBeVisible();
  await expect(weeklyRow.getByTestId("phone-row-id")).toContainText("#19");
  await assertTitleTakesHalfTheRow(weeklyRow);
  await assertNoHorizontalScroll(page.getByTestId("weekly-releases-table"));

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/search?q=spider&type=comic&view=list");
  await expect(page.getByText("Marvel")).toBeVisible();
  await expect(page.getByText("2022")).toBeVisible();
  await page.goto("/releases?view=all");
  await expect(page.getByText("DC Comics")).toBeVisible();
  await expect(page.getByText("#19")).toBeVisible();
});

test("series issue status stays in the phone viewport", async ({
  page,
}: {
  page: Page;
}) => {
  await page.route("**/api/series/991", async (route, request) => {
    if (request.method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      json: {
        comic: {
          ComicID: "991",
          ComicName: "Ultimate Wolverine",
          ComicYear: "2025",
          ComicPublisher: "Marvel",
          Status: "Active",
          Description: "Logan is the Ultimate Universe's deadliest assassin.",
        },
        issues: [
          {
            IssueID: "scroll-1",
            ComicID: "991",
            Issue_Number: "1",
            IssueName: "Scroll issue 1",
            IssueDate: "2025-01-01",
            Status: "Wanted",
            displayState: "Wanted",
            acquisitionIntent: "policy",
            fulfillment: "missing",
            missing: true,
            monitored: true,
            eligible: true,
          },
        ],
        annuals: [
          {
            IssueID: "scroll-annual",
            ComicID: "991",
            Issue_Number: "1",
            IssueName: "Annual 1",
            IssueDate: "2025-06-01",
            Status: "Wanted",
            displayState: "Wanted",
            annual: true,
            acquisitionIntent: "policy",
            fulfillment: "missing",
            missing: true,
            monitored: true,
            eligible: true,
          },
        ],
        summary: { total: 1, owned: 0, missing: 1 },
      },
    });
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/series/991");
  await expect(
    page.getByRole("heading", { name: "Ultimate Wolverine" }),
  ).toBeVisible();
  const status = page
    .getByTestId("series-issue-list")
    .locator("[data-grid-status]")
    .first();
  await expect(status).toBeVisible();
  // Phone stacks the hero above the list (#948); the AC is no *horizontal*
  // scroll to reach status, not that the first row is above the fold.
  await status.scrollIntoViewIfNeeded();
  await expect(status).toBeInViewport();
  const box = await status.boundingBox();
  expect(box).toBeTruthy();
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  const annualBadge = page
    .getByTestId("series-issue-list")
    .getByTestId("phone-row-id");
  await annualBadge.scrollIntoViewIfNeeded();
  await expect(annualBadge).toBeVisible();
  await expect(annualBadge).toContainText("Annual");
  await assertNoHorizontalScroll(page.getByTestId("series-issue-list"));
});
