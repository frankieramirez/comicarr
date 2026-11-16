import { useLingui } from "@lingui/react";
import { localeDirection } from "@/lib/intl";

/**
 * Writing direction of the language the UI is in. Use it only for the few
 * things CSS logical properties cannot express, such as which physical side a
 * sheet slides in from. Spacing and alignment use logical classes instead.
 */
export function useDirection(): "ltr" | "rtl" {
  const { i18n } = useLingui();
  return localeDirection(i18n.locale);
}
