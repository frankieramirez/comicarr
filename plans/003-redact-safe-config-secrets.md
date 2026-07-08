# Plan 003: Redact long-lived secrets from safe config responses

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report - do not improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b6d743ea..HEAD -- comicarr/app/system/service.py tests/unit/test_system_domain.py frontend/src/pages/SettingsPage.tsx frontend/src/components/settings frontend/src/types/config.ts frontend/tests`
> If any in-scope file changed since this plan was written, compare the "Current state" excerpts against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/002-add-dedicated-api-key-regeneration.md
- **Category**: security
- **Planned at**: commit `b6d743ea`, 2026-07-07

## Why this matters

`get_safe_config()` is documented as returning no passwords or keys, but it currently includes several long-lived secrets. The frontend then stores that config in TanStack Query for 10 minutes and renders the values in settings fields. Redacting secrets reduces the blast radius of browser compromise, screenshots, devtools exposure, and future XSS bugs while preserving settings editability through replace-only inputs.

## Current state

- `comicarr/app/system/service.py` - safe config docstring says no passwords/keys, but `safe_keys` includes key-like fields.
- `frontend/src/hooks/useConfig.ts` - caches `/api/config` for 10 minutes.
- `frontend/src/components/settings/ApiTab.tsx` - displays/copies raw API and Comic Vine keys.
- `frontend/src/components/settings/NotificationsTab.tsx` - displays raw webhook or key fields for several notification services.
- `tests/unit/test_system_domain.py` - currently asserts that `api_key` is included in safe config.

Relevant excerpts:

```text
service.py:162-163
def get_safe_config(ctx):
    """Return configuration as a safe dict (no passwords/keys)."""
```

```text
service.py:196-211
"COMICVINE_API",
...
"API_KEY",
```

```text
service.py:235-263
"PROWL_KEYS",
...
"SLACK_WEBHOOK_URL",
"MATTERMOST_WEBHOOK_URL",
"DISCORD_WEBHOOK_URL",
```

```text
service.py:287-307
# AI API key: include boolean indicator, not the actual key
result["ai_api_key_set"] = bool(ai_key and ai_key != "None")
...
result["metron_password_set"] = bool(metron_pw)
...
result["MAL_CLIENT_ID_SET"] = bool(mal_key and mal_key != "None")
```

```text
useConfig.ts:12-18
return useQuery({
  queryKey: ["config"],
  queryFn: () => apiRequest<Config>("GET", "/api/config"),
  staleTime: 10 * 60 * 1000,
})
```

Repo conventions to match:

- Use lowercase frontend config keys; `get_safe_config()` lowercases result keys at `service.py:309-310`.
- Existing secret indicators use the `<field>_set` pattern for frontend display.
- Settings save already has replace-only handling for `ai_api_key` in `SettingsPage.tsx:108-111`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend tests | `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_system_domain.py -q -p no:cacheprovider` | all pass |
| Backend lint | `./.venv/bin/ruff check --no-cache comicarr/app/system tests/unit/test_system_domain.py` | exit 0 |
| Frontend typecheck | `cd frontend && npm run typecheck` | exit 0 |
| Frontend lint | `cd frontend && npm run lint` | exit 0 |
| Frontend tests | `cd frontend && npm run test:run -- settings` | affected settings tests pass, or Vitest reports no matching tests only if none exist yet |

## Scope

**In scope**:

- `comicarr/app/system/service.py`
- `tests/unit/test_system_domain.py`
- `frontend/src/pages/SettingsPage.tsx`
- `frontend/src/components/settings/ApiTab.tsx`
- `frontend/src/components/settings/NotificationsTab.tsx`
- `frontend/src/types/config.ts`
- Focused frontend settings tests, if needed

**Out of scope**:

- Changing how secrets are encrypted at rest
- Redacting provider credentials not currently returned by `get_safe_config()`
- Changing authentication or CSRF middleware
- API-key regeneration itself; that is plan 002
- Displaying or writing real secret values in tests or docs

## Git workflow

- Branch: `fix/redact-safe-config-secrets`
- Commit message style: `fix: redact secrets from settings config response`
- Do not push or open a PR unless instructed.

## Steps

### Step 1: Define the redaction inventory

In `comicarr/app/system/service.py`, identify fields in `safe_keys` that are secrets or credential-equivalent values. At minimum, remove these raw values from `safe_keys`:

- `API_KEY`
- `COMICVINE_API`
- `PROWL_KEYS`
- `SLACK_WEBHOOK_URL`
- `MATTERMOST_WEBHOOK_URL`
- `DISCORD_WEBHOOK_URL`

Also inspect `safe_keys` for any other token, password, API key, webhook, passkey, or access-token fields that may have been added since this plan was written. Do not reproduce values in logs, tests, or comments.

**Verify**: `./.venv/bin/python - <<'PY'
from pathlib import Path
text = Path('comicarr/app/system/service.py').read_text()
for name in ['"API_KEY"', '"COMICVINE_API"', '"PROWL_KEYS"', '"SLACK_WEBHOOK_URL"', '"MATTERMOST_WEBHOOK_URL"', '"DISCORD_WEBHOOK_URL"']:
    print(name, text.count(name))
