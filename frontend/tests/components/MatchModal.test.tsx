import { describe, it, expect, vi, beforeEach } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "../mocks/server";
import { http, HttpResponse } from "msw";
import { screen, renderMinimal } from "../test-utils";
import MatchModal from "@/components/import/MatchModal";
import type { ImportGroup } from "@/types";

const comicGroup: ImportGroup = {
  DynamicName: "amazing-spider-man",
  ComicName: "Amazing Spider-Man",
  Volume: null,
  ComicYear: "2020",
  FileCount: 1,
  Status: "Unmatched",
  SRID: null,
  ComicID: "4050-12345",
  MatchConfidence: null,
  SuggestedComicID: null,
  SuggestedComicName: null,
  files: [],
};

const mangaGroup: ImportGroup = {
  ...comicGroup,
  DynamicName: "one-piece",
  ComicName: "One Piece",
  ComicID: null,
  SuggestedComicID: "md-abc123",
};

describe("MatchModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("searches comics for comic import groups", async () => {
    let searchedEndpoint = "";

    server.use(
      http.post("/api/search/comics", async () => {
        searchedEndpoint = "comics";
        return HttpResponse.json({
          results: [
            {
              comicid: "12345",
              name: "Amazing Spider-Man",
              comicyear: "2022",
              publisher: "Marvel",
            },
          ],
          pagination: { total: 1, limit: 20, offset: 0, returned: 1 },
        });
      }),
      http.post("/api/search/manga", async () => {
        searchedEndpoint = "manga";
        return HttpResponse.json({
          results: [],
          pagination: { total: 0, limit: 20, offset: 0, returned: 0 },
        });
      }),
    );

    renderMinimal(
      <MatchModal
        isOpen
        onClose={vi.fn()}
        importGroup={comicGroup}
        onMatch={vi.fn()}
      />,
    );

    const input = screen.getByPlaceholderText("Search for a comic series...");
    await userEvent.clear(input);
    await userEvent.type(input, "Spider");

    await waitFor(() => {
      expect(searchedEndpoint).toBe("comics");
    });
  });

  it("searches manga for manga import groups", async () => {
    let searchedEndpoint = "";

    server.use(
      http.get("/api/config", () => {
        return HttpResponse.json({
          http_host: "0.0.0.0",
          mangadex_enabled: true,
          mal_enabled: false,
        });
      }),
      http.post("/api/search/comics", async () => {
        searchedEndpoint = "comics";
        return HttpResponse.json({
          results: [],
          pagination: { total: 0, limit: 20, offset: 0, returned: 0 },
        });
      }),
      http.post("/api/search/manga", async () => {
        searchedEndpoint = "manga";
        return HttpResponse.json({
          results: [
            {
              comicid: "md-abc123",
              name: "One Piece",
              comicyear: "1997",
              publisher: "Shueisha",
            },
          ],
          pagination: { total: 1, limit: 20, offset: 0, returned: 1 },
        });
      }),
    );

    renderMinimal(
      <MatchModal
        isOpen
        onClose={vi.fn()}
        importGroup={mangaGroup}
        onMatch={vi.fn()}
      />,
    );

    await waitFor(
      () => {
        expect(searchedEndpoint).toBe("manga");
      },
      { timeout: 3000 },
    );
  });

  it("shows notice when manga is detected but sources are disabled", async () => {
    server.use(
      http.get("/api/config", () => {
        return HttpResponse.json({
          http_host: "0.0.0.0",
          mangadex_enabled: false,
          mal_enabled: false,
        });
      }),
    );

    renderMinimal(
      <MatchModal
        isOpen
        onClose={vi.fn()}
        importGroup={mangaGroup}
        onMatch={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(
        screen.getByText(
          "Manga search requires MangaDex or MyAnimeList to be enabled in Settings.",
        ),
      ).toBeTruthy();
    });

    expect(
      screen.getByPlaceholderText("Search for a manga series..."),
    ).toHaveProperty("disabled", true);
  });
});
