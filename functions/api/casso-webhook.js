/**
 * Pure Casso Webhook Proxy -> VPS Supabase (https://api.aquaai.vn/api/payment/casso-webhook)
 * ZERO Firebase dependencies.
 */

const VPS_WEBHOOK_URL = 'https://api.aquaai.vn/api/payment/casso-webhook';

export async function onRequestPost(context) {
  const { request } = context;
  try {
    const bodyText = await request.text();
    const fwdHeaders = { 'Content-Type': 'application/json' };
    const secureToken = request.headers.get('secure-token');
    if (secureToken) fwdHeaders['secure-token'] = secureToken;

    const upstream = await fetch(VPS_WEBHOOK_URL, {
      method: 'POST',
      headers: fwdHeaders,
      body: bodyText,
    });
    const text = await upstream.text();
    return new Response(text, {
      status: upstream.status,
      headers: { 'Content-Type': upstream.headers.get('Content-Type') || 'application/json' },
    });
  } catch (err) {
    return new Response(JSON.stringify({ error: err.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}
