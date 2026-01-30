import { useEffect } from 'react';

/**
 * Hook to set up global keyboard shortcuts
 * Uses native event listeners (no dependencies required)
 */
export function useKeyboardShortcuts() {
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ignore shortcuts when user is typing in an input, textarea, or contenteditable
      const activeElement = document.activeElement;
      const isTyping =
        activeElement?.tagName === 'INPUT' ||
        activeElement?.tagName === 'TEXTAREA' ||
        activeElement?.isContentEditable;

      // '/' - Focus search input (unless already typing)
      if (e.key === '/' && !isTyping && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();

        // Try to find and focus the search input
        const searchInput = document.querySelector('input[type="search"]') ||
                          document.querySelector('input[placeholder*="Search"]') ||
                          document.querySelector('input[placeholder*="search"]');

        if (searchInput) {
          searchInput.focus();
          console.log('[Keyboard] Focused search input');
        }
        return;
      }

      // 'Escape' - Close modals/dialogs, blur active input
      if (e.key === 'Escape') {
        // If an input is focused, blur it
        if (isTyping) {
          activeElement.blur();
          console.log('[Keyboard] Blurred active input');
          return;
        }

        // Look for open modals/dialogs and close them
        // shadcn/ui dialogs use [data-state="open"] attribute
        const openDialog = document.querySelector('[role="dialog"][data-state="open"]');
        if (openDialog) {
          // Find and click the close button
          const closeButton = openDialog.querySelector('button[aria-label*="Close"]') ||
                            openDialog.querySelector('button[data-dismiss]') ||
                            openDialog.querySelector('button.close');
          if (closeButton) {
            closeButton.click();
            console.log('[Keyboard] Closed dialog');
          }
        }
        return;
      }

      // 'Ctrl+K' or 'Cmd+K' - Quick navigation (future enhancement)
      // Commented out for now, can be implemented later with a command palette
      /*
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        // Open command palette / quick nav
        console.log('[Keyboard] Quick nav triggered');
        return;
      }
      */
    };

    // Add event listener
    window.addEventListener('keydown', handleKeyDown);

    console.log('[Keyboard] Shortcuts enabled: "/" to focus search, "Esc" to close dialogs');

    // Cleanup
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      console.log('[Keyboard] Shortcuts disabled');
    };
  }, []);
}
