import { useLingui } from "@lingui/react";
import App from "@/App";

// Switching language remounts the app under a new key, so every string is
// re-read, including text built by `t` from @lingui/core/macro outside a
// component that subscribes to the locale. Server data survives: the React
// Query client lives at module scope in App.tsx.
export default function LocaleRoot() {
  const { i18n } = useLingui();
  return <App key={i18n.locale} />;
}
