import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";
import { isMockEnabled } from "@/lib/mockData";

// Register/unregister the mock-mode service worker based on the current
// mock flag. Idempotent across reloads.
if (typeof window !== "undefined" && "serviceWorker" in navigator) {
  if (isMockEnabled()) {
    navigator.serviceWorker.register("/mock-sw.js").catch(() => {
      /* ignore — mock covers will fall back to broken-image icons */
    });
  } else {
    navigator.serviceWorker.getRegistrations().then((regs) => {
      const mockRegs = regs.filter((r) =>
        r.active?.scriptURL?.endsWith("/mock-sw.js"),
      );
      if (mockRegs.length === 0) return;
      Promise.all(mockRegs.map((r) => r.unregister())).then(() => {
        // An active SW continues to intercept fetches on the current page
        // until navigation/reload — reload so mock mode truly turns off.
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
