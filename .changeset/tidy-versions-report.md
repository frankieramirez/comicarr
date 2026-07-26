---
"comicarr": patch
---

Fix the version and update-available information never changing after startup.
The scheduled version check wrote to a copy of the state that the API does not
read, so a new release was never reported once the process was running. The
branch name, which nothing ever set, is now reported too. A version check that
fails to reach GitHub now keeps the last known result instead of reporting
"up to date".
