---
"comicarr": minor
---

The dashboard now says a download client or indexer is ready only after it has answered a connection check. Before, "Ready to download" and "indexers responding" only meant the settings were filled in, so an unreachable SABnzbd could show as ready. A failed check now shows its reason with a link to fix it, and Comicarr checks again right after you save client or indexer settings. Each Newznab and Torznab indexer has its own Test button in Settings, and adding an indexer switches its group on, so a new indexer is never saved unused.
