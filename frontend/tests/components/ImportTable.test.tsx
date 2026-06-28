import { describe, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { screen, renderMinimal } from "../test-utils";
import ImportTable from "@/components/import/ImportTable";
import type { ImportGroup } from "@/types";

type ImportFile = ImportGroup["files"][number];

function makeFile(overrides: Partial<ImportFile> = {}): ImportFile {
  return {
    impID: "1",
    ComicFilename: "chapter 1.cbz",
    ComicLocation: "/imports/Manga A/chapter 1.cbz",
    IssueNumber: "1",
    ComicYear: null,
    Status: "Unmatched",
    IgnoreFile: 0,
    MatchConfidence: null,
    SuggestedComicID: null,
    SuggestedComicName: null,
    SuggestedIssueID: null,
    MatchSource: null,
    ...overrides,
  };
}

function makeGroup(overrides: Partial<ImportGroup> = {}): ImportGroup {
  const files = overrides.files ?? [makeFile()];
  return {
    DynamicName: "folder:manga-a",
    ComicName: "Manga A",
    Volume: null,
    ComicYear: null,
    FileCount: files.length,
    Status: "Unmatched",
    SRID: null,
    ComicID: null,
    MatchConfidence: null,
    SuggestedComicID: null,
    SuggestedComicName: null,
    files,
    ...overrides,
  };
}

describe("ImportTable", () => {
  it("renders nested manga folders as separate review groups with chapters", async () => {
    const groups = [
      makeGroup({
        DynamicName: "folder:manga-a",
        ComicName: "Manga A",
        files: [
          makeFile({ impID: "1", ComicFilename: "chapter 1.cbz" }),
          makeFile({
            impID: "2",
            ComicFilename: "chapter 2.cbz",
            ComicLocation: "/imports/Manga A/chapter 2.cbz",
            IssueNumber: "2",
          }),
        ],
      }),
      makeGroup({
        DynamicName: "folder:manga-b",
        ComicName: "Manga B",
        files: [
          makeFile({
            impID: "3",
            ComicFilename: "chapter 1.cbz",
            ComicLocation: "/imports/Manga B/chapter 1.cbz",
          }),
          makeFile({
            impID: "4",
            ComicFilename: "chapter 2.cbz",
            ComicLocation: "/imports/Manga B/chapter 2.cbz",
            IssueNumber: "2",
          }),
        ],
      }),
    ];

    renderMinimal(
      <ImportTable imports={groups} onIssueNumberChange={vi.fn()} />,
    );

    expect(screen.getByText("Manga A")).toBeTruthy();
    expect(screen.getByText("Manga B")).toBeTruthy();
    expect(screen.getAllByText("Folder group")).toHaveLength(2);

    await userEvent.click(
      screen.getAllByRole("button", { name: "Expand import files" })[0],
    );

    expect(
      screen.getByRole("textbox", { name: "Chapter for chapter 1.cbz" }),
    ).toHaveProperty("value", "1");
    expect(
      screen.getByRole("textbox", { name: "Chapter for chapter 2.cbz" }),
    ).toHaveProperty("value", "2");
  });

  it("renders root files as one review group per file", () => {
    renderMinimal(
      <ImportTable
        imports={[
          makeGroup({
            DynamicName: "file:root-a",
            ComicName: "Root Manga A",
            FileCount: 1,
            files: [
              makeFile({
                impID: "1",
                ComicFilename: "Root Manga A - Chapter 1.cbz",
                ComicLocation: "/imports/Root Manga A - Chapter 1.cbz",
              }),
            ],
          }),
          makeGroup({
            DynamicName: "file:root-b",
            ComicName: "Root Manga B",
            FileCount: 1,
            files: [
              makeFile({
                impID: "2",
                ComicFilename: "Root Manga B - Chapter 1.cbz",
                ComicLocation: "/imports/Root Manga B - Chapter 1.cbz",
              }),
            ],
          }),
        ]}
      />,
    );

    expect(screen.getByText("Root Manga A")).toBeTruthy();
    expect(screen.getByText("Root Manga B")).toBeTruthy();
    expect(screen.getAllByText("Single file")).toHaveLength(2);
  });

  it("shows no suggestion instead of a misleading zero confidence", () => {
    renderMinimal(
      <ImportTable
        imports={[
          makeGroup({
            MatchConfidence: 0,
            SuggestedComicID: null,
            SuggestedComicName: null,
          }),
        ]}
      />,
    );

    expect(screen.getByText("No suggestion")).toBeTruthy();
    expect(screen.queryByText("0%")).toBeNull();
  });

  it("saves edited chapter values from expanded file rows", async () => {
    const file = makeFile();
    const onIssueNumberChange = vi.fn().mockResolvedValue(undefined);

    renderMinimal(
      <ImportTable
        imports={[makeGroup({ files: [file] })]}
        onIssueNumberChange={onIssueNumberChange}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Expand import files" }),
    );

    const input = screen.getByRole("textbox", {
      name: "Chapter for chapter 1.cbz",
    });
    await userEvent.clear(input);
    await userEvent.type(input, "3{Enter}");

    await waitFor(() => {
      expect(onIssueNumberChange).toHaveBeenCalledWith(file, "3");
    });
    expect(screen.getByText("Saved")).toBeTruthy();
  });

  it("keeps the last saved chapter as the edit baseline before refetch", async () => {
    const file = makeFile();
    const onIssueNumberChange = vi.fn().mockResolvedValue(undefined);

    renderMinimal(
      <ImportTable
        imports={[makeGroup({ files: [file] })]}
        onIssueNumberChange={onIssueNumberChange}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Expand import files" }),
    );

    const input = screen.getByRole("textbox", {
      name: "Chapter for chapter 1.cbz",
    });
    await userEvent.clear(input);
    await userEvent.type(input, "3{Enter}");

    await waitFor(() => {
      expect(onIssueNumberChange).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.getByText("Saved")).toBeTruthy();
    });

    await userEvent.tab();
    expect(onIssueNumberChange).toHaveBeenCalledTimes(1);

    await userEvent.click(input);
    await userEvent.clear(input);
    await userEvent.type(input, "4{Escape}");

    expect(onIssueNumberChange).toHaveBeenCalledTimes(1);
    expect(input).toHaveProperty("value", "3");
  });

  it("shows saving feedback while chapter updates are pending", async () => {
    let resolveSave: () => void = () => {};
    const onIssueNumberChange = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveSave = resolve;
        }),
    );

    renderMinimal(
      <ImportTable
        imports={[makeGroup()]}
        onIssueNumberChange={onIssueNumberChange}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Expand import files" }),
    );

    const input = screen.getByRole("textbox", {
      name: "Chapter for chapter 1.cbz",
    });
    await userEvent.clear(input);
    await userEvent.type(input, "4{Enter}");

    expect(screen.getByText("Saving...")).toBeTruthy();
    resolveSave();

    await waitFor(() => {
      expect(screen.getByText("Saved")).toBeTruthy();
    });
  });

  it("shows save feedback when chapter update fails", async () => {
    const onIssueNumberChange = vi
      .fn()
      .mockRejectedValue(new Error("Unable to save"));

    renderMinimal(
      <ImportTable
        imports={[makeGroup()]}
        onIssueNumberChange={onIssueNumberChange}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Expand import files" }),
    );

    const input = screen.getByRole("textbox", {
      name: "Chapter for chapter 1.cbz",
    });
    await userEvent.clear(input);
    await userEvent.type(input, "4{Enter}");

    await waitFor(() => {
      expect(screen.getByText("Save failed")).toBeTruthy();
    });
  });

  it("validates blank chapter values before saving", async () => {
    const onIssueNumberChange = vi.fn().mockResolvedValue(undefined);

    renderMinimal(
      <ImportTable
        imports={[makeGroup()]}
        onIssueNumberChange={onIssueNumberChange}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Expand import files" }),
    );

    const input = screen.getByRole("textbox", {
      name: "Chapter for chapter 1.cbz",
    });
    await userEvent.clear(input);
    await userEvent.tab();

    expect(screen.getByText("Required")).toBeTruthy();
    expect(onIssueNumberChange).not.toHaveBeenCalled();
  });

  it("keeps bulk row selection mapped to import file IDs", async () => {
    const onSelectionChange = vi.fn();

    renderMinimal(
      <ImportTable
        imports={[
          makeGroup({
            files: [
              makeFile({ impID: "1" }),
              makeFile({ impID: "2", ComicFilename: "chapter 2.cbz" }),
            ],
          }),
        ]}
        onSelectionChange={onSelectionChange}
      />,
    );

    await userEvent.click(screen.getAllByRole("checkbox")[1]);

    expect(onSelectionChange).toHaveBeenCalledWith(
      ["1", "2"],
      ["folder:manga-a-null"],
    );
  });

  it("recomputes selected import file IDs when imports refresh", async () => {
    const onSelectionChange = vi.fn();
    const { rerender } = renderMinimal(
      <ImportTable
        imports={[
          makeGroup({
            files: [
              makeFile({ impID: "1" }),
              makeFile({ impID: "2", ComicFilename: "chapter 2.cbz" }),
            ],
          }),
        ]}
        onSelectionChange={onSelectionChange}
      />,
    );

    await userEvent.click(screen.getAllByRole("checkbox")[1]);
    expect(onSelectionChange).toHaveBeenCalledWith(
      ["1", "2"],
      ["folder:manga-a-null"],
    );

    onSelectionChange.mockClear();
    rerender(
      <ImportTable
        imports={[
          makeGroup({
            files: [
              makeFile({ impID: "3" }),
              makeFile({ impID: "4", ComicFilename: "chapter 2.cbz" }),
            ],
          }),
        ]}
        onSelectionChange={onSelectionChange}
      />,
    );

    await waitFor(() => {
      expect(onSelectionChange).toHaveBeenCalledWith(
        ["3", "4"],
        ["folder:manga-a-null"],
      );
    });
  });
});
