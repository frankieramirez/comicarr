---
"comicarr": patch
---

The web UI stays responsive while "Override and grab this release" is processing. The grab's revalidation and download-client handoff now run off the server's request loop, so other tabs and pages load normally instead of hanging until the grab finishes or fails. The same fix covers starting an Interactive release search, series "Search all missing", single-issue search, and AI story arc generation. Grabbing a release while another grab is still processing now answers immediately with "Another release grab is already being processed" instead of silently waiting its turn.
