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
      regs.forEach((r) => {
        if (r.active?.scriptURL?.endsWith("/mock-sw.js")) {
          r.unregister();
        }
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
