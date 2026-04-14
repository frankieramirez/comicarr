import type { Comic } from "@/types";

export function getProgressPercentage(comic: Comic): number {
  const total = parseInt(String(comic.Total)) || 0;
  const have = parseInt(String(comic.Have)) || 0;
  return total > 0 ? Math.round((have / total) * 100) : 0;
}

export function getProgressCategory(comic: Comic): "0" | "partial" | "100" {
  const percentage = getProgressPercentage(comic);
  if (percentage === 0) return "0";
  if (percentage === 100) return "100";
  return "partial";
}
