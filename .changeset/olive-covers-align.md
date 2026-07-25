---
"comicarr": patch
---

Fix MyAnimeList cover art being blocked by the browser security policy. The
list of hosts trusted to serve cover images and the Content-Security-Policy
that permits the browser to load them are now derived from one source, so they
cannot drift apart again.
