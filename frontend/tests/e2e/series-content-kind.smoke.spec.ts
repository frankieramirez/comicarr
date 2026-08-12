import { expect, test } from "@playwright/test";

test("operator can classify a ComicVine series as manga", async ({ page }) => {
  let contentType = "comic";
  let updateBody: unknown;

  await page.route("**/api/series/160294", async (route, request) => {
    if (request.method() !== "GET") {
      await route.fallback();
      return;
    }

    await route.fulfill({
      contentType: "application/json",
      json: {
        comic: {
          ComicID: "160294",
          ComicName: "Solo Leveling",
          ComicYear: "2024",
          ComicPublisher: "Yen Press",
          Status: "Active",
          ContentType: contentType,
        },
        issues: [],
        annuals: [],
      },
    });
  });
  await page.route(
    "**/api/series/160294/content-kind",
    async (route, request) => {
      updateBody = request.postDataJSON();
      contentType = "manga";
      await route.fulfill({
        contentType: "application/json",
        json: { success: true, content_type: "manga" },
      });
    },
  );

  await page.goto("/series/160294");

  await expect(
    page.getByRole("heading", { name: "Solo Leveling" }),
  ).toBeVisible();
  await expect(
    page.getByText(/Metadata still comes from ComicVine/),
  ).toBeVisible();
  await expect(page.getByRole("radio", { name: "Comic" })).toHaveAttribute(
    "aria-checked",
    "true",
  );

  await page.getByRole("radio", { name: "Manga" }).click();

  await expect.poll(() => updateBody).toEqual({ content_type: "manga" });
  await expect(page.getByText("Content kind updated")).toBeVisible();
  await expect(page.getByRole("radio", { name: "Manga" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await expect(page.getByText(/Use manga chapter labels/)).toBeVisible();
});
