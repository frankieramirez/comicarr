/**
 * Mylar3 API Client
 * Handles all API calls to the Mylar3 backend
 */

const API_BASE = '/api';
const AUTH_BASE = '/auth';

/**
 * Make an API call to Mylar3
 * @param {string} cmd - The API command (e.g., 'getIndex', 'getComic')
 * @param {Object} params - Additional parameters for the API call
 * @returns {Promise<any>} The API response data
 */
export async function apiCall(cmd, params = {}) {
  const url = new URL(API_BASE, window.location.origin);
  url.searchParams.set('cmd', cmd);

  // Add additional parameters
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      url.searchParams.set(key, value);
    }
  });

  try {
    const response = await fetch(url, {
      credentials: 'include', // Send session cookies
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();

    // Mylar3 API returns {success: true/false, data: {...}, error: {...}}
    if (data.success === false) {
      throw new Error(data.error?.message || 'API call failed');
    }

    return data.data || data;
  } catch (error) {
    console.error('API call failed:', { cmd, params, error });
    throw error;
  }
}

/**
 * Login with username and password
 * @param {string} username - The username
 * @param {string} password - The password
 * @returns {Promise<{success: boolean, username?: string, error?: string}>}
 */
export async function login(username, password) {
  try {
    const url = new URL(`${AUTH_BASE}/login_json`, window.location.origin);

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: new URLSearchParams({
        username,
        password,
      }),
      credentials: 'include', // Receive session cookies
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Login failed:', error);
    return { success: false, error: error.message };
  }
}

/**
 * Logout the current user
 * @returns {Promise<{success: boolean}>}
 */
export async function logout() {
  try {
    const url = new URL(`${AUTH_BASE}/logout_json`, window.location.origin);

    const response = await fetch(url, {
      method: 'POST',
      credentials: 'include',
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Logout failed:', error);
    return { success: false, error: error.message };
  }
}

/**
 * Check if user has a valid session
 * @returns {Promise<{success: boolean, authenticated: boolean, username?: string}>}
 */
export async function checkSession() {
  try {
    const url = new URL(`${AUTH_BASE}/check_session`, window.location.origin);

    const response = await fetch(url, {
      credentials: 'include',
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Session check failed:', error);
    return { success: true, authenticated: false };
  }
}
