import { expect, test, type Page } from "@playwright/test";

const TALL = 24;
// Sub-pixel layout and scrollbar appearance move a pinned header by 1–2px
// on CI (seen up to 2.15px on /wanted and /activity/attention). A real
// unpin scrolls the header tens of pixels.
const PINNED_Y_TOLERANCE_PX = 4;

function recommendation(index: number) {
  return {
    comic_name: `Recommended series ${index}`,
    publisher: "Image",
    reason: "Because you read something nearby in the library.",
    because_of: "Saga",
    comicid: `rec-${index}`,
    comicyear: "2024",
    issues: 12,
    comicimage: null,
  };
}

function attentionGroup(index: number) {
  return {
    group_key: `${index}|postprocess_error`,
    comicid: String(index),
    series_label: `Attention series ${index}`,
    base_reason: "postprocess_error",
    reason_phrase: "post-processing failed",
    member_count: 1,
    newest_updated_at: "2026-08-03 12:00:00",
    oldest_updated_at: "2026-08-03 11:00:00",
    stage: "manual_review",
    available_actions: ["import", "search_again", "stop_wanting"],
    members: [
      {
        release_key: `rk-${index}`,
        issue_label: `Attention series ${index} #1`,
        issueid: `iss-${index}`,
        stage: "manual_review",
        available_actions: ["import", "search_again", "stop_wanting"],
        updated_date: "2026-08-03 12:00:00",
      },
    ],
  };
}

function wantedIssue(index: number) {
  return {
    IssueID: `wanted-${index}`,
    ComicID: "comic-1",
    ComicName: `Wanted series ${index}`,
    Issue_Number: String(index),
    IssueName: `Issue ${index}`,
    IssueDate: "2026-01-01",
    Status: "Wanted",
    DateAdded: "2026-01-01",
  };
}

async function mockTallPages(page: Page) {
  await page.route("**/api/ai/status", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      json: { configured: true, circuit_state: "closed" },
    });
  });
  await page.route("**/api/ai/recommendations", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        recommendations: Array.from({ length: TALL }, (_, i) =>
          recommendation(i + 1),
        ),
      },
    });
  });
  await page.route("**/api/attention**", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    const groups = Array.from({ length: TALL }, (_, i) =>
      attentionGroup(i + 1),
    );
    await route.fulfill({
      contentType: "application/json",
      json: {
        results: groups,
        total: groups.length,
        member_total: groups.length,
        preview_cap: 5,
      },
    });
  });
  await page.route("**/api/wanted**", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    const issues = Array.from({ length: TALL }, (_, i) => wantedIssue(i + 1));
    await route.fulfill({
      contentType: "application/json",
      json: {
        issues,
        pagination: {
          total: issues.length,
          limit: 50,
          offset: 0,
          has_more: false,
        },
      },
    });
  });
}

async function scrollPageBody(page: Page) {
  const shellBody = page.getByTestId("page-shell-body");
  if ((await shellBody.count()) > 0) {
    await shellBody.evaluate((node) => node.scrollTo(0, node.scrollHeight));
    return;
  }
  await page.evaluate(() => {
    const overflowing = [...document.querySelectorAll("main *")].filter(
      (node) => node.scrollHeight > node.clientHeight + 20,
    );
    const scroller = overflowing.at(-1);
    scroller?.scrollTo(0, scroller.scrollHeight);
  });
}

async function assertHeaderPins(page: Page) {
  const header = page.getByTestId("page-header");
  await expect(header).toBeVisible();
  const before = await header.boundingBox();
  expect(before).toBeTruthy();

  await scrollPageBody(page);

  const after = await header.boundingBox();
  expect(after).toBeTruthy();
  expect(Math.abs(after!.y - before!.y)).toBeLessThanOrEqual(
    PINNED_Y_TOLERANCE_PX,
  );

  // Width must match the main column, not the header's own wrapper.
  // Layout's padded `max-w-7xl` shell used to inset both equally, so
  // comparing the header to page-shell passed on the bug.
  const main = page.locator("main");
  const widthBox = await main.boundingBox();
  expect(widthBox).toBeTruthy();
  expect(Math.abs(after!.width - widthBox!.width)).toBeLessThan(2);
}

const routes = [
  { path: "/wanted", title: "Wanted" },
  { path: "/discover", title: "Discover" },
  { path: "/activity/attention", title: "Needs attention" },
];

for (const viewport of [
  { name: "desktop", width: 1280, height: 900 },
  { name: "phone", width: 390, height: 844 },
]) {
  for (const route of routes) {
    test(`PageHeader stays pinned on ${route.path} (${viewport.name})`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await mockTallPages(page);
      await page.goto(route.path);
      await expect(page.getByTestId("page-header")).toContainText(route.title);
      await assertHeaderPins(page);
    });
  }
}
