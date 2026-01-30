# Authentication Migration Complete

**Date:** 2026-01-29
**Status:** ✅ Implementation Complete - Ready for Testing

## Summary

Successfully migrated the React frontend from API key authentication to username/password authentication with CherryPy sessions, matching the original Mylar3 behavior.

---

## Changes Implemented

### Backend Changes

**File:** `mylar/auth.py`

Added three new JSON-friendly authentication endpoints:

1. **`/auth/login_json`** - Accepts username/password, creates session, returns JSON response
2. **`/auth/logout_json`** - Destroys session, returns JSON response
3. **`/auth/check_session`** - Verifies if user has valid session, returns authentication status

These endpoints use the existing `check_credentials()` function and CherryPy session management.

### Frontend Changes

#### 1. API Client (`frontend/src/lib/api.js`)

- Added `login()`, `logout()`, and `checkSession()` functions
- Updated `apiCall()` to use `credentials: 'include'` for session cookies
- Removed API key parameter from all API calls
- Removed `verifyApiKey()` function

#### 2. Auth Context (`frontend/src/contexts/AuthContext.jsx`)

- Replaced `apiKey` state with `user` object containing username
- Added `isLoading` state for initial session verification
- Added `useEffect` hook to verify session on app mount
- Updated `login()` to accept username/password
- Updated `logout()` to call new API endpoint
- Removed localStorage usage

#### 3. Login Page (`frontend/src/pages/LoginPage.jsx`)

- Replaced single API key input with username and password inputs
- Updated form validation to check both fields
- Updated labels, placeholders, and button text
- Added proper `autoComplete` attributes
- Removed helper text about finding API key

#### 4. Protected Route (`frontend/src/components/ProtectedRoute.jsx`)

- Added loading spinner while checking session on app mount
- Only redirects to login after session check completes
- Prevents flash of login page when user is authenticated

#### 5. Vite Config (`frontend/vite.config.js`)

- Added `/auth` to proxy configuration alongside existing `/api` proxy
- Ensures auth endpoints are proxied to backend during development

---

## Testing Instructions

### Prerequisites

1. Ensure Mylar3 has authentication configured:
   - Check `config.ini` has `http_username` and `http_password` set
   - Verify `authentication = 2` (form-based auth)
   - If not configured, access original UI at http://localhost:8091 and configure in Settings → Web Interface

### Backend Testing

```bash
# Start Mylar3
python3 Mylar.py --nolaunch

# Test login endpoint
curl -c cookies.txt -X POST http://localhost:8091/auth/login_json \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=YOUR_USERNAME&password=YOUR_PASSWORD"
# Expected: {"success": true, "username": "YOUR_USERNAME"}

# Test session check
curl -b cookies.txt http://localhost:8091/auth/check_session
# Expected: {"success": true, "authenticated": true, "username": "YOUR_USERNAME"}

# Test logout
curl -b cookies.txt -c cookies.txt -X POST http://localhost:8091/auth/logout_json
# Expected: {"success": true}

# Verify session cleared
curl -b cookies.txt http://localhost:8091/auth/check_session
# Expected: {"success": true, "authenticated": false}
```

### Frontend Testing

```bash
# Start Vite dev server
cd frontend
npm run dev
```

**Test Scenarios:**

1. **Initial Load**
   - Navigate to http://localhost:5173
   - Should redirect to `/login` page
   - Should see username and password inputs

2. **Login Flow**
   - Enter valid username/password → should redirect to home page
   - Enter invalid credentials → should show error message
   - Leave fields empty → should show validation error

3. **Session Persistence**
   - After logging in, refresh browser → should remain logged in
   - Close and reopen tab → should remain logged in
   - Session cookie persists across browser restarts

4. **Logout**
   - Click logout in UI → should redirect to login page
   - Try accessing protected page → should redirect to login

5. **API Functionality**
   - Browse series list → verify data loads
   - Search for comics → verify search works
   - Navigate between pages → verify session maintained

6. **Error Handling**
   - Stop backend while logged in → verify appropriate error messages
   - Invalid session → should redirect to login

### Integration Testing

- **Multi-tab:** Open in two tabs, logout from one → other should detect
- **Session timeout:** Configure short timeout, wait for expiration
- **Cookie domain:** Verify session cookie has correct domain/path settings

---

## Files Modified

**Backend:**
- `mylar/auth.py` (+45 lines)

**Frontend:**
- `frontend/src/lib/api.js` (complete rewrite for session auth)
- `frontend/src/contexts/AuthContext.jsx` (complete rewrite for session state)
- `frontend/src/pages/LoginPage.jsx` (UI changed to username/password)
- `frontend/src/components/ProtectedRoute.jsx` (added loading state)
- `frontend/vite.config.js` (added /auth proxy)

---

## Key Features

✅ Session-based authentication using CherryPy sessions
✅ Username/password login form
✅ Automatic session verification on app mount
✅ Loading states during authentication checks
✅ Session persistence across page refreshes
✅ Graceful error handling
✅ Matches original Mylar3 UI authentication behavior
✅ Backward compatible (original API endpoints unchanged)

---

## Rollback Plan

If issues arise:

1. **Backend:** Remove the three new methods from `mylar/auth.py` (lines 175-218)
2. **Frontend:** Git revert all frontend files to previous API key implementation

Original API key authentication still works for the `/api` endpoints if needed.

---

## Notes

- Session cookies handled automatically by browser with `credentials: 'include'`
- Password encryption supported via existing `check_credentials()` function
- HTTP_ROOT configuration respected (works with custom base paths)
- `/api` endpoints continue working, now receive session cookies
- Original Mako template login unchanged and still functional

---

## Next Steps

1. Test backend endpoints with curl commands above
2. Start frontend dev server and test login flow
3. Verify session persistence and logout functionality
4. Test with actual Mylar3 credentials
5. If all tests pass, commit changes and create pull request

---

## Configuration Check

Verify in your `config.ini`:

```ini
[Interface]
http_username = your_username
http_password = your_password_or_hash
authentication = 2
login_timeout = 43800
```

If authentication not configured, the new endpoints will reject all login attempts.
