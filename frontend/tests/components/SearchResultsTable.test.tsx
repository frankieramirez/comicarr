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

describe("SearchResultsTable", () => {
  it("uses a phone grid that keeps title and the add action", () => {
    const { container } = render(
      <SearchResultsTable
        results={[spider2022]}
        currentSort="relevance"
        onSortChange={() => undefined}
        contentType="comic"
      />,
    );

    const row = screen.getByTestId("search-result-row");
    expect(row.className).toMatch(/grid-cols-\[40px_minmax\(0,1fr\)_auto\]/);
    expect(row.className).toMatch(/md:grid-cols-\[40px_56px_minmax\(0,1fr\)_/);
    expect(
      container.querySelectorAll(".max-md\\:hidden").length,
    ).toBeGreaterThan(0);
  });

  it("keeps year and publisher in the phone title so volumes stay distinct", () => {
    render(
      <SearchResultsTable
        results={[spider2022, spider2016]}
        currentSort="relevance"
        onSortChange={() => undefined}
        contentType="comic"
      />,
    );

    const ids = screen.getAllByTestId("phone-row-id");
    expect(ids).toHaveLength(2);
    expect(ids[0].textContent).toContain("2022");
    expect(ids[0].textContent).toContain("Marvel");
    expect(ids[1].textContent).toContain("2016");
    expect(ids[1].className).toMatch(/hidden/);
    expect(ids[1].className).toMatch(/max-md:inline/);
  });
});
