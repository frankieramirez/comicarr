---
"comicarr": patch
---

Importing from Mylar3 no longer turns settings left unset in Mylar3 into the literal value "None". Unset passwords and API keys stay empty instead of becoming a stored password of "None", and the web login no longer accepts "None" as the password. The import also stops copying Mylar3's own config version, so the first restart after an import no longer turns a 1-minute search delay into 1 hour or switches update checks back on.
