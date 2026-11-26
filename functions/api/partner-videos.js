/**
 * Kaling Partner API (/v1/videos & /v1/videos/:orderId)
 * Runs directly on Cloudflare Worker at https://kaling.cloud/v1/videos
 */

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-API-Key',
};

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-store',
      ...CORS_HEADERS,
    },
  });
}

function getServiceAccount(env) {
  const raw = env && env.FIREBASE_SERVICE_ACCOUNT_KL;
  if (!raw) throw new Error('Missing FIREBASE_SERVICE_ACCOUNT_KL env var');
  return JSON.parse(raw);
}

function b64url(str) {
  return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

let cachedToken = null;
let cachedTokenExp = 0;

async function getAccessToken(email, privateKey) {
  const now = Math.floor(Date.now() / 1000);
  if (cachedToken && cachedTokenExp - 60 > now) {
    return cachedToken;
  }
  const iat = now;
  const exp = iat + 3600;
  const header = b64url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
  const payload = b64url(
    JSON.stringify({
      iss: email,
      scope: 'https://www.googleapis.com/auth/datastore',
      aud: 'https://oauth2.googleapis.com/token',
      exp,
      iat,
    })
  );
  const message = `${header}.${payload}`;

  let pemContents = privateKey
    .replace(/-----BEGIN PRIVATE KEY-----/g, '')
    .replace(/-----END PRIVATE KEY-----/g, '')
    .replace(/\s+/g, '')
    .replace(/\\n/g, '');
  while (pemContents.length % 4 !== 0) pemContents += '=';

  const binaryDerString = atob(pemContents);
  const binaryDer = new Uint8Array(binaryDerString.length);
  for (let i = 0; i < binaryDerString.length; i++) {
    binaryDer[i] = binaryDerString.charCodeAt(i);
  }

  const key = await crypto.subtle.importKey(
    'pkcs8',
    binaryDer,
    { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' },
    false,
    ['sign']
  );

  const signature = await crypto.subtle.sign(
    'RSASSA-PKCS1-v1_5',
    key,
    new TextEncoder().encode(message)
  );
  const jwt = `${message}.${b64url(String.fromCharCode(...new Uint8Array(signature)))}`;

  const res = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=${jwt}`,
  });
  const data = await res.json();
  if (data.error || !data.access_token) {
    throw new Error('Google Auth Error: ' + (data.error_description || data.error || 'unknown'));
  }
  cachedToken = data.access_token;
  cachedTokenExp = exp;
  return cachedToken;
}

function extractApiKey(request) {
  const auth = (request.headers.get('Authorization') || '').trim();
  if (auth.toLowerCase().startsWith('bearer ')) {
    return auth.slice(7).trim();
  }
  const xKey = (request.headers.get('X-API-Key') || '').trim();
  if (xKey) return xKey;
  return '';
}

function readFirestoreNumber(field) {
  if (!field) return 0;
  const raw = field.doubleValue ?? field.integerValue ?? field.stringValue ?? 0;
  const n = parseFloat(raw);
  return Number.isFinite(n) ? n : 0;
}

function readFirestoreString(field) {
  if (!field) return '';
  if (typeof field.stringValue === 'string') return field.stringValue;
  if (field.integerValue !== undefined) return String(field.integerValue);
  if (field.doubleValue !== undefined) return String(field.doubleValue);
  return '';
}

async function authenticateApiKey(token, projectId, apiKey) {
  if (!apiKey) {
    return { error: jsonResponse({ detail: 'Missing or invalid Authorization header' }, 401) };
  }

  const url = `https://firestore.googleapis.com/v1/projects/${projectId}/databases/(default)/documents:runQuery`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      structuredQuery: {
        from: [{ collectionId: 'users' }],
        where: {
          fieldFilter: {
            field: { fieldPath: 'apiKey' },
            op: 'EQUAL',
            value: { stringValue: apiKey },
          },
        },
        limit: 1,
      },
    }),
  });

  const data = await res.json();
  const item = Array.isArray(data) ? data.find((x) => x && x.document) : null;
  if (!item || !item.document) {
    return { error: jsonResponse({ detail: 'Invalid API Key' }, 403) };
  }

  const doc = item.document;
  const fields = doc.fields || {};
  const uid = doc.name.split('/').pop();
  return {
    user: {
      uid,
      docName: doc.name,
      updateTime: doc.updateTime,
      coins: readFirestoreNumber(fields.coins),
      email: readFirestoreString(fields.email),
      displayName: readFirestoreString(fields.displayName) || readFirestoreString(fields.name) || 'API Partner',
    },
  };
}

