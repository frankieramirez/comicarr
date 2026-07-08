import { expect, test } from "@playwright/test";

test("unauthenticated users are redirected to login", async ({ browser }) => {
  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  });
  const page = await context.newPage();

  await page.goto("/settings");

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText("Sign in")).toBeVisible();

  await context.close();
});

test("JWT cookie session survives a fresh browser context", async ({
  browser,
}, testInfo) => {
  const context = await browser.newContext({
    storageState: testInfo.project.use.storageState,
  });
  const page = await context.newPage();

  await page.goto("/");

  await expect(page.getByText("Dashboard").first()).toBeVisible();

  const session = await page.request.get("/api/auth/check-session");
  expect(session.ok()).toBe(true);
  expect(await session.json()).toEqual(
    expect.objectContaining({ authenticated: true }),
  );

  await context.close();
});

test("logout clears the protected session", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Dashboard").first()).toBeVisible();

  await page.getByRole("button", { name: "Logout" }).click();

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText("Sign in")).toBeVisible();
});
