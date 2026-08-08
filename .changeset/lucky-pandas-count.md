---
"comicarr": minor
---

The dashboard now says how much work is moving right now, across every download route — one line reading "12 in flight", and "12 in flight (3 recovered from a restart)" when some of that work has already survived a restart. The two figures are never added together: the recovered ones are part of the total, not extra.

The **Queue** tile is gone. It counted direct downloads only, so an operator running SABnzbd saw "0 queued" while SABnzbd was actively downloading — a claim the dashboard could not back. The in-flight line answers the same question honestly for every route, and it reads the same source as the status indicator in the footer, so the two can never disagree. If that source cannot be read, the line says so instead of reporting a quiet system.