function randomHex(bytesLen = 8) {
  const arr = new Uint8Array(bytesLen);
  crypto.getRandomValues(arr);
  return Array.from(arr, (b) => b.toString(16).padStart(2, '0')).join('');
}

function isHttpUrl(val) {
  try {
    const u = new URL(String(val || '').trim());
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch {
    return false;
  }
}

function isKalingSupabaseEnabled(env) {
  return (
    String(env?.KALING_DB_BACKEND || '').trim().toLowerCase() === 'supabase' &&
    Boolean(env?.SUPABASE_URL) &&
    Boolean(env?.SUPABASE_SERVICE_ROLE_KEY)
  );
}

function sbHeaders(env) {
  const key = env.SUPABASE_SERVICE_ROLE_KEY;
  return {
    apikey: key,
    Authorization: `Bearer ${key}`,
    'Content-Type': 'application/json',
  };
}

async function handlePartnerVideosSupabase(request, env, path) {
  const base = String(env.SUPABASE_URL).replace(/\/+$/, '');
  const apiKey = extractApiKey(request);
  if (!apiKey) {
    return jsonResponse({ detail: 'Missing or invalid Authorization header' }, 401);
  }

  // POST /v1/videos -> atomic RPC kaling_partner_create_order
  if (path === '/v1/videos' && request.method === 'POST') {
    let payload;
    try {
      payload = await request.json();
    } catch {
      return jsonResponse({ detail: 'Invalid JSON body' }, 400);
    }

    const modelId = String(payload?.model_id || '').trim();
    if (modelId !== '159' && modelId !== '160') {
      return jsonResponse(
        { detail: "Invalid model_id. Only '159' (10s) and '160' (20s) are supported." },
        400
      );
    }

    const charUrl = String(payload?.character_image_url || '').trim();
    const refVideoUrl = String(payload?.reference_video_url || '').trim();
    if (!isHttpUrl(charUrl) || !isHttpUrl(refVideoUrl)) {
      return jsonResponse(
        { detail: 'Both character_image_url and reference_video_url must be valid HTTP/HTTPS URLs.' },
        400
      );
    }

    const quality = String(payload?.quality || '720p').trim();
    const orderId = 'kl_ord_' + randomHex(8);

    const rpcRes = await fetch(`${base}/rest/v1/rpc/kaling_partner_create_order`, {
      method: 'POST',
      headers: sbHeaders(env),
      body: JSON.stringify({
        p_api_key: apiKey,
        p_model_id: modelId,
        p_char_url: charUrl,
        p_ref_video_url: refVideoUrl,
        p_quality: quality,
        p_order_id: orderId,
      }),
    });

    if (!rpcRes.ok) {
      const errText = await rpcRes.text();
      return jsonResponse({ detail: 'Database transaction failed: ' + errText }, 500);
    }

    const result = await rpcRes.json();
    if (!result?.ok) {
      return jsonResponse({ detail: result?.detail || 'Order rejected' }, result?.http_status || 400);
    }

    return jsonResponse(
      {
        success: true,
        order_id: result.order_id,
        status: result.status || 'pending',
        cost_credits: Number(result.cost_credits || 0),
      },
      202
    );
  }

  // GET /v1/videos/:orderId -> authenticate api_key + fetch kaling_orders
  const matchGet = path.match(/^\/v1\/videos\/([^/]+)$/);
  if (matchGet && request.method === 'GET') {
    const userRes = await fetch(
      `${base}/rest/v1/kaling_users?api_key=eq.${encodeURIComponent(apiKey)}&select=id&limit=1`,
      { headers: sbHeaders(env) }
    );
    if (!userRes.ok) {
      return jsonResponse({ detail: 'Failed to authenticate API Key' }, 500);
    }
    const users = await userRes.json();
    if (!Array.isArray(users) || users.length === 0) {
      return jsonResponse({ detail: 'Invalid API Key' }, 403);
    }
    const uid = String(users[0].id);

    const orderId = decodeURIComponent(matchGet[1]);
    const ordRes = await fetch(
      `${base}/rest/v1/kaling_orders?id=eq.${encodeURIComponent(orderId)}&select=id,user_id,status,result_link,error_message,system_note,admin_note&limit=1`,
      { headers: sbHeaders(env) }
    );
    if (!ordRes.ok) {
      const errText = await ordRes.text();
      return jsonResponse({ detail: 'Failed to read order: ' + errText }, 500);
    }
    const orders = await ordRes.json();
    if (!Array.isArray(orders) || orders.length === 0) {
      return jsonResponse({ detail: 'Order not found' }, 404);
    }
    const ord = orders[0];
    if (String(ord.user_id) !== uid) {
      return jsonResponse({ detail: 'Access denied for this order' }, 403);
    }
    const status = String(ord.status || 'pending');
    const errorMessage = ord.error_message || ord.system_note || ord.admin_note || null;
    return jsonResponse({
      order_id: orderId,
      status,
      result_url: ord.result_link || null,
      error_message: status === 'failed' ? errorMessage : null,
    });
  }

  return jsonResponse({ detail: 'Method Not Allowed' }, 405);
}

export async function handlePartnerVideosRequest(request, env) {
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  const url = new URL(request.url);
  const path = url.pathname.replace(/^\/api(?=\/v1\/videos)/, '').replace(/\/+$/, '');

  if (isKalingSupabaseEnabled(env)) {
    return handlePartnerVideosSupabase(request, env, path);
  }

  // Proxy thẳng sang VPS AquaAI backend (Supabase kaling_* — không cần cấu hình secrets trên Cloudflare)
  const upstreamUrl = 'https://api.aquaai.vn/api/payment/kaling-v1' + path.replace(/^\/v1/, '') + url.search;
  const headers = new Headers();
  const auth = request.headers.get('Authorization');
  const xKey = request.headers.get('X-API-Key');
  const ctype = request.headers.get('Content-Type');
  if (auth) headers.set('Authorization', auth);
  if (xKey) headers.set('X-API-Key', xKey);
  if (ctype) headers.set('Content-Type', ctype);

  const upstreamRes = await fetch(upstreamUrl, {
    method: request.method,
    headers,
    body: request.method === 'POST' ? await request.text() : undefined,
  });
  const respText = await upstreamRes.text();
  return new Response(respText, {
    status: upstreamRes.status,
    headers: {
      'Content-Type': upstreamRes.headers.get('Content-Type') || 'application/json',
      'Cache-Control': 'no-store',
      ...CORS_HEADERS,
    },
  });
}

// Legacy Firestore handler retained below only as reference
async function _legacyHandlePartnerVideosFirestore(request, env, path) {

  let cfg;
  let token;
  try {
    cfg = getServiceAccount(env);
    token = await getAccessToken(cfg.client_email, cfg.private_key);
  } catch (e) {
    return jsonResponse({ detail: 'Server configuration error: ' + e.message }, 500);
  }

  const apiKey = extractApiKey(request);
  const authResult = await authenticateApiKey(token, cfg.project_id, apiKey);
  if (authResult.error) return authResult.error;
  const user = authResult.user;

  // POST /v1/videos -> Create new video order
  if (path === '/v1/videos' && request.method === 'POST') {
    let payload;
    try {
      payload = await request.json();
    } catch {
      return jsonResponse({ detail: 'Invalid JSON body' }, 400);
    }

    const modelId = String(payload?.model_id || '').trim();
    if (modelId !== '159' && modelId !== '160') {
      return jsonResponse(
        { detail: "Invalid model_id. Only '159' (10s) and '160' (20s) are supported." },
        400
      );
    }

    const charUrl = String(payload?.character_image_url || '').trim();
    const refVideoUrl = String(payload?.reference_video_url || '').trim();
    if (!isHttpUrl(charUrl) || !isHttpUrl(refVideoUrl)) {
      return jsonResponse(
        { detail: 'Both character_image_url and reference_video_url must be valid HTTP/HTTPS URLs.' },
        400
      );
    }

    const rawQ = String(payload?.quality || '720p').trim().toLowerCase();
    const qualityMode = rawQ === '2k' || rawQ === '1080p' || rawQ === '2' ? '2' : '1';
    const qualityName = qualityMode === '2' ? '2k' : '720p';

    const baseCost = modelId === '159' ? 6.0 : 10.0;
    const cost = qualityMode === '2' ? baseCost * 2.0 : baseCost;
    const maxVideoSec = modelId === '159' ? 10 : 20;

    if (user.coins < cost) {
      return jsonResponse(
        {
          detail: `Insufficient coins. Required ${cost} coins for ${qualityName.toUpperCase()} quality, but you only have ${user.coins} coins.`,
        },
        402
      );
    }

    const orderId = 'kl_ord_' + randomHex(8);
    const nextCoins = Math.round((user.coins - cost) * 100) / 100;
    const nowIso = new Date().toISOString();
    const dbRoot = `projects/${cfg.project_id}/databases/(default)/documents`;
    const orderDocName = `${dbRoot}/orders/${orderId}`;

    const commitUrl = `https://firestore.googleapis.com/v1/${dbRoot}:commit`;
    const commitBody = {
      writes: [
        {
          update: {
            name: user.docName,
            fields: {
              coins: { doubleValue: nextCoins },
              updatedAt: { timestampValue: nowIso },
            },
          },
          updateMask: { fieldPaths: ['coins', 'updatedAt'] },
          ...(user.updateTime ? { currentDocument: { updateTime: user.updateTime } } : {}),
        },
        {
          update: {
            name: orderDocName,
            fields: {
              userId: { stringValue: user.uid },
              userEmail: { stringValue: user.email },
              userName: { stringValue: user.displayName },
              packageName: { stringValue: `API ${maxVideoSec}s (${qualityName.toUpperCase()})` },
              status: { stringValue: 'pending' },
              modelId: { stringValue: modelId },
              renderProvider: { stringValue: 'aidancing' },
              maxVideoSec: { integerValue: String(maxVideoSec) },
              qualityMode: { stringValue: qualityMode },
              quality: { stringValue: qualityName },
              serviceType: { stringValue: 'motion_transfer' },
              serviceLabel: { stringValue: 'Chuyển động nhân vật (API)' },
              characterImageLink: { stringValue: charUrl },
              referenceVideoLink: { stringValue: refVideoUrl },
              character_image_url: { stringValue: charUrl },
              reference_video_url: { stringValue: refVideoUrl },
              costCoins: { doubleValue: cost },
              referer: { stringValue: 'api' },
              clientVersion: { integerValue: '35' },
              resultLink: { stringValue: '' },
              result_url: { nullValue: null },
              error_message: { nullValue: null },
              createdAt: { timestampValue: nowIso },
              updatedAt: { timestampValue: nowIso },
            },
          },
          currentDocument: { exists: false },
        },
      ],
    };

    const commitRes = await fetch(commitUrl, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(commitBody),
    });

    if (!commitRes.ok) {
      const errText = await commitRes.text();
      return jsonResponse({ detail: 'Database transaction failed: ' + errText }, 500);
    }

    return jsonResponse(
      {
        success: true,
        order_id: orderId,
        status: 'pending',
        cost_credits: cost,
      },
      202
    );
  }

  // GET /v1/videos/:orderId -> Get order status & result video URL
  const matchGet = path.match(/^\/v1\/videos\/([^/]+)$/);
  if (matchGet && request.method === 'GET') {
    const orderId = decodeURIComponent(matchGet[1]);
    const docUrl = `https://firestore.googleapis.com/v1/projects/${cfg.project_id}/databases/(default)/documents/orders/${encodeURIComponent(orderId)}`;
    const res = await fetch(docUrl, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (res.status === 404) {
      return jsonResponse({ detail: 'Order not found' }, 404);
    }
    if (!res.ok) {
      const errText = await res.text();
      return jsonResponse({ detail: 'Failed to read order: ' + errText }, 500);
    }

    const doc = await res.json();
    const fields = doc.fields || {};
    const ownerUid = readFirestoreString(fields.userId);
    if (ownerUid !== user.uid) {
      return jsonResponse({ detail: 'Access denied for this order' }, 403);
    }

    const status = readFirestoreString(fields.status) || 'pending';
    const resultUrl =
      readFirestoreString(fields.result_url) ||
      readFirestoreString(fields.resultLink) ||
      null;
    const errorMessage =
      readFirestoreString(fields.error_message) ||
      readFirestoreString(fields.systemNote) ||
      readFirestoreString(fields.adminNote) ||
      null;

    return jsonResponse({
      order_id: orderId,
      status,
      result_url: resultUrl,
      error_message: status === 'failed' ? errorMessage : null,
    });
  }

  return jsonResponse({ detail: 'Method Not Allowed' }, 405);
}
