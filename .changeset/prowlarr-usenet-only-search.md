---
"comicarr": patch
---

Searches now run when Prowlarr's **Include Usenet indexers** is your only search source. Before, Auto-Search, forced searches and the RSS check logged "There are no search providers enabled" and searched nothing, even though Activity → Health showed a working route, unless at least one Newznab indexer was also turned on. You can now turn your Newznab indexers off and search them through Prowlarr alone. The RSS check still has nothing to match for Prowlarr, because Prowlarr has no RSS feed; its results come from the regular searches.
