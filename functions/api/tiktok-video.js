const TIKWM_API = 'https://www.tikwm.com/api/';
const MAX_BYTES = 50 * 1024 * 1024;

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-store',
      'Access-Control-Allow-Origin': '*'
    }
  });
}

export function isTikTokPageUrl(raw) {
  try {
    const u = new URL(raw.trim());
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return false;
    const host = u.hostname.toLowerCase();
    return host === 'tiktok.com' || host.endsWith('.tiktok.com');
  } catch {
    return false;
  }
}

async function resolveTikTokVideoUrl(pageUrl) {
  const apiRes = await fetch(
    `${TIKWM_API}?url=${encodeURIComponent(pageUrl)}&hd=1`,
    {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        Accept: 'application/json'
      }
    }
  );
  if (!apiRes.ok) {
    throw new Error('tikwm_http');
  }
  const payload = await apiRes.json();
  if (payload?.code !== 0 || !payload?.data) {
    throw new Error('tikwm_parse');
  }
  const data = payload.data;
  const duration = Number(data.duration || data.video_duration || 0);
  const videoUrl = data.hdplay || data.play || data.wmplay;
  if (!videoUrl) {
    throw new Error('no_video');
  }
  return { videoUrl, duration };
}

export async function onRequestPost({ request }) {
  if (request.method === 'OPTIONS') {
    return new Response(null, {
      status: 204,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type'
      }
    });
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: 'invalid_json' }, 400);
  }

  const pageUrl = (body?.url || '').trim();
  if (!pageUrl || !isTikTokPageUrl(pageUrl)) {
    return json({ error: 'invalid_url' }, 400);
  }

  let meta;
  try {
    meta = await resolveTikTokVideoUrl(pageUrl);
  } catch (e) {
    if (e.message === 'duration_limit') {
      return json({ error: 'duration_limit', duration: e.duration }, 400);
    }
    return json({ error: 'fetch_failed' }, 502);
  }

  const videoRes = await fetch(meta.videoUrl, {
    redirect: 'follow',
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      Referer: 'https://www.tiktok.com/'
    }
  });

  if (!videoRes.ok) {
    return json({ error: 'video_download' }, 502);
  }

  const contentLength = parseInt(videoRes.headers.get('content-length') || '0', 10);
  if (contentLength > MAX_BYTES) {
    return json({ error: 'size_limit' }, 400);
  }

  const headers = new Headers();
  headers.set('Content-Type', videoRes.headers.get('Content-Type') || 'video/mp4');
  headers.set('Cache-Control', 'no-store');
  headers.set('Access-Control-Allow-Origin', '*');
  if (meta.duration) {
    headers.set('X-Video-Duration', String(meta.duration));
  }
  if (contentLength > 0) {
    headers.set('Content-Length', String(contentLength));
  }

  return new Response(videoRes.body, { status: 200, headers });
}
