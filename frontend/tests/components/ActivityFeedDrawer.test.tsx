import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import { ActivityFeedDrawer } from "@/components/ai/ActivityFeedDrawer";

describe("ActivityFeedDrawer", () => {
  it("renders unavailable with retry when activity fails, not the empty sentence", async () => {
    server.use(
      http.get("/api/ai/activity", () =>
        HttpResponse.json({ detail: "unavailable" }, { status: 500 }),
      ),
    );

    render(<ActivityFeedDrawer open onOpenChange={vi.fn()} />);

    expect(await screen.findByText("AI activity unavailable")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Retry AI activity" }),
    ).toBeTruthy();
    expect(screen.queryByText("No AI activity yet")).toBeNull();
  });

  it("still uses the empty sentence when the endpoint answers with no entries", async () => {
    server.use(http.get("/api/ai/activity", () => HttpResponse.json([])));

    render(<ActivityFeedDrawer open onOpenChange={vi.fn()} />);

    expect(await screen.findByText("No AI activity yet")).toBeTruthy();
    expect(screen.queryByText("AI activity unavailable")).toBeNull();
  });
});
