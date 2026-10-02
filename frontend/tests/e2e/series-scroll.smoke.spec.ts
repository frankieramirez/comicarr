import { expect, test, type Page } from "@playwright/test";

const ISSUE_COUNT = 30;

const issues = Array.from({ length: ISSUE_COUNT }, (_, index) => {
  const number = index + 1;
  return {
    IssueID: `scroll-${number}`,
    ComicID: "991",
    Issue_Number: String(number),
    IssueName: `Scroll issue ${number}`,
    IssueDate: "2025-01-01",
    Status: "Wanted",
    displayState: "Wanted",
    acquisitionIntent: "policy",
    fulfillment: "missing",
    missing: true,
    monitored: true,
    eligible: true,
  };
});

async function openSeries(page: Page) {
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
        issues,
        annuals: [],
        summary: { total: ISSUE_COUNT, owned: 0, missing: ISSUE_COUNT },
      },
    });
  });

  await page.goto("/series/991");
  await expect(
    page.getByRole("heading", { name: "Ultimate Wolverine" }),
  ).toBeVisible();
}

// #947: a stacked hero must never leave the issue list at zero height.
for (const viewport of [
  { name: "phone portrait", width: 390, height: 844 },
  { name: "phone landscape", width: 844, height: 390 },
]) {
  test(`series issue list is reachable by scrolling (${viewport.name})`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await openSeries(page);

    const lastIssue = page.getByText(`Scroll issue ${ISSUE_COUNT}`, {
      exact: true,
    });
    await expect(lastIssue).not.toBeInViewport();

    await page
      .getByTestId("series-body-scroll")
      .evaluate((node) => node.scrollTo(0, node.scrollHeight));

    await expect(lastIssue).toBeInViewport();
  });
}

test("series hero stays put while the issue list scrolls (desktop)", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await openSeries(page);

  const heading = page.getByRole("heading", { name: "Ultimate Wolverine" });
  const lastIssue = page.getByText(`Scroll issue ${ISSUE_COUNT}`, {
    exact: true,
  });
  await expect(lastIssue).not.toBeInViewport();

  await page
    .getByTestId("series-issue-list")
    .evaluate((node) => node.scrollTo(0, node.scrollHeight));

  await expect(lastIssue).toBeInViewport();
  await expect(heading).toBeInViewport();
});
