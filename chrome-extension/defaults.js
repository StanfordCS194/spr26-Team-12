/* Shared defaults for options + popup. Keep VERITAS_DEFAULT_BACKEND in sync with
 * frontend/vercel.json and frontend/middleware.js (same Render API the web app uses).
 * When the saved frontend is still localhost but the API is hosted, popup.js may use
 * GET /api/health field web_app_url (from backend PUBLIC_WEB_APP_URL). */
const VERITAS_DEFAULT_BACKEND = 'https://veritas-api-ka3y.onrender.com';
const VERITAS_DEFAULT_FRONTEND = 'https://veritas-ruby.vercel.app';
