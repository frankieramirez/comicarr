/**
 * What the last connection check says about a kind of connection, pure.
 *
 * "Configured" is not "working": a download client or indexer is only ready
 * once it has answered a check. The backend runs the checks right after a
 * save, when the app starts, and every hour (`app/system/connections.py`).
 */

import type { ConnectionCheck } from "@/hooks/useAcquisitionHealth";

export type ConnectionVerdict =
  /** Nothing of this kind can be checked (for example GetComics). */
  | { state: "none" }
  /** At least one answered its last check. */
  | { state: "ok"; rows: ConnectionCheck[] }
  /** None answered: every checked one failed. `row` is the first failure. */
  | { state: "failed"; row: ConnectionCheck }
  /** Configured, and not checked yet (just saved, or just restarted). */
  | { state: "unchecked"; rows: ConnectionCheck[] };

export function connectionVerdict(
  connections: ConnectionCheck[] | null | undefined,
  kind: "client" | "indexers",
): ConnectionVerdict {
  const rows = (connections ?? []).filter((row) => row.kind === kind);
  if (rows.length === 0) return { state: "none" };
  const ok = rows.filter((row) => row.ok === true);
  if (ok.length > 0) return { state: "ok", rows: ok };
  const failed = rows.find((row) => row.ok === false);
  if (failed) return { state: "failed", row: failed };
  return { state: "unchecked", rows };
}