PY` -> each name should appear only where intentionally writable, indicator-derived, or tested. They should not remain in `safe_keys`.

### Step 2: Add indicator-only fields

Still in `get_safe_config()`, add boolean indicators for redacted fields, following the existing `ai_api_key_set` and `metron_password_set` pattern.

Required indicator names after lowercase conversion:

- `api_key_set`
- `comicvine_api_set`
- `prowl_keys_set`
- `slack_webhook_url_set`
- `mattermost_webhook_url_set`
- `discord_webhook_url_set`

Use a small local helper if it keeps the code readable, for example one that treats `None`, empty string, and `"None"` as unset. Keep the helper private to `service.py`.

**Verify**: `./.venv/bin/ruff check --no-cache comicarr/app/system/service.py` -> `All checks passed!`.

### Step 3: Preserve replace-only save behavior

Update `frontend/src/pages/SettingsPage.tsx` so save payloads do not overwrite existing redacted secrets with blank values. Generalize the current `ai_api_key` special case into a list/map of redacted fields and their `<field>_set` indicators.

Required behavior:

- If a redacted field is blank and its indicator is true, delete it from `saveData`.
- If a redacted field has a non-empty value, send it so users can replace the secret.
- If a redacted field is blank and its indicator is false, sending blank is acceptable only if that matches current backend semantics; otherwise omit it.
- Do not include raw `api_key` in this generic save flow; plan 002 owns regeneration.

**Verify**: `cd frontend && npm run typecheck` -> exit 0.

### Step 4: Update settings controls to show configured state without raw values

Update settings components so redacted fields are empty inputs with placeholders/help text such as "Configured - enter a new value to replace". Do not display raw keys or webhook URLs from `config`.

Specific adjustments:

- `ApiTab.tsx`: API key display should rely on plan 002's one-time regenerated value. `GET /api/config` should no longer be used to display or copy the persisted API key. Comic Vine key input should use `comicvine_api_set` for configured state and an empty editable value for replacement.
- `NotificationsTab.tsx`: Discord, Slack, Mattermost, and Prowl fields should use indicator fields for configured state and blank replacement inputs.
- `frontend/src/types/config.ts`: replace raw secret assumptions with optional indicator fields where useful.

**Verify**: `cd frontend && npm run lint` -> exit 0.

### Step 5: Update backend and frontend tests

Backend tests in `tests/unit/test_system_domain.py`:

- Replace `test_get_safe_config_includes_api_key` with tests that assert raw secret keys are absent.
- Assert every new `<field>_set` indicator is present and true/false based on placeholder secret values in the mock config.
- Keep tests for non-secret config fields.

Frontend tests:

- Add or update settings tests to assert configured secrets do not render raw values.
- Assert blank replacement fields are omitted from the save payload when the corresponding `_set` indicator is true.

Do not include real credentials in test fixtures.

**Verify**: backend and frontend test commands in this plan exit 0.

## Test plan

- Backend safe-config tests for raw-secret absence and indicator presence.
- Frontend settings save test for blank redacted fields.
- Frontend render test for configured placeholder state.

## Done criteria

- [ ] `GET /api/config` no longer returns raw API keys, Comic Vine API keys, Prowl keys, or Discord/Slack/Mattermost webhook URLs.
- [ ] Replacement inputs still allow users to update those secrets.
- [ ] Blank replacement inputs do not erase existing configured secrets.
- [ ] API-key regeneration remains available through plan 002's dedicated endpoint.
- [ ] Backend and frontend verification commands in this plan exit 0.
- [ ] No real secret value appears in code, tests, docs, or logs.
- [ ] No files outside the in-scope list are modified.
- [ ] `plans/README.md` status row updated.

## STOP conditions

Stop and report back if:

- Plan 002 has not landed and there is no alternate way for users to obtain a newly generated API key.
- The frontend depends on reading the persisted API key for a workflow other than display/copy in settings.
- A redacted field is required by a non-settings page that cannot work with indicator-only data.

## Maintenance notes

Future config fields should default to indicator-only exposure if their name includes key, token, password, webhook, secret, passkey, or credential. Reviewers should treat additions to `safe_keys` as a security-sensitive change.
