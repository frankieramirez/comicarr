import { writeFile, unlink } from "node:fs/promises";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

test("Logs searches a retained file, copies whole redacted records, and recovers a missing file", async ({
  page,
  context,
}) => {
  test.skip(
    Boolean(process.env.COMICARR_E2E_BASE_URL),
    "Requires the managed local fixture directory",
  );
  const config = await (await page.request.get("/api/config")).json();
  const path = join(config.log_dir, "comicarr.log.2");
  const secret = "e2e-provider-key-1015";
  const contents = Array.from({ length: 205 }, (_, index) => {
    const header =
      index % 2
        ? "11-Aug-2026 14:28:01 - ERROR :: MainThread : search.py:search:12 : failed"
        : "11-Aug-2026 14:28:01 - ERROR :: comicarr.search.12 : MainThread : failed";
    return `${header} ${index}\nTraceback (most recent call last):\n  RuntimeError: needle https://indexer.test/?apikey=${secret}\n`;
  }).join("");
  await writeFile(path, contents);
  try {
    await page.goto("/settings?section=logs");
    await expect(page.getByRole("status")).toContainText("comicarr.log");
    await page.getByLabel("Log file").click();
    await page.getByRole("option", { name: /comicarr.log.2/ }).click();
    await page.getByLabel("Search text").fill("needle");
    await page.getByLabel("Component", { exact: true }).fill("search");
    await page.getByLabel("Filter log lines").click();
    await page.getByRole("option", { name: "Errors only" }).click();
    await page
      .getByRole("form", { name: "Search log records" })
      .getByRole("button", { name: "Search", exact: true })
      .click();
    await expect(page.getByRole("status")).toContainText(
      "615 lines scanned · 205 matched · 200 returned",
    );
    await expect(page.getByRole("status")).toContainText("Truncated");
    await expect(page.locator("pre")).toContainText(
      "Traceback (most recent call last):",
    );
    await expect(page.locator("pre")).toContainText("apikey=[redacted]");
    await expect(page.locator("pre")).not.toContainText(secret);
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.getByRole("button", { name: "Copy", exact: true }).click();
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    expect(copied).toBe(await page.locator("pre").textContent());
    expect(copied).not.toContain(secret);
    if (process.env.COMICARR_LOG_SEARCH_EVIDENCE) {
      for (const theme of ["light", "dark"]) {
        await page.evaluate(
          (value) =>
            document.documentElement.classList.toggle("dark", value === "dark"),
          theme,
        );
        await page.screenshot({
          path: join(
            process.env.COMICARR_LOG_SEARCH_EVIDENCE,
            `log-search-${theme}.png`,
          ),
          fullPage: true,
        });
      }
      await page.setViewportSize({ width: 390, height: 844 });
      await page.screenshot({
        path: join(
          process.env.COMICARR_LOG_SEARCH_EVIDENCE,
          "log-search-mobile.png",
        ),
        fullPage: true,
      });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(390);
    }
    await unlink(path);
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect(page.getByText(/The log file no longer exists/)).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Copy", exact: true }),
    ).toBeDisabled();
    await writeFile(path, contents);
    await page
      .getByRole("button", { name: "Refresh files and results" })
      .click();
    await expect(page.getByRole("status")).toContainText(
      "205 matched · 200 returned",
    );
  } finally {
    await unlink(path).catch(() => {});
  }
});
