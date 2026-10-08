import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
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

  it("announces list sort direction on the sort button", async () => {
    const user = userEvent.setup();
    const onSortChange = vi.fn();

    const { rerender } = render(
      <SearchResultsTable
        results={results}
        currentSort="relevance"
        onSortChange={onSortChange}
        contentType="comic"
      />,
    );

    expect(screen.queryByRole("columnheader")).toBeNull();

    await user.click(screen.getByRole("button", { name: /^series$/i }));
    expect(onSortChange).toHaveBeenCalledWith("name_desc");

    rerender(
      <SearchResultsTable
        results={results}
        currentSort="name_desc"
        onSortChange={onSortChange}
        contentType="comic"
      />,
    );

    expect(
      screen.getByRole("button", { name: /series.*sorted descending/i }),
    ).toBeTruthy();

    await user.click(
      screen.getByRole("button", { name: /series.*sorted descending/i }),
    );
    expect(onSortChange).toHaveBeenCalledWith("name_asc");

    rerender(
      <SearchResultsTable
        results={results}
        currentSort="name_asc"
        onSortChange={onSortChange}
        contentType="comic"
      />,
    );

    expect(
      screen.getByRole("button", { name: /series.*sorted ascending/i }),
    ).toBeTruthy();
  });
});
