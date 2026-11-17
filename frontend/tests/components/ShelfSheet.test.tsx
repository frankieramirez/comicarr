/**
 * The print copies of one issue: listing them, adding one, and the price box.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import { ShelfSheet } from "@/components/shelf/ShelfSheet";
import { centsToInput, parseCents } from "@/lib/shelf";

const TARGET = {
  item: { ComicID: "100", ItemID: "i64" },
  title: "Starfall Saga #64",
};

const COPY = {
  CopyID: "c1",
  ComicID: "100",
  ItemID: "i64",
  VolumeNumber: null,
  SeriesName: "Starfall Saga",
  ItemLabel: "#64",
  CoverURL: null,
  SeriesPresent: true,
  VariantName: "1:25 virgin",
  Grade: "CGC 9.8",
  PaidCents: 6000,
  Storage: "Slab shelf",
  Notes: null,
  created_at: "2026-11-17T00:00:00+00:00",
  updated_at: "2026-11-17T00:00:00+00:00",
};

function copies(results: unknown[]) {
  return http.get("/api/shelf/copies", () =>
    HttpResponse.json({
      results,
      total: results.length,
      paid_cents: 0,
      limit: 100,
      offset: 0,
    }),
  );
}

describe("ShelfSheet", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("lists the copies of the item it was opened for", async () => {
    let asked = "";
    server.use(
      http.get("/api/shelf/copies", ({ request }) => {
        asked = new URL(request.url).search;
        return HttpResponse.json({
          results: [COPY],
          total: 1,
          paid_cents: 6000,
          limit: 100,
          offset: 0,
        });
      }),
    );

    render(<ShelfSheet target={TARGET} onClose={() => {}} />);

    expect(await screen.findByText("1:25 virgin")).toBeTruthy();
    expect(screen.getByText("CGC 9.8 · Slab shelf · 60.00")).toBeTruthy();
    expect(asked).toBe("?comic_id=100&item_id=i64");
    expect(
      screen.getByRole("button", { name: "Add another copy" }),
    ).toBeTruthy();
  });

  it("opens straight on the form when there are no copies, and saves cents", async () => {
    const user = userEvent.setup();
    let body: Record<string, unknown> | null = null;
    server.use(
      copies([]),
      http.post("/api/shelf/copies", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(COPY, { status: 201 });
      }),
    );

    render(<ShelfSheet target={TARGET} onClose={() => {}} />);

    await user.type(await screen.findByLabelText("Grade"), "NM");
    await user.type(screen.getByLabelText("Paid"), "4,99");
    await user.type(screen.getByLabelText("Storage"), "Long box 03");
    await user.click(screen.getByRole("button", { name: "Add to shelf" }));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toEqual({
      ComicID: "100",
      ItemID: "i64",
      VariantName: "",
      Grade: "NM",
      PaidCents: 499,
      Storage: "Long box 03",
      Notes: "",
    });
    expect(localStorage.getItem("comicarr.shelf.storage")).toBe("Long box 03");
  });

  it("refuses a price it cannot read without calling the server", async () => {
    const user = userEvent.setup();
    let posted = false;
    server.use(
      copies([]),
      http.post("/api/shelf/copies", () => {
        posted = true;
        return HttpResponse.json(COPY, { status: 201 });
      }),
    );

    render(<ShelfSheet target={TARGET} onClose={() => {}} />);

    await user.type(await screen.findByLabelText("Paid"), "five");
    await user.click(screen.getByRole("button", { name: "Add to shelf" }));

    expect((await screen.findByRole("alert")).textContent).toBe(
      "Enter a price such as 4.99.",
    );
    expect(posted).toBe(false);
  });
});

describe("shelf prices", () => {
  it("reads typed prices as whole cents", () => {
    expect(parseCents("4.99")).toBe(499);
    expect(parseCents("4,5")).toBe(450);
    expect(parseCents("60")).toBe(6000);
    expect(parseCents("  ")).toBeNull();
    expect(parseCents("4.999")).toBeUndefined();
    expect(parseCents("-1")).toBeUndefined();
  });

  it("shows stored cents the way they are typed", () => {
    expect(centsToInput(6005)).toBe("60.05");
    expect(centsToInput(null)).toBe("");
  });
});
