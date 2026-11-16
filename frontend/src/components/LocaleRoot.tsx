import { DirectionProvider } from "@base-ui/react/direction-provider";
import { useLingui } from "@lingui/react";
import App from "@/App";
import { localeDirection } from "@/lib/intl";

// Switching language remounts the app under a new key, so every string is
// re-read, including text built by `t` from @lingui/core/macro outside a
// component that subscribes to the locale. Server data survives: the React
// Query client lives at module scope in App.tsx. The direction provider tells
// Base UI popups which way `inline-start` and `inline-end` point.
export default function LocaleRoot() {
  const { i18n } = useLingui();
  return (
    <DirectionProvider direction={localeDirection(i18n.locale)}>
      <App key={i18n.locale} />
    </DirectionProvider>
  );
}
