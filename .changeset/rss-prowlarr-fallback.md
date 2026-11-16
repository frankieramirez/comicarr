---
"comicarr": patch
---

RSS checks pick up new releases from Prowlarr indexers again. Comicarr asked each Prowlarr indexer for an `/rss` page that Prowlarr doesn't have. Prowlarr answered with its own web page, so every pass logged "0 entries indexed" and never tried the indexer's API. Comicarr now notices when a response isn't a feed and uses the API instead. A GetComics post in an unexpected layout no longer stops the RSS check before it looks for your wanted issues.
