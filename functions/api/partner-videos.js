/**
 * Kaling Partner API Proxy (/v1/videos & /v1/videos/:orderId)
 * Forwards directly to VPS Supabase API at https://api.aquaai.vn/api/payment/kaling-v1/videos
 * ZERO Firebase dependencies.
 */

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-API-Key',
};

const VPS_BASE = 'https://api.aquaai.vn/api/payment/kaling-v1/videos';

export async function handlePartnerVideosRequest(request) {
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }
  const url = new URL(request.url);
  const match = url.pathname.match(/^\/(?:api\/)?v1\/videos(?:\/([^/]+))?\/?$/);
  if (!match) {
    return new Response(JSON.stringify({ detail: 'Not found' }), {
      status: 404,
      headers: { 'Content-Type': 'application/json', ...CORS_HEADERS },
    });
  }

  const orderId = match[1] ? `/${encodeURIComponent(decodeURIComponent(match[1]))}` : '';
  const targetUrl = `${VPS_BASE}${orderId}`;
  const fwdHeaders = new Headers();
  const auth = request.headers.get('Authorization');
  const xKey = request.headers.get('X-API-Key');
  const ct = request.headers.get('Content-Type');
  if (auth) fwdHeaders.set('Authorization', auth);
  if (xKey) fwdHeaders.set('X-API-Key', xKey);
  if (ct) fwdHeaders.set('Content-Type', ct);

  const init = { method: request.method, headers: fwdHeaders };
  if (request.method === 'POST') {
    init.body = await request.text();
  }

  const upstream = await fetch(targetUrl, init);
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: {
      'Content-Type': upstream.headers.get('Content-Type') || 'application/json',
      'Cache-Control': 'no-store',
      ...CORS_HEADERS,
    },
  });
}
