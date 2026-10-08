import { describe, expect, it } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import SearchAddButton from "@/components/search/SearchAddButton";
import type { SearchResult } from "@/types";

const wizard = {
  comicid: "18692",
  id: "18692",
  name: "Wizard",
} as SearchResult;

describe("SearchAddButton", () => {
  it("adds a comic straight into a chosen folder", async () => {
    let payload: unknown;
    server.use(
      http.post("/api/search/add", async ({ request }) => {
        payload = await request.json();
        return HttpResponse.json({ success: true, comicid: "18692" });
      }),
    );
    const user = userEvent.setup();
    render(<SearchAddButton comic={wizard} contentType="comic" />);

    await user.click(
      screen.getByRole("button", { name: "Add Wizard to a chosen folder" }),
    );
    await user.type(
      await screen.findByLabelText("Folder"),
      "/magazines/Wizard",
    );
    await user.click(screen.getByRole("button", { name: "Add comic" }));

    await waitFor(() =>
      expect(payload).toEqual({ id: "18692", folder: "/magazines/Wizard" }),
    );
    expect(
      await screen.findByText(
        "Wizard is being added to /magazines/Wizard. Please wait...",
      ),
    ).toBeTruthy();
  });

  it("keeps the folder dialog open with the reason a folder was refused", async () => {
    server.use(
      http.post("/api/search/add", () =>
        HttpResponse.json(
          {
            detail:
              "Folder must be inside a library root, not the root itself.",
          },
          { status: 400 },
        ),
      ),
    );
    const user = userEvent.setup();
    render(<SearchAddButton comic={wizard} contentType="comic" />);

    await user.click(
      screen.getByRole("button", { name: "Add Wizard to a chosen folder" }),
    );
    await user.type(await screen.findByLabelText("Folder"), "/etc");
    await user.click(screen.getByRole("button", { name: "Add comic" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "inside a library root",
    );
    expect(
      screen.getByRole("dialog", { name: "Add Wizard to a folder" }),
    ).toBeTruthy();
  });

  it("still adds with one click and no folder", async () => {
    let payload: unknown;
    server.use(
      http.post("/api/search/add", async ({ request }) => {
        payload = await request.json();
        return HttpResponse.json({ success: true, comicid: "18692" });
      }),
    );
    const user = userEvent.setup();
    render(<SearchAddButton comic={wizard} contentType="comic" />);

    await user.click(screen.getByRole("button", { name: "Add Wizard" }));

    await waitFor(() => expect(payload).toEqual({ id: "18692" }));
  });
});
