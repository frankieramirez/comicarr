import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { NuqsAdapter } from "nuqs/adapters/react-router/v7";
import { render, screen } from "../test-utils";
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

describe("SeriesTable", () => {
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
});
