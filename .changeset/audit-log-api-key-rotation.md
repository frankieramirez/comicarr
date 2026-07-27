---
"comicarr": patch
---

Record API key regeneration as an audit log event with the user and originating IP. Rotation revokes every outstanding API credential, so integrations start failing immediately — previously nothing in the log explained why.
