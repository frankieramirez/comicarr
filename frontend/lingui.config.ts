import { readdirSync } from "node:fs";
import { defineConfig } from "@lingui/cli";
import { formatter } from "@lingui/format-po";

// Catalogs are gettext .po files under src/locales/<locale>/messages.po, so
// Weblate (or any translation tool) reads and writes them directly. A language
// exists once its folder exists: the list below is read from disk, and the app
// discovers the same folders at build time with import.meta.glob.
//
// `npm run i18n:extract` refreshes every catalog from the source. The Vite
// plugin compiles catalogs when they are imported, so no compiled JS is
// committed. See docs/architecture/i18n.md.
const localesDir = new URL("./src/locales/", import.meta.url);
const translations = readdirSync(localesDir, { withFileTypes: true })
  .filter((entry) => entry.isDirectory() && entry.name !== "en")
  .map((entry) => entry.name)
  .sort();

export default defineConfig({
  sourceLocale: "en",
  locales: ["en", ...translations],
  fallbackLocales: { default: "en" },
  catalogs: [
    {
      path: "<rootDir>/src/locales/{locale}/messages",
      include: ["<rootDir>/src"],
      exclude: ["**/node_modules/**", "**/*.test.*", "**/mockData.ts"],
    },
  ],
  // File-level origins tell a translator where a string appears; line
  // numbers would churn the catalog on every unrelated edit.
  format: formatter({ lineNumbers: false }),
  orderBy: "message",
});
