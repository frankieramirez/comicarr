---
"comicarr": patch
---

Three API routes that duplicated other routes are removed. A script that called one should switch: `POST /api/metadata/search` to `POST /api/search/comics`, `POST /api/metadata/search/manga` to `POST /api/search/manga` (same request body for both), and `POST /api/ai/chat/stream` to `POST /api/ai/chat/turns/stream`. The Comicarr web app never used the removed routes, so nothing changes there.
