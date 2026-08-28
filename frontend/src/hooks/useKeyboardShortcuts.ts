import { useEffect } from "react";

/**
 * Hook to set up global keyboard shortcuts
 * Uses native event listeners (no dependencies required)
 */
export function useKeyboardShortcuts(): void {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const activeElement = document.activeElement as HTMLElement | null;
      const isTyping =
        activeElement?.tagName === "INPUT" ||
        activeElement?.tagName === "TEXTAREA" ||
        activeElement?.isContentEditable;

      if (e.key === "/" && !isTyping && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();

        const searchInput =
          document.querySelector<HTMLInputElement>('input[type="search"]') ||
          document.querySelector<HTMLInputElement>(
            'input[placeholder*="Search"]',
          ) ||
          document.querySelector<HTMLInputElement>(
            'input[placeholder*="search"]',
          ) ||
          document.querySelector<HTMLInputElement>(
            'input[placeholder*="Filter"]',
          ) ||
          document.querySelector<HTMLInputElement>(
            'input[placeholder*="filter"]',
          );

        if (searchInput) {
          searchInput.focus();
          console.log("[Keyboard] Focused search input");
        }
        return;
      }

      if (e.key === "Escape") {
        if (isTyping && activeElement) {
          activeElement.blur();
          console.log("[Keyboard] Blurred active input");
          return;
        }

        const openDialog = document.querySelector(
          '[role="dialog"][data-state="open"]',
        );
        if (openDialog) {
          const closeButton =
            openDialog.querySelector<HTMLButtonElement>(
              'button[aria-label*="Close"]',
            ) ||
            openDialog.querySelector<HTMLButtonElement>(
              "button[data-dismiss]",
            ) ||
            openDialog.querySelector<HTMLButtonElement>("button.close");
          if (closeButton) {
            closeButton.click();
            console.log("[Keyboard] Closed dialog");
          }
        }
        return;
      }

      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        const globalSearch = document.querySelector<HTMLInputElement>(
          'input[data-global-search="true"]',
        );
        if (globalSearch) {
          globalSearch.focus();
          globalSearch.select();
        }
        return;
      }
    };

    window.addEventListener("keydown", handleKeyDown);

    console.log(
      '[Keyboard] Shortcuts enabled: "/" to focus search, "Esc" to close dialogs',
    );

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      console.log("[Keyboard] Shortcuts disabled");
    };
  }, []);
}
