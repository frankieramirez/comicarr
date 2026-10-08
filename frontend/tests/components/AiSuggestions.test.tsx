import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import { AiSuggestions } from "@/components/weekly/AiSuggestions";

describe("AiSuggestions", () => {
  it("renders unavailable with retry when suggestions fail, not the empty sentence", async () => {
    server.use(
      http.get("/api/ai/suggestions", () =>
        HttpResponse.json({ detail: "unavailable" }, { status: 500 }),
      ),
    );

    render(<AiSuggestions />);

    expect(await screen.findByText("Suggestions unavailable")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Retry Suggestions" }),
    ).toBeTruthy();
    expect(
      screen.queryByText("Nothing new this week matches your collection"),
    ).toBeNull();
  });

  it("still uses the empty sentence when the endpoint answers with no suggestions", async () => {
    server.use(
      http.get("/api/ai/suggestions", () =>
        HttpResponse.json({ suggestions: [] }),
      ),
    );

    render(<AiSuggestions />);

    expect(
      await screen.findByText("Nothing new this week matches your collection"),
    ).toBeTruthy();
    expect(screen.queryByText("Suggestions unavailable")).toBeNull();
  });
});
