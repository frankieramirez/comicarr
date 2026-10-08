/**
 * Shared CSS-grid column convention for list views that are not yet on
 * `useTableState`.
 *
 * Phone templates keep the title (and one status/action track). Secondary
 * columns use `DESKTOP_COL` so they leave the grid below `md` instead of
 * shrinking the title to a few pixels.
 *
 * `max-md:hidden` leaves the element's own display (block/flex/inline-flex)
 * intact at md+, unlike `hidden md:block` which fights flex utilities.
 */

export const DESKTOP_COL = "max-md:hidden";
