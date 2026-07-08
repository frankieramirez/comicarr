import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { expect, test as setup } from "@playwright/test";

import { ADMIN_PASSWORD, ADMIN_USERNAME } from "./support/comicarr-server.mjs";

const authFile = resolve("tests/e2e/.auth/admin.json");

setup("authenticate seeded admin", async ({ page }) => {
  mkdirSync(dirname(authFile), { recursive: true });

  await page.goto("/login");
  await expect(page.getByText("Sign in")).toBeVisible();

  await page.getByPlaceholder("username").fill(ADMIN_USERNAME);
  await page.getByPlaceholder("password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByText("Dashboard").first()).toBeVisible();

  const cookies = await page.context().cookies();
  expect(cookies.some((cookie) => cookie.name === "comicarr_session")).toBe(
    true,
  );

  await page.context().storageState({ path: authFile });
});
