import { defineConfig, devices } from "@playwright/test";

const e2ePort = Number(process.env.COMICARR_E2E_PORT ?? "18090");
const baseURL =
  process.env.COMICARR_E2E_BASE_URL ?? `http://127.0.0.1:${e2ePort}`;

function selectedProjects() {
  const projects: string[] = [];
  for (let index = 0; index < process.argv.length; index += 1) {
    const arg = process.argv[index];
    if (arg === "--project" && process.argv[index + 1]) {
      projects.push(process.argv[index + 1]);
    } else if (arg.startsWith("--project=")) {
      projects.push(arg.split("=", 2)[1]);
    }
  }
  return projects;
}

const selectedProjectNames = selectedProjects();
const fullOnly =
  selectedProjectNames.length > 0 &&
  selectedProjectNames.every((project) => project === "chromium-full");
const shouldStartServer = !process.env.COMICARR_E2E_BASE_URL && !fullOnly;

export default defineConfig({
  testDir: "./tests/e2e",
  outputDir: "./test-results/e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI
    ? [
        ["list"],
        ["github"],
        ["html", { outputFolder: "playwright-report", open: "never" }],
        ["junit", { outputFile: "test-results/e2e/junit.xml" }],
      ]
    : [
        ["list"],
        ["html", { outputFolder: "playwright-report", open: "never" }],
      ],
  use: {
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "on-first-retry",
  },
  projects: [
    {
      name: "setup",
      testMatch: /.*\.setup\.ts/,
    },
    {
      name: "chromium-smoke",
      testMatch: /.*\.smoke\.spec\.ts/,
      dependencies: ["setup"],
      use: {
        ...devices["Desktop Chrome"],
        storageState: "./tests/e2e/.auth/admin.json",
      },
    },
    {
      name: "chromium-full",
      testMatch: /.*\.full\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
      },
    },
  ],
  webServer: shouldStartServer
    ? {
        command: "node tests/e2e/support/comicarr-server.mjs seeded",
        url: `${baseURL}/api/health`,
        timeout: 120_000,
        reuseExistingServer: false,
        env: {
          ...process.env,
          COMICARR_E2E_PORT: String(e2ePort),
        },
      }
    : undefined,
});
