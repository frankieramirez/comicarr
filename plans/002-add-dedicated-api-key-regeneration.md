# Plan 002: Add a dedicated API key regeneration flow

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report - do not improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b6d743ea..HEAD -- comicarr/app/system/service.py comicarr/app/system/router.py tests/unit/test_system_domain.py frontend/src/components/settings/ApiTab.tsx frontend/src/hooks/useConfig.ts frontend/src/lib/api.ts frontend/tests`
> If any in-scope file changed since this plan was written, compare the "Current state" excerpts against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `b6d743ea`, 2026-07-07

## Why this matters

The settings UI currently lets a user generate a new API key locally, says to save it, and then sends it through the generic config update endpoint. The backend intentionally rejects `API_KEY` in that endpoint, so the UI can report success while the real API key remains unchanged. A dedicated authenticated regenerate endpoint preserves the security boundary while making the UI truthful.

## Current state

- `frontend/src/components/settings/ApiTab.tsx` - generates a local key and stores it in form state.
- `frontend/src/hooks/useConfig.ts` - contains an unused `useGenerateApiKey()` hook that also writes `api_key` through generic config.
- `comicarr/app/system/service.py` - generic config write allowlist excludes `API_KEY`.
- `comicarr/app/system/router.py` - exposes `/api/config` get/put endpoints.
- `tests/unit/test_system_domain.py` - explicitly asserts that generic config updates reject `api_key`.

Relevant excerpts:

```text
ApiTab.tsx:33-49
const handleRegenerateApiKey = async () => {
  ...
  const newApiKey = crypto.randomUUID().replace(/-/g, "");
  onChange("api_key", newApiKey);
  addToast({ message: "API key regenerated. Remember to save your changes!" });
}
```

```text
service.py:465-472
# Filter to only writable keys - prevents privilege escalation via
# overwriting HTTP_PASSWORD, API_KEY, AUTHENTICATION, etc.
rejected = [k for k in key_values if k not in WRITABLE_CONFIG_KEYS]
...
if not filtered:
    return {"success": False, "error": "No valid config keys provided"}
```

```text
test_system_domain.py:373-390
def test_update_config_rejects_sensitive_keys_regardless_of_case(self):
    ...
def test_update_config_filters_sensitive_keys_from_mixed_payload(self):
    ...
    assert "API_KEY" not in args
