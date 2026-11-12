/** Fired by the global ⌘K shortcut; `CommandPalette` is the only listener. */
export const OPEN_PALETTE_EVENT = "comicarr:open-palette";

export function openCommandPalette(): void {
  window.dispatchEvent(new Event(OPEN_PALETTE_EVENT));
}
