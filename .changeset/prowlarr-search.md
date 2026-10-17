---
"comicarr": minor
---

Comicarr can search through Prowlarr directly. Under Settings → Search → Prowlarr, turn on "Search with Prowlarr" and enter your Prowlarr URL and API key. Test Connection then reports how many torrent indexers Prowlarr has enabled. Comicarr sends one search to Prowlarr, which asks all of its indexers and skips any it knows are failing, so one broken indexer no longer holds up a search. Prowlarr appears as a single provider named Prowlarr, which you can exclude for a Series like any other provider. Only torrent results are used; keep usenet indexers as Newznab indexers. Torrent search must be on, as it already must be for Torznab indexers. The default category is 7030 (comics); add 7010 to include magazines. An existing indexer named "Prowlarr" must be renamed before Prowlarr search can be turned on.