```

Repo conventions to match:

- System-domain business logic belongs in `comicarr/app/system/service.py`; routers should delegate to service functions.
- Router functions that do blocking work use `asyncio.to_thread`, as in `router.py:183-187`.
- Frontend data writes use `apiRequest()` and TanStack Query hooks.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend tests | `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_system_domain.py -q -p no:cacheprovider` | all pass |
| Backend lint | `./.venv/bin/ruff check --no-cache comicarr/app/system tests/unit/test_system_domain.py` | exit 0 |
| Frontend typecheck | `cd frontend && npm run typecheck` | exit 0, no TypeScript errors |
| Frontend lint | `cd frontend && npm run lint` | exit 0 |
| Frontend tests | `cd frontend && npm run test:run -- ApiTab` | new/affected tests pass |

## Scope

**In scope**:

- `comicarr/app/system/service.py`
- `comicarr/app/system/router.py`
- `tests/unit/test_system_domain.py`
- `frontend/src/components/settings/ApiTab.tsx`
- `frontend/src/hooks/useConfig.ts`
- `frontend/src/lib/api.ts` only if a typed helper is useful
- A focused frontend test for `ApiTab` if one does not already exist

**Out of scope**:

- Adding `API_KEY` to `WRITABLE_CONFIG_KEYS`
- Changing session authentication, JWT auth, or API key validation semantics
- Redacting all config secrets; that is plan 003
- Rotating existing users' API keys automatically

## Git workflow

- Branch: `fix/api-key-regeneration`
- Commit message style: `fix: add dedicated API key regeneration endpoint`
- Do not push or open a PR unless instructed.

## Steps

### Step 1: Add a service function that regenerates and persists the API key

In `comicarr/app/system/service.py`, add a function such as `regenerate_api_key(ctx)`.

Required behavior:

- Return `{"success": False, "error": "Config not loaded"}` if `ctx.config` is missing, matching `update_config`.
- Generate the new key server-side with `secrets.token_hex(16)` for a 32-character hex token, unless the existing config layer has a stronger established API-key generator. Do not use `crypto.randomUUID()` in the browser for the persisted secret.
- Set `ctx.config.API_KEY`, call `ctx.config.writeconfig()`, and call `ctx.config.configure(update=True, startup=False)` if that is required for config consistency.
- Sync `comicarr.CONFIG = ctx.config` during the transition, matching `update_config`.
- Return the new key only in this regenerate response, for immediate user copy.
- Do not add `API_KEY` to `WRITABLE_CONFIG_KEYS`.

**Verify**: `./.venv/bin/ruff check --no-cache comicarr/app/system/service.py` -> `All checks passed!`.

### Step 2: Add an authenticated router endpoint

In `comicarr/app/system/router.py`, add a dedicated endpoint near the config endpoints:

- Method: `POST`
- Path: `/api/config/api-key/regenerate`
- Dependency: `Depends(require_session)`
- Implementation: delegate to `system_service.regenerate_api_key` through `asyncio.to_thread`.
- Response: return service result; if service returns `success: False`, use a 400 or 500 JSON response consistent with nearby endpoints.

**Verify**: `./.venv/bin/ruff check --no-cache comicarr/app/system/router.py` -> `All checks passed!`.

### Step 3: Update backend tests

In `tests/unit/test_system_domain.py`, keep the existing tests that prove `update_config` rejects `api_key`. Add tests for the new service function:

- Success path: returns `success: True`, returns an `api_key` string, writes `ctx.config.API_KEY`, calls `writeconfig`, and calls `configure(update=True, startup=False)`.
- Error path: returns failure when config is missing.
- Safety path: generic `update_config` still rejects `api_key`.

Do not put a real secret value in the test source. Use placeholder values only.

**Verify**: `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_system_domain.py -q -p no:cacheprovider` -> all pass.

### Step 4: Replace browser-local regeneration with the endpoint

In `frontend/src/components/settings/ApiTab.tsx`, change `handleRegenerateApiKey` so it calls the backend endpoint. The UI should no longer put `api_key` into the generic settings form or tell the user to save.

Required UX:

- Keep the confirmation dialog because existing API integrations are invalidated.
- Show a success toast that says the API key was regenerated.
- Display the returned key immediately so the user can copy it.
- Invalidate or refetch config after success if needed.
- Keep the copy button behavior, but make sure it copies the returned/current key, not a stale `config.api_key`.

You may remove or rewrite the unused `useGenerateApiKey()` hook in `frontend/src/hooks/useConfig.ts`. If you keep it, it must call `/api/config/api-key/regenerate`, not `PUT /api/config`.

**Verify**: `cd frontend && npm run typecheck` -> exit 0.

### Step 5: Add a focused frontend test

Add an `ApiTab` test under `frontend/tests/components/` or another existing test location. Use the existing Vitest and Testing Library style from `frontend/tests/pages/ImportPage.test.tsx`.

Cover:

- Clicking regenerate confirms, posts to `/api/config/api-key/regenerate`, displays the returned key, and does not call the generic config save path.
- Copy uses the visible regenerated key.

Use MSW if the component path naturally makes HTTP calls; otherwise pass a small fake mutation helper if you extracted one.

**Verify**: `cd frontend && npm run test:run -- ApiTab` -> the new test passes.

## Test plan

- Backend service tests in `tests/unit/test_system_domain.py`.
- Frontend component test for the regenerate/copy behavior.
- Existing generic config rejection tests must remain.

## Done criteria

- [ ] Generic `PUT /api/config` still rejects `api_key`.
- [ ] New authenticated `POST /api/config/api-key/regenerate` persists a server-generated key.
- [ ] Settings UI no longer asks users to save after regenerating the API key.
- [ ] The newly returned key is visible/copyable immediately after regeneration.
- [ ] Backend and frontend verification commands in this plan exit 0.
- [ ] No files outside the in-scope list are modified.
- [ ] `plans/README.md` status row updated.

## STOP conditions

Stop and report back if:

- There is already another API-key rotation endpoint or config-generation path not cited here.
- Existing clients require reading the old API key from `GET /api/config` and plan 003 has already landed differently.
- Persisting `ctx.config.API_KEY` requires encrypted storage changes outside the system domain.

## Maintenance notes

Reviewers should check that only the dedicated endpoint can rotate `API_KEY`. This plan intentionally avoids making sensitive keys generally writable through the config payload.
