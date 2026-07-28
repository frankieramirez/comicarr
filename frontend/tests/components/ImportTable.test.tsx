import { useEffect, useMemo } from "react";
import { describe, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { screen, renderMinimal } from "../test-utils";
import ImportTable from "@/components/import/ImportTable";
import {
  getImportGroupRowId,
  getSelectedImportFileIds,
  useImportColumns,
} from "@/components/import/importColumns";
import { useTableState } from "@/components/data-table/useTableState";
import type { ImportGroup, ImportFile } from "@/types";

/**
 * The harness stands in for `ImportPage` as it now is (#396): calling
 * `useTableState` with the shared columns, passing `table` down, and deriving
 * the bulk-action file ids from `selectedRows` via `getSelectedImportFileIds`
 * — the same fan-out the page runs, not a re-implementation.
 *
 * The two selection pins guard this site's only unique invariant, the
 * group→file fan-out; nothing else in the repo covers it. #396 deleted the
 * `onSelectionChange` prop they asserted on, so each names its invariant with
 * the old assertion alongside the new one.
 */
function Harness({
  imports,
  onSelectionChange,
  onIssueNumberChange,
}: {
  imports: ImportGroup[];
  onSelectionChange?: (fileIds: string[], groupCount: number) => void;
  onIssueNumberChange?: (
    file: ImportFile,
    issueNumber: string,
  ) => Promise<void>;
}) {
  const columns = useImportColumns({});
  const { table, selectedRows } = useTableState({
    data: imports,
    columns,
    getRowId: getImportGroupRowId,
    selection: { scope: "filtered" },
    getRowCanExpand: (row) =>
      !!(row.original.files && row.original.files.length > 0),
  });

  const fileIds = useMemo(
    () => getSelectedImportFileIds(selectedRows),
    [selectedRows],
  );
  const groupCount = selectedRows.length;
  useEffect(() => {
    if (fileIds.length > 0) onSelectionChange?.(fileIds, groupCount);
  }, [fileIds, groupCount, onSelectionChange]);

  return (
    <ImportTable table={table} onIssueNumberChange={onIssueNumberChange} />
  );
}

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

    renderMinimal(<Harness imports={groups} onIssueNumberChange={vi.fn()} />);

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
      <Harness
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
      <Harness
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

  it("labels empty-file groups as Ignore, not Unignore", () => {
    renderMinimal(
      <Harness
        imports={[
          makeGroup({
            DynamicName: "folder:empty",
            ComicName: "Empty Group",
            FileCount: 0,
            files: [],
          }),
        ]}
      />,
    );

    expect(screen.getByRole("button", { name: "Ignore import" })).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Unignore import" }),
    ).toBeNull();
  });

  it("labels fully ignored groups as Unignore", () => {
    renderMinimal(
      <Harness
        imports={[
          makeGroup({
            files: [
              makeFile({ impID: "1", IgnoreFile: 1 }),
              makeFile({
                impID: "2",
                IgnoreFile: 1,
                ComicFilename: "chapter 2.cbz",
              }),
            ],
          }),
        ]}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Unignore import" }),
    ).toBeTruthy();
  });

  it("saves edited chapter values from expanded file rows", async () => {
    const file = makeFile();
    const onIssueNumberChange = vi.fn().mockResolvedValue(undefined);

    renderMinimal(
      <Harness
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
      <Harness
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
      <Harness
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
      <Harness
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
      <Harness
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

  // INVARIANT (pin 1 of 2): selecting a *group* row fans out to its
  // constituent file impIDs — row ids alone cannot express this.
  //
  //   old: expect(onSelectionChange).toHaveBeenCalledWith(
  //          ["1", "2"], ["folder:manga-a-null"]);   // ImportTable prop, deleted
  //   new: expect(onSelectionChange).toHaveBeenCalledWith(["1", "2"], 1);
  //
  // The group id argument became a count: the page consumes group *identity*
  // only through `selectedRows`, and the row id is now the #383 encoding, an
  // implementation detail no caller reads.
  it("keeps bulk row selection mapped to import file IDs", async () => {
    const onSelectionChange = vi.fn();

    renderMinimal(
      <Harness
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

    expect(onSelectionChange).toHaveBeenCalledWith(["1", "2"], 1);
  });

  // INVARIANT (pin 2 of 2): a data refresh recomputes the selected file ids
  // from the *fresh* groups — the selection keys on group identity, so new
  // impIDs under the same group must flow through without reselection.
  //
  //   old: rerender(<ImportTable imports={refreshed} …/>);
  //        expect(onSelectionChange).toHaveBeenCalledWith(
  //          ["3", "4"], ["folder:manga-a-null"]);   // emit-upward effect, deleted
  //   new: rerender(<Harness imports={refreshed} …/>);
  //        expect(onSelectionChange).toHaveBeenCalledWith(["3", "4"], 1);
  //
  // Deriving from `selectedRows` is what makes this hold: the stale-copy
  // plumbing (`lastSelectionKeyRef`, the emit effect) is deleted, not ported.
  it("recomputes selected import file IDs when imports refresh", async () => {
    const onSelectionChange = vi.fn();
    const { rerender } = renderMinimal(
      <Harness
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
    expect(onSelectionChange).toHaveBeenCalledWith(["1", "2"], 1);

    onSelectionChange.mockClear();
    rerender(
      <Harness
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
      expect(onSelectionChange).toHaveBeenCalledWith(["3", "4"], 1);
    });
  });

  // Pins the #383 encoder adoption. SQL groups `Volume` null and `""`
  // separately, but the old `${DynamicName}-${Volume || "null"}` id collapsed
  // both to "folder:manga-a-null" — duplicate row ids, so selecting either row
  // reported the *first* group's files. Latent until now (#364, #365).
  it("keeps groups whose Volume is null and empty string separately selectable", async () => {
    const onSelectionChange = vi.fn();

    renderMinimal(
      <Harness
        imports={[
          makeGroup({
            Volume: null,
            files: [makeFile({ impID: "1" })],
          }),
          makeGroup({
            Volume: "",
            files: [
              makeFile({
                impID: "2",
                ComicFilename: "chapter 2.cbz",
                ComicLocation: "/imports/Manga A/chapter 2.cbz",
              }),
            ],
          }),
        ]}
        onSelectionChange={onSelectionChange}
      />,
    );

    // checkboxes[0] is the header select-all; [2] is the second group's row.
    await userEvent.click(screen.getAllByRole("checkbox")[2]);

    expect(onSelectionChange).toHaveBeenCalledWith(["2"], 1);
  });
});
