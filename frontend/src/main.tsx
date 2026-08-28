import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
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
