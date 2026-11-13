---
"comicarr": patch
---

Restarting Comicarr no longer marks open NZBGet downloads as gone and blocklists them. Comicarr saved NZBGet's job ID as text but NZBGet reports it as a number, so the restart check never found the job. It now matches the job, and a download that is still running is picked up from NZBGet's queue instead of only its history, so monitoring resumes where it left off.
