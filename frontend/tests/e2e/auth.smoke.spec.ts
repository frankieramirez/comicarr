import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

import { ADMIN_PASSWORD, ADMIN_USERNAME } from "./support/comicarr-server.mjs";

const authFile = resolve("tests/e2e/.auth/admin.json");

test("unauthenticated users are redirected to login", async ({ browser }) => {
  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  });
  const page = await context.newPage();

  await page.goto("/settings");

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();

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

  await page.getByRole("button", { name: ADMIN_USERNAME }).click();
  await page.getByRole("menuitem", { name: "Log out", exact: true }).click();

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();

  // Logout rotates the server-side JWT key, so refresh the shared storage
  // state before the next smoke test creates its browser context.
  await page.getByLabel("Username", { exact: true }).fill(ADMIN_USERNAME);
  await page.getByLabel("Password", { exact: true }).fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Dashboard").first()).toBeVisible();
  await page.context().storageState({ path: authFile });
});
