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

  it("loads list covers from the art proxy, never a MangaDex hotlink", () => {
    window.history.pushState({}, "", "/library");
    const comics: Comic[] = [
      {
        ComicID: "md-onepiece",
        ComicName: "One Piece",
        ComicPublisher: "Shueisha",
        ComicYear: "1997",
        Status: "Active",
        Have: 0,
        Total: 1,
        ComicImage: "https://uploads.mangadex.org/covers/uuid/cover.jpg",
      },
      {
        ComicID: "mal-13",
        ComicName: "Naruto",
        ComicPublisher: "Shueisha",
        ComicYear: "1999",
        Status: "Active",
        Have: 0,
        Total: 1,
        ComicImage: "https://cdn.myanimelist.net/images/manga/2/x.jpg",
      },
    ];

    render(
      <NuqsAdapter>
        <SeriesTable data={comics} />
      </NuqsAdapter>,
    );

    expect(
      screen.getByRole("img", { name: "One Piece" }).getAttribute("src"),
    ).toBe("/api/metadata/art/md-onepiece");
    expect(
      screen.getByRole("img", { name: "Naruto" }).getAttribute("src"),
    ).toBe("/api/metadata/art/mal-13");
    expect(
      screen.getByRole("img", { name: "One Piece" }).getAttribute("src"),
    ).not.toContain("uploads.mangadex.org");
  });

  it("shows the next page when pagination advances", async () => {
    const user = userEvent.setup();
    window.history.pushState({}, "", "/library");

    render(
      <NuqsAdapter>
        <SeriesTable data={series(21)} />
      </NuqsAdapter>,
    );

    await user.click(screen.getByRole("button", { name: "Next page" }));

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
    // Invariant: an out-of-range page never renders an empty table. The URL
    // half deliberately inverted with the migration: #381's guarded effect
    // rewrote `?page=99` to `?page=3`, and pinned that rewrite precisely so
    // deleting the effect would surface the change rather than hide it. The
    // clamp is now render-time and display-only (#360), so the URL is left
    // exactly as the user supplied it.
    expect(new URLSearchParams(window.location.search).get("page")).toBe("99");
  });

  // The display clamp must count the rows the global search leaves, not just
  // the domain-filtered set: the search runs inside useTableState, so the
  // component reproduces it to size the clamp, and this pins the two against
  // drifting apart. With the clamp counting all 63 rows, page=99 would clamp
  // to page 3 of a one-row searched set and render an empty table.
  it("clamps against the searched rows on a deep link with search and page", async () => {
    window.history.pushState({}, "", "/library?page=99&search=Series+21");

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

    expect(screen.getByText("Series 21")).toBeTruthy();
    expect(screen.queryByText("No results.")).toBeNull();
    expect(new URLSearchParams(window.location.search).get("page")).toBe("99");
    expect(new URLSearchParams(window.location.search).get("search")).toBe(
      "Series 21",
    );
  });

  // Regression: `selectedSeriesIds` used to read the raw rowSelection keys, so
  // a row filtered out of view stayed selected, stayed counted in the bulk
  // bar, and stayed a target of bulk delete/pause/resume — the #307 class.
  // See wayfinder #365 / #390.
  it("drops a filtered-away row from the selection and the bulk bar", async () => {
    const user = userEvent.setup();
    window.history.pushState({}, "", "/library");

    const data = [
      { ComicID: "1", ComicName: "Akira", Status: "Active" },
      { ComicID: "2", ComicName: "Berserk", Status: "Active" },
    ] as Comic[];

    render(
      <NuqsAdapter>
        <SeriesTable data={data} />
      </NuqsAdapter>,
    );

    await user.click(screen.getByRole("checkbox", { name: "Select Akira" }));
    expect(screen.queryAllByText("1 selected")).not.toHaveLength(0);

    // Filter Akira out of view.
    await user.type(screen.getByLabelText("Filter series"), "Berserk");
    await settle();

    expect(screen.queryByText("Akira")).toBeNull();
    expect(screen.queryAllByText(/\d+ selected/)).toHaveLength(0);

    // The selection was pruned, not hidden: clearing the filter brings Akira
    // back deselected, so no bulk action can reach a row the user never saw
    // re-selected.
    await user.clear(screen.getByLabelText("Filter series"));
    await settle();

    expect(screen.getByText("Akira")).toBeTruthy();
    expect(screen.queryAllByText(/\d+ selected/)).toHaveLength(0);
    expect(
      screen
        .getByRole("checkbox", { name: "Select Akira" })
        .getAttribute("aria-checked"),
    ).toBe("false");
  });

  it("keeps a selection on rows the pager, not the filter, hid", async () => {
    const user = userEvent.setup();
    window.history.pushState({}, "", "/library");

    render(
      <NuqsAdapter>
        <SeriesTable data={series(21)} />
      </NuqsAdapter>,
    );

    await user.click(screen.getByRole("checkbox", { name: "Select Series 1" }));
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await settle();

    // Series 1 is on the previous page — out of sight but not out of the
    // filtered row set, so it must stay selected and counted.
    expect(screen.queryByText("Series 1")).toBeNull();
    expect(screen.queryAllByText("1 selected")).not.toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Previous page" }));
    await settle();

    expect(
      screen
        .getByRole("checkbox", { name: "Select Series 1" })
        .getAttribute("aria-checked"),
    ).toBe("true");
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

  // Regression #414: at phone widths the desktop row used
  // minmax(0,1fr) for the title beside ~670px of fixed tracks, so the title
  // track (and the truncate span beside the kind badge) collapsed to 0px.
  // The list now adapts to a 3-column phone grid and the title span is the
  // flexible primary. jsdom cannot assert clientWidth, so this pins the
  // layout contract that keeps the title identifiable.
  it("keeps list-row titles as the flexible primary identifier", () => {
    window.history.pushState({}, "", "/library");

    const data = [
      {
        ComicID: "1",
        ComicName: "A Very Long Series Title That Must Stay Readable",
        ComicPublisher: "Publisher House",
        ComicYear: "2024",
        Status: "Active",
        Have: 3,
        Total: 12,
        ContentType: "comic",
      },
    ] as Comic[];

    const { container } = render(
      <NuqsAdapter>
        <SeriesTable data={data} />
      </NuqsAdapter>,
    );

    const title = screen.getByTestId("series-row-title");
    expect(title.textContent).toBe(
      "A Very Long Series Title That Must Stay Readable",
    );
    expect(title.className.split(/\s+/)).toEqual(
      expect.arrayContaining(["min-w-0", "flex-1", "truncate"]),
    );

    const titleSlot = title.closest("[data-series-title-slot]");
    expect(titleSlot).toBeTruthy();
    expect(titleSlot?.className.split(/\s+/)).toContain("min-w-0");

    const row = container.querySelector("[data-series-row]");
    expect(row).toBeTruthy();
    // Phone track list: only checkbox / cover / flexible title.
    expect(row?.className).toMatch(/grid-cols-\[20px_40px_minmax\(0,1fr\)\]/);
    // Desktop keeps a non-zero title floor beside fixed secondary columns.
    expect(row?.className).toMatch(
      /md:grid-cols-\[20px_40px_minmax\(10rem,1fr\)_/,
    );

    // Secondary desktop columns must leave the phone grid (max-md:hidden),
    // not sit as zero-width fr siblings of the title.
    const desktopOnly = container.querySelectorAll(".max-md\\:hidden");
    expect(desktopOnly.length).toBeGreaterThan(0);
  });
});
