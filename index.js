import { onRequestPost as onCassoRequestPost } from './functions/api/casso-webhook.js';
import { onRequestPost as onTikTokVideoPost } from './functions/api/tiktok-video.js';
import { onRequestGet as onTikTokChannelGet } from './functions/api/tiktok-channel.js';

function isAllowedMediaUrl(rawUrl) {
  try {
    const u = new URL(rawUrl);
    return u.protocol === 'https:';
  } catch {
    return false;
  }
}

export default {
  async fetch(request, env, context) {
    const url = new URL(request.url);
    const method = request.method;

    // --- Casso (VietQR) webhook ----------------------------------------------
    if (url.pathname === '/api/casso-webhook' && method === 'POST') {
      return onCassoRequestPost({ request, env, context });
    }

    // TikTok channel videos bridge
    if (url.pathname === '/api/tiktok-channel' && method === 'GET') {
      return onTikTokChannelGet({ request, env, context });
    }

    // Geo hint for auto language: tier mapping via lang-config.js on frontend.
    if (url.pathname === '/api/geo' && method === 'GET') {
      const country = request.headers.get('CF-IPCountry')
        || request.headers.get('cf-ipcountry')
        || 'XX';
      const tierLangMap = {
        VN: 'vi',
        ES: 'es', MX: 'es', CO: 'es', AR: 'es', CL: 'es', PE: 'es', EC: 'es',
        VE: 'es', UY: 'es', PY: 'es', BO: 'es', CR: 'es', PA: 'es', DO: 'es',
        GT: 'es', HN: 'es', NI: 'es', SV: 'es', PR: 'es', CU: 'es',
        BR: 'pt', PT: 'pt',
        TH: 'th', ID: 'id'
      };
      const lang = tierLangMap[country] || 'en';
      return new Response(JSON.stringify({ country, lang }), {
        headers: {
          'Content-Type': 'application/json',
          'Cache-Control': 'no-store',
          'Access-Control-Allow-Origin': '*'
        }
      });
    }

    // TikTok link → video file (for order form reference video).
    if (url.pathname === '/api/tiktok-video') {
      if (method === 'OPTIONS' || method === 'POST') {
        return onTikTokVideoPost({ request, env, context });
      }
      return new Response('Method Not Allowed', { status: 405 });
    }

    // Proxy R2 template API to avoid CORS issues.
    if (url.pathname === '/api/templates' && method === 'GET') {
      const r2Url = 'https://pub-4496e76c4ba34c28980998855e485fbd.r2.dev/api/template.json';
      const r2Res = await fetch(r2Url);
      return new Response(r2Res.body, {
        status: r2Res.status,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
          'Cache-Control': 'public, max-age=300'
        }
      });
    }

    // Same-origin download proxy — browser native download UI (Content-Length + attachment).
    if (url.pathname === '/api/media-download' && method === 'GET') {
      const target = url.searchParams.get('url');
      if (!target || !isAllowedMediaUrl(target)) {
        return new Response('Forbidden', { status: 403 });
      }
      const upstream = await fetch(target, { redirect: 'follow' });
      if (!upstream.ok) {
        return new Response('Upstream error', { status: upstream.status });
      }
      const headers = new Headers();
      const contentType = upstream.headers.get('Content-Type') || 'application/octet-stream';
      headers.set('Content-Type', contentType);
      headers.set('Cache-Control', 'private, max-age=600');
      headers.set('Access-Control-Allow-Origin', '*');
      const contentLength = upstream.headers.get('Content-Length');
      if (contentLength) headers.set('Content-Length', contentLength);
      const acceptRanges = upstream.headers.get('Accept-Ranges');
      if (acceptRanges) headers.set('Accept-Ranges', acceptRanges);
      const suggestedName = (url.searchParams.get('name') || '').trim();
      const safeName = suggestedName.replace(/[^\w.\-()+ ]/g, '_').slice(0, 180);
      const upstreamCd = upstream.headers.get('Content-Disposition');
      if (safeName) {
        headers.set('Content-Disposition', `attachment; filename="${safeName}"`);
      } else {
        headers.set('Content-Disposition', upstreamCd || 'attachment; filename="download"');
      }
      return new Response(upstream.body, { status: upstream.status, headers });
    }

    // Not an API route - let Cloudflare Assets serve static files.
    return new Response('Not Found', { status: 404 });
  }
};
