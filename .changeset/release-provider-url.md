---
"comicarr": patch
---

The weekly pull list works again. Its source, walksoftly.itsaninja.party, went offline and answered every request with a Cloudflare 523, so Releases fell back to ComicVine. Comicarr now uses the replacement service that Mylar3 moved to, `https://talkhard.notaninja.party`, which serves the same API. The base URL is a new `release_provider_url` setting in the `[Weekly]` section of `config.ini`, so it can be changed without a new release if the source moves again.
