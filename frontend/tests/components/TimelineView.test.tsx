import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import { TimelineView } from "@/components/activity/timeline/TimelineView";

describe("TimelineView", () => {
  it("exposes in-progress severity as an image role", async () => {
    server.use(
      http.get("/api/activity/timeline", () =>
        HttpResponse.json({
          results: [
            {
              event_id: 1,
              created_at: "2026-07-10 12:00:00",
              activity: "grab",
              status: "succeeded",
              subject_type: "issue",
              subject_id: "iss-1",
              subject_label: "Saga #1",
            },
          ],
          total: 1,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      ),
      http.get("/api/attention", () =>
        HttpResponse.json({
          results: [],
          total: 0,
          member_total: 0,
          preview_cap: 5,
        }),
      ),
    );

    render(<TimelineView />, { useMemoryRouter: true, route: "/activity" });

    expect(
      await screen.findByRole("img", { name: "In progress" }),
    ).toBeTruthy();
  });
});
