import { expect, test } from "@playwright/test";

import {
  ADMIN_PASSWORD,
  ADMIN_USERNAME,
  startComicarr,
  type ComicarrServer,
} from "./support/comicarr-server.mjs";

test.describe.serial("first-run setup", () => {
  let server: ComicarrServer | null = null;

  test.afterEach(async () => {
    await server?.cleanup();
    server = null;
  });

  test("requires the printed setup token and persists login after restart", async ({
    browser,
  }) => {
    const basePort = Number(process.env.COMICARR_E2E_PORT ?? "18090");
    server = await startComicarr({
      mode: "fresh",
      port: Number(process.env.COMICARR_E2E_FULL_PORT ?? basePort + 1),
      dataDir: process.env.COMICARR_E2E_FULL_DATADIR,
    });
    await server.waitForReady();
    const setupToken = await server.waitForSetupToken();

    const context = await browser.newContext({ baseURL: server.baseURL });
    const page = await context.newPage();

    const blockedDeepLink = await page.goto("/settings");
    expect(blockedDeepLink?.status()).toBe(503);
    await expect(page.getByText("Setup required")).toBeVisible();

    await page.goto("/login");
    await expect(page.getByText("Create admin", { exact: true })).toBeVisible();

    const blockedConfig = await page.request.get("/api/config");
    expect(blockedConfig.status()).toBe(503);

    await page.getByPlaceholder("Choose a username").fill(ADMIN_USERNAME);
    await page.getByPlaceholder("min 8 characters").fill(ADMIN_PASSWORD);
    await page.getByPlaceholder("confirm").fill(ADMIN_PASSWORD);
    await page.getByPlaceholder("from server logs if required").fill("invalid");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByText("Invalid setup token")).toBeVisible();

    await page
      .getByPlaceholder("from server logs if required")
      .fill(setupToken);
    const setupResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/auth/setup") &&
        response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Create account" }).click();
    const setupResult = await setupResponse;
    expect(setupResult.ok()).toBe(true);
    // The new credentials are live at once; the page must not wait for a
    // restart nothing sends (#1352).
    expect((await setupResult.json()).needs_restart).toBe(false);

    await expect(page).toHaveURL(/\/login$/, { timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();

    // The credentials survive a restart.
    await server.restart();
    await page.reload();
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible({
      timeout: 30_000,
    });

    await page.getByLabel("Username", { exact: true }).fill(ADMIN_USERNAME);
    await page.getByLabel("Password", { exact: true }).fill(ADMIN_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page.getByText("Dashboard").first()).toBeVisible();
    await context.close();
  });
});
