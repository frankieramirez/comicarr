---
"comicarr": patch
---

Fix post-processing failing for every numeric issue when zero-padding was enabled but no padding level was set. Completed downloads (reported against SABnzbd, but affecting all download routes) crashed with `postprocess_error:UnboundLocalError`, landed in needs-attention, and retrying the import failed the same way with only "No rows could be resolved" shown. An unset or unrecognized padding level now means no padding, so imports proceed. Post-processing failures also now log the full error and traceback instead of just the error's name, so the log tells you what actually went wrong.
