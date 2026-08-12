import { expect, test } from "@playwright/test";

const frontendMutationHeaders = {
  "X-Requested-With": "ComicarrFrontend",
};

test("authenticated acquisition diagnostics expose a safe operator contract", async ({
  page,
}) => {
  await page.goto("/settings");

  const [healthResponse, versionResponse, progressResponse] = await Promise.all(
    [
      page.request.get("/api/search/health"),
      page.request.get("/api/system/version"),
      page.request.get("/api/system/migration/progress"),
    ],
  );

  expect(healthResponse.ok()).toBe(true);
  expect(versionResponse.ok()).toBe(true);
  expect(progressResponse.ok()).toBe(true);

  const health = await healthResponse.json();
  expect(health).toEqual(
    expect.objectContaining({
      routes: expect.any(Object),
      viable_route: expect.any(Boolean),
      maintenance: expect.objectContaining({
        blocked: expect.any(Boolean),
        active_leases: expect.any(Number),
      }),
    }),
  );

  const version = await versionResponse.json();
  expect(version.build).toEqual(
    expect.objectContaining({
      id: expect.any(String),
      verified: expect.any(Boolean),
    }),
  );

  const progress = await progressResponse.json();
  expect(progress.reconciliation).toEqual(
    expect.objectContaining({ state: expect.any(String) }),
  );
});

test("acquisition mutations require the session-bound confirmation inputs", async ({
  page,
}) => {
  await page.goto("/settings");

  // This deliberately fails before a series lookup or any durable mutation.
  // It keeps the smoke suite safe on the minimal seeded library while proving
  // that the browser cannot bypass the preview-token/fingerprint boundary.
  const searchConfirm = await page.request.post(
    "/api/series/not-a-real-series/search-missing",
    {
      data: { confirm: true },
      headers: frontendMutationHeaders,
    },
  );
  expect(searchConfirm.status()).toBe(400);
  expect(await searchConfirm.json()).toEqual(
    expect.objectContaining({
      success: false,
      error: expect.stringContaining("preview token"),
    }),
  );

  // The operator-only recovery endpoints must reject incomplete requests
  // instead of creating a repair, releasing a gate, or resuming acquisition.
  const [repairPreview, reconciliationReady, maintenanceAbort] =
    await Promise.all([
      page.request.post("/api/system/acquisition/repair/preview", {
        data: {},
        headers: frontendMutationHeaders,
      }),
      page.request.post("/api/system/acquisition/reconciliation/ready", {
        data: {},
        headers: frontendMutationHeaders,
      }),
      page.request.post("/api/system/acquisition/maintenance/abort", {
        data: {},
        headers: frontendMutationHeaders,
      }),
    ]);

  expect(repairPreview.status()).toBe(400);
  expect(await repairPreview.json()).toEqual(
    expect.objectContaining({
      success: false,
      error: "series_id is required",
    }),
  );

  expect(reconciliationReady.status()).toBe(400);
  expect(await reconciliationReady.json()).toEqual(
    expect.objectContaining({
      success: false,
      error: expect.stringContaining("reconciliation release reason"),
    }),
  );

  expect(maintenanceAbort.status()).toBe(400);
  expect(await maintenanceAbort.json()).toEqual(
    expect.objectContaining({
      success: false,
      error: expect.stringContaining("maintenance abort reason"),
    }),
  );
});

test("wanted releases support an explainable interactive grab", async ({
  page,
}) => {
  let grabBody: unknown;

  await page.route("**/api/upcoming**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: [
        {
          IssueID: "issue-e2e",
          ComicID: "comic-e2e",
          ComicName: "Absolute Batman",
          IssueNumber: "19",
          Issue_Number: "19",
          IssueDate: "2026-08-12",
          Status: "Wanted",
        },
      ],
    });
  });
  await page.route("**/api/search/interactive**", async (route, request) => {
    const path = new URL(request.url()).pathname;

    if (request.method() === "POST" && path.endsWith("/interactive")) {
      await route.fulfill({
        contentType: "application/json",
        status: 202,
        json: {
          session_id: "session-e2e",
          state: "queued",
          candidates: [],
          progress: {
            provider_total: 1,
            provider_completed: 0,
            current_provider: null,
          },
          provider_failures: [],
        },
      });
      return;
    }

    if (request.method() === "GET" && path.endsWith("/session-e2e")) {
      await route.fulfill({
        contentType: "application/json",
        json: {
          session_id: "session-e2e",
          entity_type: "issue",
          entity_id: "issue-e2e",
          series_id: "comic-e2e",
          state: "complete",
          candidate_count: 1,
          progress: {
            provider_total: 1,
            provider_completed: 1,
            current_provider: null,
          },
          provider_failures: [],
          created_at: "2026-08-12T04:00:00Z",
          expires_at: "2026-08-12T04:10:00Z",
          candidates: [
            {
              candidate_id: "candidate-e2e",
              state: "available",
              candidate: {
                title: "Absolute Batman 019 (2026) (Digital)",
                provider: "Indexer",
                source_kind: "usenet",
                published_at: "2026-08-12T04:00:00Z",
                size_bytes: 98000000,
                pack: false,
                metrics: { grabs: 8 },
              },
              verdict: {
                status: "accepted",
                accepted: true,
                overrideable: false,
                reason_code: "accepted.issue",
                reasons: [
                  {
                    code: "accepted.issue",
                    message: "Issue, year, and volume match",
                  },
                ],
                match_kind: "standard",
              },
            },
          ],
        },
      });
      return;
    }

    if (request.method() === "POST" && path.endsWith("/grab")) {
      grabBody = request.postDataJSON();
      await route.fulfill({
        contentType: "application/json",
        json: {
          success: true,
          status: "submitted",
          candidate_id: "candidate-e2e",
        },
      });
      return;
    }

    await route.fallback();
  });

  await page.goto("/releases");
  await page.getByRole("button", { name: "Review releases" }).click();

  await expect(
    page.getByRole("heading", { name: "Review releases" }),
  ).toBeVisible();
  await expect(
    page.getByText("Absolute Batman 019 (2026) (Digital)"),
  ).toBeVisible();
  await expect(page.getByText("Issue, year, and volume match")).toBeVisible();

  await page.getByRole("button", { name: "Review grab" }).click();
  await page.getByRole("button", { name: "Confirm grab" }).click();

  await expect.poll(() => grabBody).toEqual({ override: false });
  await expect(page.getByText("Grab started")).toBeVisible();
});
