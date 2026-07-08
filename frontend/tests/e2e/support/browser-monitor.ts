import { expect, type Page } from "@playwright/test";

const ignoredApiFailures = ["/api/events/stream"];

export function monitorBrowser(page: Page) {
  const issues: string[] = [];

  page.on("pageerror", (error) => {
    issues.push(`pageerror: ${error.message}`);
  });

  page.on("requestfailed", (request) => {
    const requestUrl = new URL(request.url());
    const failure = request.failure()?.errorText;
    if (failure === "net::ERR_ABORTED") {
      return;
    }

    if (
      requestUrl.origin === new URL(page.url()).origin &&
      requestUrl.pathname.startsWith("/api/") &&
      !ignoredApiFailures.includes(requestUrl.pathname)
    ) {
      issues.push(
        `requestfailed: ${request.method()} ${requestUrl.pathname} ${failure}`,
      );
    }
  });

  page.on("response", (response) => {
    const requestUrl = new URL(response.url());
    if (
      requestUrl.origin === new URL(page.url()).origin &&
      requestUrl.pathname.startsWith("/api/") &&
      response.status() >= 500 &&
      !ignoredApiFailures.includes(requestUrl.pathname)
    ) {
      issues.push(
        `api ${response.status()}: ${response.request().method()} ${requestUrl.pathname}`,
      );
    }
  });

  return {
    async expectClean() {
      expect(issues).toEqual([]);
    },
  };
}
