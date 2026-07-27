/**
 * The chat rename/delete prompts are raised from both the workspace header and
 * the thread rail. Keeping the copy here stops the two from drifting apart.
 */

/** Returns the new title, or null when cancelled or unchanged. */
export function promptChatTitle(currentTitle: string): string | null {
  const title = window.prompt("Rename chat", currentTitle)?.trim();
  if (!title || title === currentTitle) return null;
  return title;
}

export function confirmChatDelete(title: string): boolean {
  return window.confirm(`Delete “${title}”? This also removes its images.`);
}
