---
"comicarr": patch
---

Deprecated Activity preview and Downloads needs-attention compatibility routes stay until 0.50.0. Custom scripts that still call them keep working; move to GET /api/attention and POST /api/attention/resolve before then.
