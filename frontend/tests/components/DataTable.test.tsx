import { useMemo } from "react";
import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { createColumnHelper } from "@tanstack/react-table";
import { render, screen } from "../test-utils";
import { DataTable } from "@/components/data-table/DataTable";
import { DataTableSortHeader } from "@/components/data-table/DataTableSortHeader";
import {
  useTableState,
  type ComicarrTableFeatures,
} from "@/components/data-table/useTableState";

type Row = { id: string; title: string };

const columnHelper = createColumnHelper<ComicarrTableFeatures, Row>();

function TitleTable() {
  const columns = useMemo(
    () =>
      columnHelper.columns([
        columnHelper.accessor("title", {
          header: ({ column }) => (
            <DataTableSortHeader column={column} title="Title" />
          ),
        }),
      ]),
    [],
  );
  const { table } = useTableState({
    data: [
      { id: "1", title: "Alpha" },
      { id: "2", title: "Beta" },
    ],
    columns,
    getRowId: (row) => row.id,
  });
  return <DataTable table={table} />;
}

describe("DataTable sort headers", () => {
  it("exposes sort direction on the column header", async () => {
    const user = userEvent.setup();
    render(<TitleTable />);

    await user.click(screen.getByRole("button", { name: /title/i }));

    expect(
      ["ascending", "descending"].includes(
        screen
          .getByRole("columnheader", { name: /title/i })
          .getAttribute("aria-sort") ?? "",
      ),
    ).toBe(true);
  });
});
