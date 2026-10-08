import { describe, expect, it } from "vitest";
import { render, screen } from "../test-utils";
import SearchResultsTable from "@/components/search/SearchResultsTable";
import type { SearchResult } from "@/types";

const results: SearchResult[] = [
  {
    id: "12345",
    comicid: "12345",
    name: "Amazing Spider-Man",
    comicyear: "2022",
    issues: 75,
    publisher: "Marvel",
  },
];

describe("SearchResultsTable", () => {
  it("uses a phone grid that keeps title and the add action", () => {
    const { container } = render(
      <SearchResultsTable
        results={results}
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
});
