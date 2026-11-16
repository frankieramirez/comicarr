/**
 * Which language the UI runs in, and loading its catalog.
 *
 * A language is available once `src/locales/<locale>/messages.po` exists;
 * the glob below finds it at build time, so adding a language (by hand or from
 * Weblate) needs no code change. English is bundled; every other catalog is a
 * lazy chunk loaded only when that language is picked.
 *
 * The choice is per browser (localStorage), not a server setting: two people
 * sharing one Comicarr can read it in different languages.
 */
import { i18n, type Messages } from "@lingui/core";
import { messages as englishMessages } from "@/locales/en/messages.po";

export const SOURCE_LOCALE = "en";
const STORAGE_KEY = "comicarr.locale";

// English is bundled above, so it is excluded here to keep it out of a
// second chunk.
const loaders = import.meta.glob<{ messages: Messages }>([
  "../locales/*/messages.po",
  "!../locales/en/messages.po",
]);

function localeOf(path: string): string {
  const parts = path.split("/");
  return parts[parts.length - 2] ?? SOURCE_LOCALE;
}

/** Every locale with a catalog, English first. */
export const AVAILABLE_LOCALES: string[] = [
  SOURCE_LOCALE,
  ...Object.keys(loaders).map(localeOf).sort(),
];

/** The language's own name for itself: "Deutsch", "日本語". */
export function localeName(locale: string): string {
  try {
    const name = new Intl.DisplayNames([locale], { type: "language" }).of(
      locale,
    );
    if (name) return name.charAt(0).toLocaleUpperCase(locale) + name.slice(1);
  } catch {
    // An unknown tag: fall back to the tag itself.
  }
  return locale;
}

function readStored(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStored(locale: string) {
  try {
    window.localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // Private mode or blocked storage: the choice lasts for this tab only.
  }
}

/**
 * Best available match for a list of preferred tags: an exact match first
 * ("pt-BR"), then the base language ("pt-BR" → "pt"), then any regional
 * catalog of that language ("pt" → "pt-BR").
 */
export function matchLocale(
  preferred: readonly string[],
  available: readonly string[] = AVAILABLE_LOCALES,
): string {
  const lower = available.map((locale) => locale.toLowerCase());
  for (const tag of preferred) {
    const wanted = tag.toLowerCase();
    const exact = lower.indexOf(wanted);
    if (exact !== -1) return available[exact];
    const base = wanted.split("-")[0];
    const baseIndex = lower.indexOf(base);
    if (baseIndex !== -1) return available[baseIndex];
    const regional = lower.findIndex((locale) => locale.startsWith(`${base}-`));
    if (regional !== -1) return available[regional];
  }
  return SOURCE_LOCALE;
}

/** The saved choice if it still exists, otherwise the browser's languages. */
export function detectLocale(): string {
  const stored = readStored();
  if (stored && AVAILABLE_LOCALES.includes(stored)) return stored;
  const browser =
    typeof navigator === "undefined"
      ? []
      : navigator.languages?.length
        ? navigator.languages
        : [navigator.language];
  return matchLocale(browser.filter(Boolean));
}

async function loadMessages(locale: string): Promise<Messages> {
  if (locale === SOURCE_LOCALE) return englishMessages;
  const loader = Object.entries(loaders).find(
    ([path]) => localeOf(path) === locale,
  )?.[1];
  if (!loader) return englishMessages;
  return (await loader()).messages;
}

/** Load and switch to a locale, and mark the document with it. */
export async function activateLocale(locale: string): Promise<void> {
  const target = AVAILABLE_LOCALES.includes(locale) ? locale : SOURCE_LOCALE;
  const messages = await loadMessages(target);
  i18n.loadAndActivate({ locale: target, messages });
  if (typeof document !== "undefined") {
    document.documentElement.lang = target;
  }
}

/** The user picked a language: remember it and switch. */
export async function chooseLocale(locale: string): Promise<void> {
  writeStored(locale);
  await activateLocale(locale);
}

/**
 * Activate English synchronously so the first render never shows message ids,
 * then switch to the detected language if it is a different one.
 */
export function initI18n(): Promise<void> {
  i18n.loadAndActivate({ locale: SOURCE_LOCALE, messages: englishMessages });
  if (typeof document !== "undefined") {
    document.documentElement.lang = SOURCE_LOCALE;
  }
  const detected = detectLocale();
  return detected === SOURCE_LOCALE
    ? Promise.resolve()
    : activateLocale(detected);
}

export { i18n };
