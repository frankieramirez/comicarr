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

async function openSeries(page: Page, tallHeader = false) {
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
          Description: tallHeader
            ? "A long catalog description with publication history and issue details. ".repeat(
                100,
              )
            : "Logan is the Ultimate Universe's deadliest assassin.",
        },
        searchProviders: tallHeader
          ? {
              available: ["GetComics", "NZBGeek", "Prowlarr", "Torznab"],
              override: {
                order: ["Prowlarr", "GetComics"],
                exclude: ["Torznab"],
              },
            }
          : undefined,
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
  { name: "short desktop", width: 1280, height: 600 },
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
}, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 1024 });
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
  await testInfo.attach("short-header-split", {
    body: await page.screenshot(),
    contentType: "image/png",
  });
});

for (const viewport of [
  { width: 1280, height: 1024 },
  { width: 1024, height: 900 },
]) {
  test(`tall series header lets the page scroll the issues into view (${viewport.width}x${viewport.height})`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize(viewport);
    await openSeries(page, true);
    const body = page.getByTestId("series-body-scroll");
    const list = page.getByTestId("series-issue-list");
    await expect
      .poll(() => body.evaluate((node) => getComputedStyle(node).overflowY))
      .toBe("auto");
    await expect
      .poll(() => list.evaluate((node) => node.clientHeight))
      .toBeGreaterThan(400);
    await page
      .getByText("Scroll issue 1", { exact: true })
      .evaluate((node) => node.scrollIntoView({ block: "start" }));
    await expect(
      page.getByText("Scroll issue 8", { exact: true }),
    ).toBeInViewport();
    await testInfo.attach(`tall-header-${viewport.width}x${viewport.height}`, {
      body: await page.screenshot(),
      contentType: "image/png",
    });
    await body.evaluate((node) => node.scrollTo(0, node.scrollHeight));
    await expect(
      page.getByText(`Scroll issue ${ISSUE_COUNT}`, { exact: true }),
    ).toBeInViewport();
    await expect.poll(() => list.evaluate((node) => node.scrollTop)).toBe(0);
  });
}

test("series layout rechecks available issue space after viewport resize", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 1400 });
  await openSeries(page, true);
  const body = page.getByTestId("series-body-scroll");
  await expect
    .poll(() => body.evaluate((node) => getComputedStyle(node).overflowY))
    .toBe("hidden");
  await page.setViewportSize({ width: 1280, height: 1024 });
  await expect
    .poll(() => body.evaluate((node) => getComputedStyle(node).overflowY))
    .toBe("auto");
  await page.setViewportSize({ width: 1280, height: 1400 });
  await expect
    .poll(() => body.evaluate((node) => getComputedStyle(node).overflowY))
    .toBe("hidden");
});

test("selection toolbar rechecks issue space when it appears and disappears", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 1400 });
  await openSeries(page);
  const body = page.getByTestId("series-body-scroll");
  const list = page.getByTestId("series-issue-list");
  await expect
    .poll(() => body.evaluate((node) => getComputedStyle(node).overflowY))
    .toBe("hidden");
  const issueHeight = await list.evaluate((node) => node.clientHeight);
  await page.setViewportSize({ width: 1280, height: 1400 - issueHeight + 410 });
  await expect
    .poll(() => body.evaluate((node) => getComputedStyle(node).overflowY))
    .toBe("hidden");
  await page
    .getByRole("checkbox", { name: "Select Scroll issue 1", exact: true })
    .click();
  await expect(page.getByTestId("issue-selection-count")).toHaveText(
    "1 selected",
  );
  await expect
    .poll(() => body.evaluate((node) => getComputedStyle(node).overflowY))
    .toBe("auto");
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await expect
    .poll(() => body.evaluate((node) => getComputedStyle(node).overflowY))
    .toBe("hidden");
});
