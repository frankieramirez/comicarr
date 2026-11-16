import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Bundled so they load under the app's own font-src 'self' policy.
import "@fontsource/inter-tight/latin-400.css";
import "@fontsource/inter-tight/latin-ext-400.css";
import "@fontsource/inter-tight/latin-500.css";
import "@fontsource/inter-tight/latin-ext-500.css";
import "@fontsource/inter-tight/latin-600.css";
import "@fontsource/inter-tight/latin-ext-600.css";
import "@fontsource/inter-tight/latin-700.css";
import "@fontsource/inter-tight/latin-ext-700.css";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-ext-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";
import "@fontsource/jetbrains-mono/latin-ext-500.css";
import "./index.css";
import { I18nProvider } from "@lingui/react";
import LocaleRoot from "@/components/LocaleRoot";
import { i18n, initI18n } from "@/lib/i18n";
import { isMockEnabled } from "@/lib/mockData";

if (typeof window !== "undefined" && "serviceWorker" in navigator) {
  if (isMockEnabled()) {
    navigator.serviceWorker.register("/mock-sw.js").catch(() => {});
  } else {
    navigator.serviceWorker.getRegistrations().then((regs) => {
      const mockRegs = regs.filter((r) =>
        r.active?.scriptURL?.endsWith("/mock-sw.js"),
      );
      if (mockRegs.length === 0) return;
      Promise.all(mockRegs.map((r) => r.unregister())).then(() => {
        if (navigator.serviceWorker.controller) window.location.reload();
      });
    });
  }
}

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("Failed to find the root element");

// English is active synchronously; a saved or browser language that has a
// catalog loads before the first paint, so the UI never flashes English first.
void initI18n().finally(() => {
  createRoot(rootElement).render(
    <StrictMode>
      <I18nProvider i18n={i18n}>
        <LocaleRoot />
      </I18nProvider>
    </StrictMode>,
  );
});
