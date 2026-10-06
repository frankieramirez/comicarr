---
"comicarr": patch
---

Direct downloads that stall no longer sit in Downloading forever. After the stuck threshold Comicarr resumes them when auto-resume is on and the source link still works, or marks them Failed (and re-queues the issue as Wanted when failed-download handling is on). A download still Downloading after 24 hours (`ddl_stuck_expiry`, minutes) is always failed. Stuck notifications no longer repeat after a restart.
