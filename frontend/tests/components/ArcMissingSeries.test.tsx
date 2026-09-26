/**
 * Tests for the story-arc "Add what's missing" flow (issue #913).
 *
 * The card lists arc series absent from the library; the dialog resolves each
 * to a ComicVine match and only confirmed, resolved series are POSTed.
 */

import { describe, it, expect } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import ArcMissingSeries from "@/components/storyarcs/ArcMissingSeries";

const MISSING = [
  {
    series_name: "Flashpoint",
    comic_id: "",
    series_year: null,
    publisher: null,
    issue_count: 2,
    issue_numbers: ["1", "2"],
  },
  {
    series_name: "Doom",
    comic_id: "C9",
    series_year: "2015",
    publisher: "Marvel",
    issue_count: 1,
    issue_numbers: ["1"],
  },
];

const RESOLVED = {
  success: true,
  series: [
    {
      ...MISSING[0],
      match: {
        comic_id: "777",
        name: "Flashpoint",
        year: "2011",
        publisher: "DC Comics",
        image: null,
      },
    },
    {
      ...MISSING[1],
      match: {
        comic_id: "C9",
        name: "Doom",
        year: "2015",
        publisher: "Marvel",
        image: null,
      },
    },
  ],
};

describe("ArcMissingSeries", () => {
  it("lists missing series with needed issue counts", () => {
    render(<ArcMissingSeries storyArcId="ARC1" missing={MISSING} />);

    expect(screen.getByText("Flashpoint")).toBeTruthy();
    expect(screen.getByText("Doom")).toBeTruthy();
    expect(screen.getByText("needs 2 issues")).toBeTruthy();
    expect(screen.getByText("needs 1 issue")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /add what's missing/i }),
    ).toBeTruthy();
  });

  it("confirms only resolved series and posts the additions", async () => {
    const user = userEvent.setup();
    let capturedBody: Record<string, unknown> | null = null;

    server.use(
      http.get("/api/storyarcs/ARC1/missing", () =>
        HttpResponse.json(RESOLVED),
      ),
      http.post("/api/storyarcs/ARC1/add-missing", async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ success: true, queued: 2 });
      }),
    );

    render(<ArcMissingSeries storyArcId="ARC1" missing={MISSING} />);

    await user.click(
      screen.getByRole("button", { name: /add what's missing/i }),
    );

    await waitFor(() => {
      expect(screen.getByText(/DC Comics/)).toBeTruthy();
    });

    await user.click(
      screen.getByRole("button", {
        name: /add 2 series & mark issues wanted/i,
      }),
    );

    await waitFor(() => {
      expect(capturedBody).toEqual({
        additions: [
          { series_name: "Flashpoint", comic_id: "777" },
          { series_name: "Doom", comic_id: "C9" },
        ],
      });
    });
  });

  it("keeps unresolved series out of the additions", async () => {
    const user = userEvent.setup();
    let capturedBody: Record<string, unknown> | null = null;

    server.use(
      http.get("/api/storyarcs/ARC1/missing", () =>
        HttpResponse.json({
          success: true,
          series: [{ ...RESOLVED.series[0] }, { ...MISSING[1], match: null }],
        }),
      ),
      http.post("/api/storyarcs/ARC1/add-missing", async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ success: true, queued: 1 });
      }),
    );

    render(<ArcMissingSeries storyArcId="ARC1" missing={MISSING} />);

    await user.click(
      screen.getByRole("button", { name: /add what's missing/i }),
    );

    await waitFor(() => {
      expect(screen.getByText(/won't be added/i)).toBeTruthy();
    });

    await user.click(
      screen.getByRole("button", {
        name: /add 1 series & mark issues wanted/i,
      }),
    );

    await waitFor(() => {
      expect(capturedBody).toEqual({
        additions: [{ series_name: "Flashpoint", comic_id: "777" }],
      });
    });
  });
});
