---
"comicarr": patch
---

The Metron Password field in Settings → API now actually saves. `METRON_PASSWORD` was never registered as writable, so every save silently dropped it — the "Password saved" indicator could only ever reflect a value set outside the UI. The password is stored encrypted like the other secrets, and an empty field leaves a previously saved password unchanged.
