# ADR-0004: Manga chapter and volume ledgers

MangaDex is the sole ledger source. Volumes are first-class rows with ids `{comicId}-v{n}`, not issues with a type discriminator — issue Status, attention, and Have/Total assume one row kind, and stuffing volumes there would leak manga into comic paths. Chapters stay in `issues` as `{comicId}-ch{n}`.

The volume roster comes from `GET /cover?manga[]={uuid}` (complete even when `/aggregate` has holes). `/aggregate` is unfiltered and supplies chapter rows plus *partial* volume→chapter containment. A volume in the cover feed but absent from aggregate is released with unknown contents: owning it does not mark unknown chapters Covered-by-volume.

Covered-by-volume is fulfillment `covered`, distinct from Have. Explicit skip/ignore and in-flight/downloaded states win. Refresh upserts by those stable ids and never overwrites operator Status, AcquisitionIntent, or Location.

Last released volume is `max(cover volume number)`. Series progress is the blended frontier: owned released volumes plus owned-or-covered chapters beyond that volume, over released volumes plus those later chapters.
