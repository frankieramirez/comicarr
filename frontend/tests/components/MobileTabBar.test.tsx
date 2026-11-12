/**
 * The phone's bottom navigation (v2 mobile designs): four destinations, a
 * needs-you badge on Activity, and More for everything else.
 */

import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import { SidebarProvider } from "@/components/ui/sidebar";
import MobileTabBar from "@/components/layout/MobileTabBar";

function renderAt(route: string) {
  return render(
    <SidebarProvider>
      <MobileTabBar />
    </SidebarProvider>,
    { useMemoryRouter: true, route },
  );
}

describe("MobileTabBar", () => {
  it("marks the current destination, counting series pages as Library", () => {
    renderAt("/library/42");

    expect(
      screen
        .getByRole("link", { name: "Library" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      screen.getByRole("link", { name: "Home" }).getAttribute("aria-current"),
    ).toBeNull();
  });

  it("badges Activity with what needs you", async () => {
    server.use(
      http.get("/api/activity/status", () =>
        HttpResponse.json({ in_flight: 0, attention: 13 }),
      ),
    );

    renderAt("/");

    expect(await screen.findByLabelText("13 need you")).toBeTruthy();
  });

  it("offers More for the destinations it leaves out", () => {
    renderAt("/settings");

    expect(screen.getByRole("button", { name: "More" })).toBeTruthy();
  });
});
