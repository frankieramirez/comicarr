import { describe, expect, it } from "vitest";
import { render, screen } from "../test-utils";
import SearchResultsTable from "@/components/search/SearchResultsTable";
import type { SearchResult } from "@/types";

const spider2022: SearchResult = {
  id: "12345",
  comicid: "12345",
  name: "Amazing Spider-Man",
  comicyear: "2022",
  issues: 75,
  publisher: "Marvel",
};

const spider2016: SearchResult = {
  id: "67890",
  comicid: "67890",
  name: "Amazing Spider-Man",
  comicyear: "2016",
  issues: 32,
  publisher: "Marvel",
};

const results = [
  {
    id: "1",
    comicid: "1",
    name: "Alpha",
    comicyear: "2020",
    issues: 12,
    publisher: "Pub",
  },
  {
    id: "2",
    comicid: "2",
    name: "Beta",
    comicyear: "2021",
    issues: 8,
    publisher: "Pub",
  },
] as SearchResult[];

describe("SearchResultsTable", () => {
  it("keeps the title and the add action in one row", () => {
    render(<SearchResultsTable results={[spider2022]} contentType="comic" />);

    const row = screen.getByTestId("search-result-row");
    expect(row.className).toMatch(/grid-cols-\[36px_minmax\(0,1fr\)_auto\]/);
    expect(
      screen.getByRole("button", { name: "Add Amazing Spider-Man" }),
    ).toBeTruthy();
  });

  it("keeps year and publisher in the meta line so volumes stay distinct", () => {
    render(
      <SearchResultsTable
        results={[spider2022, spider2016]}
        contentType="comic"
      />,
    );

    const ids = screen.getAllByTestId("phone-row-id");
    expect(ids).toHaveLength(2);
    expect(ids[0].textContent).toBe("Marvel · 2022 · 75 issues");
    expect(ids[1].textContent).toBe("Marvel · 2016 · 32 issues");
  });

  it("links a series already in the library instead of offering Add", () => {
    render(
      <SearchResultsTable
        results={[
          {
            ...results[0],
            in_library: true,
            haveit: { comicid: "md-abc", status: "Active" },
          },
        ]}
        contentType="manga"
      />,
    );

    expect(screen.getByText("In library")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Open Alpha" }).getAttribute("href"),
    ).toBe("/library/md-abc");
    expect(screen.queryByRole("button", { name: "Add Alpha" })).toBeNull();
    expect(screen.getByTestId("phone-row-id").textContent).toBe(
      "Pub · 2020 · 12 chapters",
    );
  });
});
