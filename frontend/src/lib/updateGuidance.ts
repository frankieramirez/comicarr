/**
 * Install-type how-to-update copy for the update-available popover (#473 / #452).
 * Instructions only — Comicarr never mutates the install from this surface.
 */

import type { InstallType } from "@/types/version";

export const GHCR_IMAGE = "ghcr.io/frankieramirez/comicarr";

/**
 * The git/release line carries a `v` prefix: git tags, GitHub release pages.
 */
export function asGitTag(latestVersion: string): string {
  return latestVersion.startsWith("v") ? latestVersion : `v${latestVersion}`;
}

/**
 * The registry line does not: .github/workflows/release.yml pushes
 * `${GHCR_IMAGE}:${version}` from package.json, bare semver. Carrying the `v`
 * into a pull reference 404s (#545), so the two lines never share a helper.
 */
export function asRegistryTag(latestVersion: string): string {
  return latestVersion.replace(/^v/, "");
}

export function releaseTagUrl(latestVersion: string): string {
  return `https://github.com/frankieramirez/comicarr/releases/tag/${asGitTag(latestVersion)}`;
}

export function pinImageTag(latestVersion: string): string {
  return `${GHCR_IMAGE}:${asRegistryTag(latestVersion)}`;
}

export interface UpdateGuidance {
  title: string;
  intro: string;
  /** Copyable shell blocks; empty for prose-only types (win/source). */
  commands: string[];
  note?: string;
}

export function getUpdateGuidance(
  installType: InstallType | null | undefined,
  latestVersion: string,
): UpdateGuidance {
  const tag = asGitTag(latestVersion);
  const pinned = pinImageTag(latestVersion);
  const kind = (installType || "source").toLowerCase();

  if (kind === "docker") {
    return {
      title: "How to update (Docker)",
      intro:
        "Pull the notified release and recreate the container on the host. Comicarr cannot replace its own container.",
      commands: [
        ["docker compose pull", "docker compose up -d"].join("\n"),
        [
          `docker pull ${pinned}`,
          "docker stop comicarr",
          "docker rm comicarr",
        ].join("\n"),
      ],
      note: `Compose: set image: ${pinned} in the compose file before pulling — a pull alone never moves a running container off :latest. Standalone: after the stop and rm, re-run your original docker run with ${pinned}. Your config and library are mounted volumes and survive either path.`,
    };
  }

  if (kind === "git") {
    return {
      title: "How to update (git)",
      intro: `Check out the release tag ${tag}, then restart Comicarr. Do not git pull a branch — branches are not the release line.`,
      commands: [["git fetch --tags origin", `git checkout ${tag}`].join("\n")],
      note: "Restart the Comicarr process after checkout.",
    };
  }

  if (kind === "win") {
    return {
      title: "How to update (Windows)",
      intro:
        "Self-update is not supported for this install. Download the notified release from GitHub and upgrade using your usual install path.",
      commands: [],
      note: "Use the Release link for the exact tag notes and assets.",
    };
  }

  return {
    title: "How to update (source)",
    intro: `Upgrade this source install to ${tag} from the GitHub release (reinstall or replace the tree from that tag). Do not run in-app tarball overwrite commands.`,
    commands: [],
    note: "See the Release page for that version’s notes and packaging.",
  };
}
