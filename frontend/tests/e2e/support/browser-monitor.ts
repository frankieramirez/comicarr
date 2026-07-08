import { expect, type Page } from "@playwright/test";

const ignoredApiFailures = ["/api/events/stream"];

export function monitorBrowser(page: Page, baseURL?: string) {
  const issues: string[] = [];
  const expectedOrigin = baseURL ? new URL(baseURL).origin : null;

  const isExpectedApiRequest = (requestUrl: URL) => {
    if (!requestUrl.pathname.startsWith("/api/")) {
      return false;
    }
    if (expectedOrigin) {
      return requestUrl.origin === expectedOrigin;
    }

    const currentUrl = page.url();
    return (
      currentUrl !== "about:blank" &&
      requestUrl.origin === new URL(currentUrl).origin
    );
  };

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
      isExpectedApiRequest(requestUrl) &&
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
      isExpectedApiRequest(requestUrl) &&
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
