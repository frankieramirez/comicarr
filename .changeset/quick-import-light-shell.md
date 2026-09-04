---
"comicarr": patch
---

Speed up large import queues by batching file reads on SQLite. Reduce startup JavaScript by loading table code and optional dialogs only when needed, and remove background chat-thread and closed activity-drawer requests.
