/** Proxy /api/* to Render so production works even when vercel.json rewrites are not applied. */
const BACKEND_ORIGIN = 'https://veritas-api-ka3y.onrender.com';

export const config = {
  matcher: '/api/:path*',
};

export default async function middleware(request) {
  const url = new URL(request.url);
  const target = `${BACKEND_ORIGIN}${url.pathname}${url.search}`;

  const headers = new Headers(request.headers);
  headers.delete('host');

  /** @type {RequestInit} */
  const init = {
    method: request.method,
    headers,
    redirect: 'manual',
  };

  if (request.method !== 'GET' && request.method !== 'HEAD') {
    init.body = request.body;
    init.duplex = 'half';
  }

  return fetch(target, init);
}
