/**
 * Settings-page layout helpers. Pure composition; no React, no I/O.
 *
 * Lives outside SettingsPage.tsx so the page module exports only its
 * component (react-refresh/only-export-components).
 */

export type SectionId =
  | "general"
  | "interface"
  | "api"
  | "search"
  | "acquisition"
  | "media"
  | "notifications"
  | "clients"
  | "ai"
  | "logs"
  | "about";

/** Logs use the full content pane; other tabs stay a readable centered column. */
export function settingsPanelClassName(section: SectionId): string {
  const padding = "px-4 py-5 md:px-6 md:py-6 mx-auto pb-24";
  return section === "logs"
    ? `${padding} w-full max-w-none`
    : `${padding} max-w-4xl`;
}
