---
"comicarr": patch
---

SABnzbd jobs that finish with a missing file, a job SAB no longer has, or a failure while Failed download handling is off now go to Needs Attention. Failures while handling is on retry as usual. A job still Repairing or Moving is checked again without stalling the rest of the NZB monitor.
