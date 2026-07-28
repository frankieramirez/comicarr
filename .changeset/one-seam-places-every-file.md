---
"comicarr": patch
---

Add a single file placement stage that reads the file operation setting at call time. Callers pass intent — what the file is for, and what to do if the destination is occupied — instead of a resolved mode, so no caller can bind a stale setting and place a file the wrong way. Nothing routes through it yet.
