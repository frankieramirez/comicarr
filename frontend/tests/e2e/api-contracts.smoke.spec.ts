import { expect, test } from "@playwright/test";

test("authenticated config API exposes only safe config", async ({ page }) => {
  await page.goto("/");

  const response = await page.request.get("/api/config");
  expect(response.ok()).toBe(true);

  const config = await response.json();
  expect(config).toEqual(
    expect.objectContaining({
      http_username: "e2e-admin",
      authentication: 2,
    }),
  );
  expect(config.http_password).toBeUndefined();
  expect(config.api_key).toBeUndefined();
});

test("CSRF middleware rejects state changes without frontend header", async ({
  page,
}) => {
  await page.goto("/");

  const response = await page.request.put("/api/config", {
    data: { LAUNCH_BROWSER: false },
  });

  expect(response.status()).toBe(403);
  expect(await response.json()).toEqual(
    expect.objectContaining({ detail: "CSRF validation failed" }),
  );
});

test("authenticated frontend-header config write succeeds", async ({
  page,
}) => {
  await page.goto("/");

  const response = await page.request.put("/api/config", {
    data: { LAUNCH_BROWSER: false },
    headers: { "X-Requested-With": "ComicarrFrontend" },
  });

  expect(response.ok()).toBe(true);
  expect(await response.json()).toEqual(
    expect.objectContaining({ success: true }),
  );
});
