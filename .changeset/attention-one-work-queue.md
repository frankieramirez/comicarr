---
"comicarr": minor
---

Needs attention now uses one actionable work queue everywhere. The Activity
preview, Dashboard count, triage view, and resolution actions share the same
membership and action rules, so self-recoverable failures no longer appear in
one place while disappearing from another.

Custom integrations should move to `GET /api/attention` and
`POST /api/attention/resolve`. The existing Activity preview and Downloads
resolution routes remain available for this release and will be removed in the
next release. `GET /api/downloads/needs-attention` is already gone in this
release with no deprecation window — scripts polling it should switch to
`GET /api/attention` now.
