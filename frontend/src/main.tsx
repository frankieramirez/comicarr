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
import App from "./App";
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

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
