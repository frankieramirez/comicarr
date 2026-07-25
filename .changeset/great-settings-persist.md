---
"comicarr": patch
---

Fix saving settings failing whenever the RSS check interval or database update
interval was changed. Both fields were sent under names the configuration did
not recognise, which rolled back the entire save — every other setting changed
at the same time was discarded without a visible error.

Interval changes now also reach the running scheduler, which they never did, so
a new search or RSS cadence takes effect without a restart. The database update
interval is a real setting now and survives a restart instead of resetting to 24
hours.
