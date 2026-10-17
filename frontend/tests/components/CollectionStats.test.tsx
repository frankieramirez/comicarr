import { describe, expect, it } from "vitest";
import { render, screen } from "../test-utils";
import CollectionStats from "@/components/dashboard/CollectionStats";

const base = {
  total_series: 3,
  total_issues: 12,
  total_expected: 30,
  completion_pct: 40,
  comic_series: 2,
  comic_have: 7,
  comic_total: 20,
};

describe("CollectionStats", () => {
  it("splits magazines out of the comic counts", () => {
    render(
      <CollectionStats
        isLoading={false}
        stats={{
          ...base,
          magazine_series: 1,
          magazine_have: 5,
          magazine_total: 10,
        }}
      />,
    );

    expect(screen.getByText("2 comics, 1 magazines")).toBeTruthy();
    expect(screen.getByText("7 comic, 5 magazine")).toBeTruthy();
  });

  it("shows no split for a comics-only library", () => {
    render(<CollectionStats isLoading={false} stats={base} />);

    expect(screen.queryByText(/comics,/)).toBeNull();
  });
});
