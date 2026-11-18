---
"comicarr": minor
---

Three API routes that duplicated other routes are deprecated and will be removed in 1.0.0: `POST /api/metadata/search` (use `POST /api/search/comics`), `POST /api/metadata/search/manga` (use `POST /api/search/manga`) and `POST /api/ai/chat/stream` (use `POST /api/ai/chat/turns/stream`). They keep working until then. `POST /api/metadata/search/manga` now gives the same answer as `POST /api/search/manga`, so it also searches MyAnimeList when that is set up and marks the series already in your library. If a script or tool of yours still calls one of them, Comicarr logs a warning and lists it under **Activity → Health**. See [Deprecations](https://comicarr.com/docs/deprecations).
