import { afterEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { NuqsAdapter } from "nuqs/adapters/react-router/v7";
import { act, render, screen } from "../test-utils";
import SeriesTable from "@/components/series/SeriesTable";
import type { Comic } from "@/types";

function series(count: number): Comic[] {
  return Array.from({ length: count }, (_, index) => {
    const number = index + 1;
    return {
      ComicID: String(number),
      ComicName: `Series ${number}`,
      ComicPublisher: "Publisher",
      ComicYear: "2024",
      Status: "Active",
      Have: 0,
      Total: 1,
    } as Comic;
  });
}

/**
 * Record every URL the app commits, so a page param that is stripped and never
 * restored cannot hide behind the final assertion.
 */
function recordUrlWrites(): string[] {
  const urls: string[] = [];
  for (const method of ["pushState", "replaceState"] as const) {
    const original = window.history[method].bind(window.history);
    vi.spyOn(window.history, method).mockImplementation((...args) => {
      original(...args);
      urls.push(window.location.pathname + window.location.search);
    });
  }
  return urls;
}

/** Let nuqs' setTimeout flush and TanStack's queued microtasks drain. */
async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 400));
  });
}

describe("SeriesTable", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the next page when pagination advances", async () => {
    const user = userEvent.setup();
    window.history.pushState({}, "", "/library");

    render(
      <NuqsAdapter>
        <SeriesTable data={series(21)} />
      </NuqsAdapter>,
    );

    await user.click(screen.getByRole("button", { name: "next" }));

    expect(screen.getByText("Series 21")).toBeTruthy();
    expect(screen.queryByText("Series 1")).toBeNull();
  });

  // Regression: a cold load of /library?page=2 used to render page 0 and strip
  // `page` from the URL. Two independent causes, one symptom — the page-clamp
  // effect running while `data` was still empty, and TanStack's auto-reset
  // firing on a microtask after the render-time clamp had already raised
  // `pageIndex` to the requested page. See wayfinder #372 / #381.
  it("keeps a deep-linked page when rows arrive after mount", async () => {
    window.history.pushState({}, "", "/library?page=2");
    const urls = recordUrlWrites();

    const { rerender } = render(
      <NuqsAdapter>
        <SeriesTable data={[]} isLoading />
      </NuqsAdapter>,
    );
    await settle();

    rerender(
      <NuqsAdapter>
        <SeriesTable data={series(63)} />
      </NuqsAdapter>,
    );
    await settle();

    // Page 2 at 20 rows a page is Series 41–60.
    expect(screen.getByText("Series 41")).toBeTruthy();
    expect(screen.queryByText("Series 1")).toBeNull();

    expect(new URLSearchParams(window.location.search).get("page")).toBe("2");
    for (const url of urls) {
      expect(new URLSearchParams(url.split("?")[1] ?? "").get("page")).toBe(
        "2",
      );
    }
  });

  it("clamps a genuinely out-of-range deep link once rows are known", async () => {
    window.history.pushState({}, "", "/library?page=99");

    const { rerender } = render(
      <NuqsAdapter>
        <SeriesTable data={[]} isLoading />
      </NuqsAdapter>,
    );
    await settle();

    rerender(
      <NuqsAdapter>
        <SeriesTable data={series(63)} />
      </NuqsAdapter>,
    );
    await settle();

    // 63 rows at 20 a page is pages 0–3, so the last page is Series 61–63.
    expect(screen.getByText("Series 61")).toBeTruthy();
    expect(new URLSearchParams(window.location.search).get("page")).toBe("3");
  });

  it("still resets to the first page when the row set changes later", async () => {
    window.history.pushState({}, "", "/library?page=2");

    const { rerender } = render(
      <NuqsAdapter>
        <SeriesTable data={series(63)} />
      </NuqsAdapter>,
    );
    await settle();
    expect(screen.getByText("Series 41")).toBeTruthy();

    // e.g. a bulk delete lands and the query refetches.
    rerender(
      <NuqsAdapter>
        <SeriesTable data={series(61)} />
      </NuqsAdapter>,
    );
    await settle();

    expect(screen.getByText("Series 1")).toBeTruthy();
    expect(new URLSearchParams(window.location.search).get("page")).toBeNull();
  });
});
