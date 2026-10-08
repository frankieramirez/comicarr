import { describe, expect, it } from "vitest";
import { render, screen } from "../test-utils";
import PageHeader from "@/components/layout/PageHeader";
import PageShell from "@/components/layout/PageShell";

describe("PageShell", () => {
  it("defaults to a full-bleed pinned header and scrolling body", () => {
    render(
      <PageShell header={<PageHeader title="Discover" />}>
        <p>body copy</p>
      </PageShell>,
    );

    const shell = screen.getByTestId("page-shell");
    expect(shell.getAttribute("data-variant")).toBe("full-bleed");
    expect(shell.className).toMatch(/flex h-full min-h-0 min-w-0 flex-col/);
    expect(shell.className).not.toMatch(/max-w-7xl/);
    expect(screen.getByTestId("page-shell-header").className).toMatch(
      /shrink-0/,
    );
    const bodyClass = screen.getByTestId("page-shell-body").className;
    expect(bodyClass).toMatch(/flex-1/);
    expect(bodyClass).toMatch(/min-h-0/);
    expect(bodyClass).toMatch(/overflow-auto/);
    expect(screen.getByTestId("page-header")).toBeTruthy();
    expect(screen.getByText("body copy")).toBeTruthy();
  });

  it("insets the centred variant the way Layout padded non-full-bleed routes", () => {
    render(
      <PageShell variant="centred" header={<PageHeader title="Centred" />}>
        <p>body copy</p>
      </PageShell>,
    );

    const shell = screen.getByTestId("page-shell");
    expect(shell.getAttribute("data-variant")).toBe("centred");
    expect(shell.className).toMatch(/max-w-7xl/);
    expect(shell.className).toMatch(/px-4/);
    expect(shell.className).toMatch(/py-8/);
  });
});
