/**
 * Safe composite row ids.
 *
 * A row id must be unique and stable, and #359 narrows `getRowId` to
 * `(row) => string` so it can never fall back to TanStack's index default.
 * Tables whose identity is a composite then have to join several fields into
 * one string, and a bare join is ambiguous the moment a field can contain the
 * delimiter. Two live cases (#383, #364):
 *
 *   - download history keys on `(IssueID, Status, Provider)`, and `Status`
 *     takes the literal value `Post-Processed`;
 *   - the import table's key was `` `${DynamicName}-${Volume || "null"}` ``,
 *     which collapsed `null` and `""` even though SQL groups them separately
 *     (fixed by #396's `getImportGroupRowId`).
 *
 * So the encoder is shared rather than fixed per site: the class is the bug,
 * not either instance.
 *
 * Each part is tagged (`s` present, `n` absent) and percent-encoded, then
 * joined with `|`. `encodeURIComponent` escapes `|` to `%7C`, so no encoded
 * part can contain the delimiter and the split is unambiguous for any input.
 * The tag keeps `null` distinct from `""` and from the string `"null"`.
 */
export function encodeRowId(
  parts: readonly (string | number | null | undefined)[],
): string {
  return parts
    .map((part) =>
      part === null || part === undefined
        ? "n"
        : `s${encodeURIComponent(String(part))}`,
    )
    .join("|");
}
