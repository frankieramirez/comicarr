import { expect, test } from "@playwright/test";

test("shell defers optional requests and chunks until the drawer opens", async ({
  page,
}) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.route("**/api/ai/status", (route) =>
    route.fulfill({ json: { configured: true } }),
  );
  await page.route("**/api/ai/activity?*", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("**/api/system/version", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      json: { ...(await response.json()), pending_whats_new: null },
    });
  });

  for (const path of ["/", "/library", "/settings"]) {
    await page.goto(path);
    await expect(
      page.getByRole("button", { name: "AI Activity" }),
    ).toBeVisible();
    expect(
      requests.filter((url) => url.includes("/api/ai/chat/threads")),
    ).toEqual([]);
    expect(requests.filter((url) => url.includes("/api/ai/activity?"))).toEqual(
      [],
    );
    expect(
      requests.filter((url) =>
        /\/assets\/(ActivityFeedDrawer|WhatsNewModal)-/.test(url),
      ),
    ).toEqual([]);
  }

  await page.getByRole("button", { name: "AI Activity" }).click();
  const drawer = page.getByRole("dialog", { name: "AI Activity" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText("No AI activity yet")).toBeVisible();
  expect(
    requests.filter((url) => url.includes("/api/ai/activity?")),
  ).toHaveLength(1);
  expect(
    requests.some((url) => /\/assets\/ActivityFeedDrawer-/.test(url)),
  ).toBe(true);
  await drawer.getByRole("button", { name: "Close" }).click();
  await expect(drawer).toBeHidden();
  await page.getByRole("button", { name: "AI Activity" }).click();
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText("No AI activity yet")).toBeVisible();
  expect(
    requests.filter((url) => url.includes("/api/ai/activity?")),
  ).toHaveLength(1);
});

test("pending upgrade still loads and dismisses What's New", async ({
  page,
}) => {
  let pending = true;
  await page.route("**/api/system/version", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      json: {
        ...(await response.json()),
        pending_whats_new: pending ? { from: "0.38.6", to: "0.38.7" } : null,
      },
    });
  });
  await page.route("**/api/system/release-notes?*", (route) =>
    route.fulfill({ json: { sections: [] } }),
  );
  await page.route("**/api/system/whats-new/dismiss", (route) => {
    pending = false;
    return route.fulfill({ json: { success: true } });
  });

  await page.goto("/");
  const modal = page.getByRole("dialog");
  await expect(modal.getByText("Comicarr updated")).toBeVisible();
  await expect(
    modal.getByText("No release notes recorded for this upgrade."),
  ).toBeVisible();
  await modal.getByRole("button", { name: "Got it" }).click();
  await expect(modal).toBeHidden();
  expect(pending).toBe(false);
});
