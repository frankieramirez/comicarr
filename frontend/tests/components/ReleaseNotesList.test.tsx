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

  it("renders a changeset's sub-bullets as a nested list", () => {
    const { container } = render(
      <BulletBody
        text={
          "Releases now shows manga.\n\n- Mine and Industry are one list.\n- **Popular only** is on\n  by default."
        }
      />,
    );

    const items = Array.from(container.querySelectorAll("li")).map(
      (li) => li.textContent,
    );
    expect(items).toEqual([
      "Mine and Industry are one list.",
      "Popular only is on by default.",
    ]);
    expect(container.querySelector("p")?.textContent).toBe(
      "Releases now shows manga.",
    );
    expect(container.textContent).not.toContain("- ");
  });
});
