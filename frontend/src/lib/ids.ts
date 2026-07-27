/**
 * Client-side identifier for records that only exist until the server answers.
 *
 * `crypto.randomUUID` is defined only in secure contexts, and a self-hosted
 * Comicarr is commonly served over plain HTTP — calling it directly there
 * throws. `getRandomValues` carries no such restriction, so it is the fallback.
 */
export function createLocalId(): string {
  if (typeof crypto !== "undefined") {
    if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
    if (typeof crypto.getRandomValues === "function") {
      return Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
        byte.toString(16).padStart(2, "0"),
      ).join("");
    }
  }
  return `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`;
}
