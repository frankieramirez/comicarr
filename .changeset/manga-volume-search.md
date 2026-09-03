---
"comicarr": patch
---

Manga series tracked by volume now actually grab the releases they find. A volume-numbered series would run every search, receive the correct results from the provider, and snatch none of them — five separate gates each discarded the release, so the series sat permanently Wanted with nothing to show for it. Volume searches now query the volume name the way the RSS path already did, match results against the real series name, and accept a release on its volume number rather than demanding an issue number the release never carries. Half volumes such as v01.5 keep their fraction instead of being searched and matched as v01.
