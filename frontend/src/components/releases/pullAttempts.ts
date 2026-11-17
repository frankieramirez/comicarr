import { t } from "@lingui/core/macro";
import type { PullAttempt } from "@/pages/weeklyReleaseRowKey";

/** One sentence per pull-list source that did not fill the week. */
function describeAttempt({ source, reason }: PullAttempt): string | null {
  if (source === "walksoftly") {
    return t`The built-in release calendar could not be reached. It needs no setup, and Comicarr tries it again on the next refresh.`;
  }
  if (source === "metron") {
    if (reason === "not_configured")
      return t`Metron is not set up as a backup. Add your Metron login in Settings to use it.`;
    if (reason === "no_releases")
      return t`Metron lists no comics for this week yet.`;
    return t`Metron could not be reached.`;
  }
  if (source === "comicvine") {
    if (reason === "not_configured")
      return t`ComicVine has no API key in Settings.`;
    if (reason === "no_releases")
      return t`ComicVine lists no comics for this week yet.`;
    if (reason === "filtered_out")
      return t`Every ComicVine release this week is from a publisher you ignore.`;
    return t`ComicVine could not be reached.`;
  }
  return null;
}

/** Why the week's comics are missing, as sentences, or null when unknown. */
export function describePullAttempts(
  attempts: PullAttempt[] | undefined,
): string | null {
  const sentences = (attempts ?? [])
    .map(describeAttempt)
    .filter((s): s is string => Boolean(s));
  return sentences.length ? sentences.join(" ") : null;
}
