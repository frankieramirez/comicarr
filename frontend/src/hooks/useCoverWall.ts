import { useEffect, useState } from "react";
import { apiRequest } from "@/lib/api";

interface CoverWallResponse {
  enabled: boolean;
  tiles: number;
}

/**
 * The opt-in wall of the library's own covers behind the sign-in card
 * (Settings > Interface). The server picks safe, cached covers and serves
 * them by slot, so this page never learns titles, ids or counts beyond the
 * tiles it draws. Renders nothing when the wall is off or empty, and the
 * caller falls back to the grid backdrop.
 */
export function useCoverWall(): number {
  const [tiles, setTiles] = useState(0);
  useEffect(() => {
    let live = true;
    apiRequest<CoverWallResponse>("GET", "/api/auth/cover-wall")
      .then((result) => {
        if (live && result?.enabled) setTiles(Math.max(0, result.tiles || 0));
      })
      .catch(() => {
        // The wall is decoration; a failed read just leaves the backdrop.
      });
    return () => {
      live = false;
    };
  }, []);
  return tiles;
}
