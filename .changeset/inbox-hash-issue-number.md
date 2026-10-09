---
"comicarr": patch
---

The import inbox now reads the issue number from filenames written with a `#`, such as `Midnight X-Men #001 (2026).cbz`. These files now get matched to their issue, renamed, and tagged with metadata, the same as `Midnight X-Men 001 (2026).cbz`. Before this fix they were moved into the series folder untagged.
