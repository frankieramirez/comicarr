/** Print copies on the shelf (`/api/shelf`). */

/** The item a copy belongs to: an issue or annual by id, or a manga volume by number. */
export interface ShelfItem {
  ComicID: string;
  ItemID?: string;
  VolumeNumber?: string;
}

/** What an operator records about one copy. Every field is optional. */
export interface ShelfCopyFields {
  VariantName: string | null;
  Grade: string | null;
  PaidCents: number | null;
  Storage: string | null;
  Notes: string | null;
}

export interface ShelfCopy extends ShelfCopyFields {
  CopyID: string;
  ComicID: string;
  ItemID: string | null;
  VolumeNumber: string | null;
  SeriesName: string | null;
  ItemLabel: string | null;
  CoverURL: string | null;
  /** False once the series was removed from the library; the copy stays. */
  SeriesPresent: boolean;
  created_at: string;
  updated_at: string;
}

export interface ShelfCopyPage {
  results: ShelfCopy[];
  total: number;
  /** What was paid for every match, not only this page. */
  paid_cents: number;
  limit: number;
  offset: number;
}

/** How many copies each item of one series has. */
export interface SeriesShelf {
  issues: Record<string, number>;
  volumes: Record<string, number>;
}
