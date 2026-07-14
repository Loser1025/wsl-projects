/**
 * Shared utilities for Vercel Serverless Functions
 * Common utilities for environment validation, CORS, error handling, and Firebase Admin init
 */

// Use correct import for firebase-admin v14+
const { cert } = require('firebase-admin/app');
const admin = require('firebase-admin');

/**
 * Validates required environment variables
 * @param {string} envVarName - Name of the environment variable
 * @param {Object} res - Response object
 * @returns {Object|null} Parsed JSON credentials or null if validation failed (response already sent)
 */
function validateEnvVar(envVarName, res) {
  const value = process.env[envVarName];
  
  if (!value || value === 'undefined' || value.trim() === '') {
    console.error(`Missing or invalid environment variable: ${envVarName}`);
    res.status(500).json({ error: 'Internal server configuration error' });
    return null;
  }
  
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch (error) {
    console.error(`Invalid JSON in ${envVarName}:`, error.message);
    res.status(500).json({ error: 'Internal server configuration error' });
    return null;
  }
  
  // Validate it's a valid service account object
  if (!parsed || typeof parsed !== 'object' || !parsed.private_key || !parsed.client_email) {
    console.error(`Invalid service account structure in ${envVarName}`);
    res.status(500).json({ error: 'Internal server configuration error' });
    return null;
  }
  
  return parsed;
}

/**
 * Sets CORS headers on response
 * @param {Object} res - Response object
 * @param {string} origin - Allowed origin (default: '*')
 */
function setCorsHeaders(res, origin = '*') {
  res.setHeader('Access-Control-Allow-Origin', origin);
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
}

/**
 * Handles OPTIONS preflight request
 * @param {Object} req - Request object
 * @param {Object} res - Response object
 * @returns {boolean} True if OPTIONS request was handled
 */
function handleOptions(req, res) {
  if (req.method === 'OPTIONS') {
    setCorsHeaders(res);
    res.status(204).end();
    return true;
  }
  return false;
}

/**
 * Handles Google Calendar API errors and returns user-friendly messages
 * @param {Error} error - The error from Google Calendar API
 * @returns {string} User-friendly error message
 */
function handleGoogleCalendarError(error) {
  // Check for 403 Forbidden - delegation issue
  if (error.code === 403 || error.status === 403) {
    return 'カレンダーアクセス権限がありません（サービスアカウントの委任設定を確認してください）';
  }
  
  // Check for errors array with forbidden reason
  if (error.errors && Array.isArray(error.errors)) {
    const forbiddenError = error.errors.find(e => e.reason === 'forbidden');
    if (forbiddenError) {
      return 'カレンダーアクセス権限がありません（サービスアカウントの委任設定を確認してください）';
    }
  }
  
  // Check error.response for Google API error format
  if (error.response && error.response.data && error.response.data.error) {
    const err = error.response.data.error;
    if (err.code === 403 || err.status === 'PERMISSION_DENIED') {
      return 'カレンダーアクセス権限がありません（サービスアカウントの委任設定を確認してください）';
    }
    if (err.errors && Array.isArray(err.errors)) {
      const forbiddenError = err.errors.find(e => e.reason === 'forbidden');
      if (forbiddenError) {
        return 'カレンダーアクセス権限がありません（サービスアカウントの委任設定を確認してください）';
      }
    }
  }
  
  // Generic error message
  return '内部サーバーエラーが発生しました';
}

/**
 * Handles generic errors - logs details but returns masked message to client
 * @param {Error} error - The error object
 * @param {Object} res - Response object
 * @param {string} defaultMessage - Default message for client
 * @param {number} statusCode - HTTP status code (default 500)
 */
function handleError(error, res, defaultMessage = '内部サーバーエラーが発生しました', statusCode = 500) {
  console.error('Error:', error.message || error);
  if (error.stack) {
    console.error(error.stack);
  }
  res.status(statusCode).json({ error: defaultMessage });
}

/**
 * Validates FreeBusy response structure
 * @param {Object} calendars - The calendars object from freebusy response
 * @returns {boolean} True if valid structure
 */
function validateFreeBusyResponse(calendars) {
  return calendars && typeof calendars === 'object' && !Array.isArray(calendars);
}

/**
 * Firebase Admin initialization with robust guard
 * Prevents re-initialization with different credentials
 * @param {Object} serviceAccount - Parsed service account credentials
 * @returns {admin.app.App} Firebase app instance
 */
function initFirebaseAdmin(serviceAccount) {
  try {
    // Check if already initialized with same credentials
    if (admin.apps.length > 0) {
      const existingApp = admin.apps[0];
      const existingCred = existingApp.options.credential;
      
      // Compare credentials - check client_email as unique identifier
      if (existingCred && existingCred.client_email === serviceAccount.client_email) {
        return existingApp;
      }
      
      // Different credentials - this shouldn't happen in serverless but handle gracefully
      console.warn('Firebase Admin already initialized with different credentials, re-initializing');
    }
    
    return admin.initializeApp({
      credential: cert(serviceAccount),
    });
  } catch (error) {
    // If already initialized error, try to get existing app
    if (error.code === 'app/duplicate-app') {
      return admin.app();
    }
    throw error;
  }
}

/**
 * Creates a standard API handler wrapper with CORS, OPTIONS, and error handling
 * @param {Function} handler - The actual handler function
 * @returns {Function} Wrapped handler
 */
function createApiHandler(handler) {
  return async function(req, res) {
    // Set CORS headers for all responses
    setCorsHeaders(res);
    
    // Handle OPTIONS preflight
    if (handleOptions(req, res)) {
      return;
    }
    
    // Only allow POST
    if (req.method !== 'POST') {
      return res.status(405).json({ error: 'Method Not Allowed' });
    }
    
    try {
      await handler(req, res);
    } catch (error) {
      handleError(error, res);
    }
  };
}

module.exports = {
  validateEnvVar,
  setCorsHeaders,
  handleOptions,
  handleGoogleCalendarError,
  handleError,
  validateFreeBusyResponse,
  initFirebaseAdmin,
  createApiHandler,
};