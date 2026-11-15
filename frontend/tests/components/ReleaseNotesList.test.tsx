import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BulletBody } from "@/components/whats-new/ReleaseNotesList";

describe("BulletBody", () => {
  it("renders bold and code from the changelog instead of raw Markdown", () => {
    const { container } = render(
      <BulletBody text="Turn on **Include Usenet indexers** in `config.ini`." />,
    );

    expect(screen.getByText("Include Usenet indexers").tagName).toBe("STRONG");
    expect(screen.getByText("config.ini").tagName).toBe("CODE");
    expect(container.textContent).not.toContain("**");
    expect(container.textContent).not.toContain("`");
  });
});
