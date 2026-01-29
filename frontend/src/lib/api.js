/**
 * Mylar3 API Client
 * Handles all API calls to the Mylar3 backend
 */

const API_BASE = '/api';

/**
 * Make an API call to Mylar3
 * @param {string} cmd - The API command (e.g., 'getIndex', 'getComic')
 * @param {Object} params - Additional parameters for the API call
 * @returns {Promise<any>} The API response data
 */
export async function apiCall(cmd, params = {}) {
  const apiKey = localStorage.getItem('apiKey');

  if (!apiKey) {
    throw new Error('No API key found. Please log in.');
  }

  const url = new URL(API_BASE, window.location.origin);
  url.searchParams.set('apikey', apiKey);
  url.searchParams.set('cmd', cmd);

  // Add additional parameters
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      url.searchParams.set(key, value);
    }
  });

  try {
    const response = await fetch(url);

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
 * Verify if an API key is valid
 * @param {string} apiKey - The API key to verify
 * @returns {Promise<boolean>} True if valid
 */
export async function verifyApiKey(apiKey) {
  try {
    const url = new URL(API_BASE, window.location.origin);
    url.searchParams.set('apikey', apiKey);
    url.searchParams.set('cmd', 'getVersion');

    const response = await fetch(url);
    const data = await response.json();

    return data.success !== false;
  } catch (error) {
    console.error('API key verification failed:', error);
    return false;
  }
}
