import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { Route, Routes, useLocation } from "react-router-dom";
import { act } from "react";
import userEvent from "@testing-library/user-event";
import CommandPalette from "@/components/layout/CommandPalette";
import { openCommandPalette } from "@/lib/commandPalette";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";

function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.pathname + location.search}</div>;
}

function renderPalette() {
  return render(
    <>
      <CommandPalette />
      <Routes>
        <Route path="*" element={<Where />} />
      </Routes>
    </>,
    { useMemoryRouter: true },
  );
}

describe("CommandPalette", () => {
  it("finds a series from the library and opens it with Enter", async () => {
    server.use(
      http.get("/api/series", () =>
        HttpResponse.json([
          {
            ComicID: "1",
            ComicName: "Magi",
            Status: "Active",
            Have: 248,
            Total: 369,
          },
          { ComicID: "2", ComicName: "Dandadan", Status: "Active" },
        ]),
      ),
    );
    const user = userEvent.setup();
    renderPalette();

    act(() => openCommandPalette());
    const input = await screen.findByRole("combobox", {
      name: "Command palette search",
    });
    await user.type(input, "mag");

    const option = await screen.findByRole("option", { name: /Magi/ });
    expect(option.getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByRole("option", { name: /Dandadan/ })).toBeNull();

    await user.keyboard("{Enter}");
    expect(screen.getByTestId("where").textContent).toBe("/library/1");
  });

  it("offers to add a series and jumps to pages by name", async () => {
    const user = userEvent.setup();
    renderPalette();

    act(() => openCommandPalette());
    const input = await screen.findByRole("combobox", {
      name: "Command palette search",
    });
    await user.type(input, "wan");

    expect(
      screen.getByRole("option", { name: /Add a series matching “wan”/ }),
    ).toBeTruthy();
    await user.click(screen.getByRole("option", { name: /^Wanted/ }));
    expect(screen.getByTestId("where").textContent).toBe("/wanted");
  });
});
