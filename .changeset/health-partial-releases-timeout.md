---
"comicarr": patch
---

Activity → Health no longer makes a partly failed job look like a success. When a search, RSS check, import or library refresh had some failures, or a connection did not answer, the job shows a warning with the counts (for example "1 grabbed of 3 searched, 2 failed"). A job that reports nothing now says so instead of "Finished without errors". Releases stops waiting after 30 seconds and shows an error with Retry instead of loading forever, and the page heading names the week you are looking at.
