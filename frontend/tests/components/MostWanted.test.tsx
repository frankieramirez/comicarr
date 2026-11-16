import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { MostWanted } from "@/components/dashboard/LibraryHighlights";
import { server } from "../mocks/server";
import { render, screen, within } from "../test-utils";

/**
 * Most wanted counts what the Wanted page counts. A series with Skipped
 * issues has gaps, but nothing it is waiting for (audit finding 4).
 */
describe("MostWanted", () => {
  it("ranks series by wanted issues, not by every gap", async () => {
    server.use(
      http.get("/api/series", () =>
        HttpResponse.json([
          // 117 gaps, but only 43 wanted: the rest are Skipped.
          {
            ComicID: "1",
            ComicName: "Electric Paragon",
            Total: 500,
            Have: 383,
            Wanted: 43,
          },
          // Fewer gaps, more of them wanted.
          {
            ComicID: "2",
            ComicName: "Night Signal",
            Total: 80,
            Have: 20,
            Wanted: 60,
          },
          // All gaps skipped: not wanted at all.
          {
            ComicID: "3",
            ComicName: "Quiet Harbor",
            Total: 300,
            Have: 10,
            Wanted: 0,
          },
        ]),
      ),
    );

    render(<MostWanted />);

    const panel = await screen.findByTestId("most-wanted");
    expect(
      await within(panel).findByText("103 wanted across 2 series"),
    ).toBeTruthy();
    const names = within(panel)
      .getAllByRole("link")
      .map((link) => link.textContent ?? "")
      .filter((text) => !text.includes("Open Wanted"));
    expect(names[0]).toContain("Night Signal");
    expect(names[0]).toContain("60 wanted");
    expect(names[1]).toContain("Electric Paragon");
    expect(names[1]).toContain("43 wanted");
    expect(within(panel).queryByText(/Quiet Harbor/)).toBeNull();
  });

  it("says so when nothing is wanted", async () => {
    server.use(
      http.get("/api/series", () =>
        HttpResponse.json([
          { ComicID: "3", ComicName: "Quiet Harbor", Total: 300, Have: 10 },
        ]),
      ),
    );

    render(<MostWanted />);

    expect(
      await screen.findByText("No issues are wanted right now."),
    ).toBeTruthy();
  });
});
