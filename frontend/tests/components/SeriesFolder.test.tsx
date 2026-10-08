import { describe, expect, it } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import { SeriesFolder } from "@/components/series/SeriesFolder";

function renderFolder(props: Partial<Parameters<typeof SeriesFolder>[0]> = {}) {
  return render(
    <SeriesFolder
      comicId="18692"
      location="/comics/Wizard (1991)"
      override={false}
      retained={[]}
      {...props}
    />,
  );
}

async function chooseFolder(folder: string) {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Change folder" }));
  const input = await screen.findByLabelText("Folder");
  await user.clear(input);
  await user.type(input, folder);
  return user;
}

describe("SeriesFolder", () => {
  it("shows where the series lives and whether Comicarr chose it", () => {
    renderFolder({
      location: "/magazines/Wizard",
      override: true,
      retained: ["/comics/Wizard (1991)"],
    });

    expect(screen.getByTestId("series-folder").textContent).toBe(
      "/magazines/Wizard",
    );
    expect(screen.getByText("chosen")).toBeTruthy();
    expect(
      screen.getByText(
        /Earlier files are still read from \/comics\/Wizard \(1991\)/,
      ),
    ).toBeTruthy();
  });

  it("changes the folder, leaving files by default, and says what stayed", async () => {
    let payload: unknown;
    server.use(
      http.patch("/api/series/18692/location", async ({ request }) => {
        payload = await request.json();
        return HttpResponse.json({
          success: true,
          comic_location: "/magazines/Wizard",
          previous_location: "/comics/Wizard (1991)",
          override: true,
          files_moved: 0,
          files_left: 12,
          retained_locations: ["/comics/Wizard (1991)"],
        });
      }),
    );
    renderFolder();

    const user = await chooseFolder("/magazines/Wizard");
    await user.click(screen.getByRole("button", { name: "Save folder" }));

    await waitFor(() =>
      expect(payload).toEqual({
        folder: "/magazines/Wizard",
        move_files: false,
      }),
    );
    expect(await screen.findByText("Series folder changed")).toBeTruthy();
    expect(
      screen.getByText(
        "12 files stay readable where they were. New downloads and imports go to /magazines/Wizard.",
      ),
    ).toBeTruthy();
  });

  it("moves files when asked and reports the move", async () => {
    let payload: unknown;
    server.use(
      http.patch("/api/series/18692/location", async ({ request }) => {
        payload = await request.json();
        return HttpResponse.json({
          success: true,
          comic_location: "/magazines/Wizard",
          previous_location: "/comics/Wizard (1991)",
          override: true,
          files_moved: 3,
          files_left: 0,
          retained_locations: [],
        });
      }),
    );
    renderFolder();

    const user = await chooseFolder("/magazines/Wizard");
    await user.click(screen.getByRole("radio", { name: /Move them/ }));
    await user.click(screen.getByRole("button", { name: "Save folder" }));

    await waitFor(() =>
      expect(payload).toEqual({
        folder: "/magazines/Wizard",
        move_files: true,
      }),
    );
    expect(
      await screen.findByText(
        "Moved 3 files from /comics/Wizard (1991). New downloads and imports go to /magazines/Wizard.",
      ),
    ).toBeTruthy();
  });

  it("keeps the dialog open and never claims success when a move stops part way", async () => {
    server.use(
      http.patch("/api/series/18692/location", () =>
        HttpResponse.json(
          {
            detail:
              "Moved 1 of 2 files, then could not move Wizard 002.cbz. The log has the reason.",
            success: false,
            files_moved: 1,
            files_left: 1,
          },
          { status: 500 },
        ),
      ),
    );
    renderFolder();

    const user = await chooseFolder("/magazines/Wizard");
    await user.click(screen.getByRole("radio", { name: /Move them/ }));
    await user.click(screen.getByRole("button", { name: "Save folder" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Wizard 002.cbz");
    expect(alert.textContent).toContain("1 file stays readable where it was.");
    expect(screen.queryByText("Series folder changed")).toBeNull();
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("shows why a folder was refused", async () => {
    server.use(
      http.patch("/api/series/18692/location", () =>
        HttpResponse.json(
          {
            detail:
              "Folder must be inside a library root, not the root itself.",
          },
          { status: 400 },
        ),
      ),
    );
    renderFolder();

    const user = await chooseFolder("/etc");
    await user.click(screen.getByRole("button", { name: "Save folder" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "inside a library root",
    );
  });

  it("returns a chosen folder to the automatic one", async () => {
    let payload: unknown;
    server.use(
      http.patch("/api/series/18692/location", async ({ request }) => {
        payload = await request.json();
        return HttpResponse.json({
          success: true,
          comic_location: "/comics/Wizard (1991)",
          previous_location: "/magazines/Wizard",
          override: false,
          files_moved: 0,
          files_left: 0,
          retained_locations: [],
        });
      }),
    );
    renderFolder({ location: "/magazines/Wizard", override: true });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Change folder" }));
    await user.click(
      await screen.findByRole("button", { name: "Use automatic folder" }),
    );

    await waitFor(() =>
      expect(payload).toEqual({ folder: null, move_files: false }),
    );
    expect(
      await screen.findByText("Series folder is automatic again"),
    ).toBeTruthy();
  });
});
