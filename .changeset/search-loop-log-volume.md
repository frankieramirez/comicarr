---
"comicarr": patch
---

Search no longer fills the log with one Info line per provider and alternate name. At the default Info level you get one summary per issue, naming the providers and alternate names tried and whether it was found, and new installs keep 50 MB per log file so a few hours of history survive rotation. Set the log level to Debug (2) to see the per-provider and per-alternate-name lines again.
