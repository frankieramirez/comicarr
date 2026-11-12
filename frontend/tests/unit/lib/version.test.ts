import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it, expect } from "vitest";
import packageJson from "../../../package.json";
import rootPackageJson from "../../../../package.json";
import { APP_VERSION, formatAppVersion } from "@/lib/version";

const here = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(here, "../../..");
const repoRoot = resolve(frontendRoot, "..");

/** Every user-facing surface that shows the app release version. */
const VERSION_DISPLAY_CONSUMERS = [
  "src/components/layout/VersionChip.tsx",
  "src/components/onboarding/OnboardingDialog.tsx",
  "src/components/settings/AboutTab.tsx",
  "src/pages/SettingsPage.tsx",
] as const;

function readPyprojectVersion(): string {
  const text = readFileSync(resolve(repoRoot, "pyproject.toml"), "utf8");
  let inProject = false;
  for (const line of text.split("\n")) {
    if (/^\[.+\]\s*$/.test(line)) {
      inProject = line.trim() === "[project]";
      continue;
    }
    if (inProject) {
      const match = line.match(/^version\s*=\s*"([^"]+)"/);
      if (match) return match[1];
    }
  }
  throw new Error("Could not find [project] version in pyproject.toml");
}

function* walkTsSources(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    const full = resolve(dir, name);
    if (statSync(full).isDirectory()) {
      yield* walkTsSources(full);
    } else if (/\.(tsx?)$/.test(name) && !name.endsWith(".d.ts")) {
      yield full;
    }
  }
}

describe("version", () => {
  it("matches frontend package.json", () => {
    expect(APP_VERSION).toBe(packageJson.version);
    expect(APP_VERSION).toMatch(/^\d+\.\d+\.\d+/);
  });

  it("stays in lockstep with root package.json and pyproject.toml", () => {
    // Single build-version contract (#412). Changesets + sync-version.mjs
    // keep these three surfaces aligned; any drift reopens conflicting badges.
    const pyprojectVersion = readPyprojectVersion();
    expect(APP_VERSION).toBe(rootPackageJson.version);
    expect(APP_VERSION).toBe(pyprojectVersion);
    expect(packageJson.version).toBe(pyprojectVersion);
  });

  it("formats with and without v prefix", () => {
    expect(formatAppVersion()).toBe(`v${packageJson.version}`);
    expect(formatAppVersion(true)).toBe(`v${packageJson.version}`);
    expect(formatAppVersion(false)).toBe(packageJson.version);
  });

  describe("display consumers", () => {
    for (const rel of VERSION_DISPLAY_CONSUMERS) {
      it(`${rel} routes through @/lib/version`, () => {
        const source = readFileSync(resolve(frontendRoot, rel), "utf8");
        expect(source).toMatch(/from ["']@\/lib\/version["']/);
        expect(source).toMatch(/\bformatAppVersion\b/);
        // Must not paint config.version (git SHA / stale install metadata).
        expect(source).not.toMatch(
          /config\?\.version\s*\?|config\.version\s*\|\||\[\s*["']version["']\s*,\s*config\.version/,
        );
      });
    }

    it("lists every file that imports the version helper as a known consumer", () => {
      // Fail if a new surface imports @/lib/version without joining the list
      // above (or if a listed consumer stops importing it).
      const importers = [...walkTsSources(resolve(frontendRoot, "src"))]
        .filter((path) => {
          if (path.replaceAll("\\", "/").endsWith("/lib/version.ts")) {
            return false;
          }
          const text = readFileSync(path, "utf8");
          return /from ["']@\/lib\/version["']/.test(text);
        })
        .map((path) =>
          path.slice(frontendRoot.length + 1).replaceAll("\\", "/"),
        )
        .sort();

      expect(importers).toEqual([...VERSION_DISPLAY_CONSUMERS].sort());
    });
  });
});
