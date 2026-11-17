import { describe, expect, it } from "vitest";
import { libraryScanFolders } from "@/lib/libraryFolders";

describe("libraryScanFolders", () => {
  it("scans the library folder when no comic folder is set", () => {
    expect(libraryScanFolders({ destination_dir: "/comics" })).toEqual({
      comic: "/comics",
      manga: undefined,
    });
  });

  it("prefers the folders chosen for scanning", () => {
    expect(
      libraryScanFolders({
        destination_dir: "/comics",
        comic_dir: "/old/comics",
        manga_destination_dir: "/manga",
        manga_dir: "/old/manga",
      }),
    ).toEqual({ comic: "/old/comics", manga: "/old/manga" });
  });

  it("never scans the comic library folder for manga", () => {
    expect(
      libraryScanFolders({ destination_dir: "/comics", manga_dir: " " }).manga,
    ).toBeUndefined();
    expect(libraryScanFolders({ manga_destination_dir: "/manga" }).manga).toBe(
      "/manga",
    );
  });

  it("treats blank and 'None' as unset", () => {
    expect(
      libraryScanFolders({ comic_dir: "None", destination_dir: "" }),
    ).toEqual({ comic: undefined, manga: undefined });
  });
});
