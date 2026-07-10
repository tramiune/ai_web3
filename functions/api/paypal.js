/**
 * PayPal Integration Handler (Cloudflare Workers + Firebase Admin REST API)
 * MotionAI Studio - International Payments (replaces Lemon Squeezy)
 *
 * Exports 4 handlers wired up by index.js:
 *   - onConfigRequest          (GET  /api/paypal-config)
 *   - onCreateOrderRequest     (POST /api/paypal-create-order)
 *   - onCaptureOrderRequest    (POST /api/paypal-capture-order)
 *   - onWebhookRequest         (POST /api/paypal-webhook)
 *
 * Flow (Smart Buttons + Webhook source-of-truth):
 *   1. Frontend fetches /api/paypal-config to know which Client ID + env to load.
 *   2. Frontend renders PayPal Buttons. createOrder() -> /api/paypal-create-order
 *      with { userId, packageId }. Server validates packageId, looks up USD price
 *      from server-side map (never trust client), creates a PayPal Order with
 *      custom_id = "userId|packageId", returns the Order ID.
 *   3. User approves in PayPal popup. onApprove() -> /api/paypal-capture-order
 *      with { orderID }. Server calls PayPal Capture API.
 *   4. PayPal fires webhook PAYMENT.CAPTURE.COMPLETED. Server verifies signature
 *      via PayPal verify-webhook-signature API (using configured Webhook ID),
 *      then atomically:
 *         a) creates topup doc paypal_<captureId> (idempotent via documentId)
 *         b) increments user's coin balance
 *         c) sends Telegram notification
 *         d) pays 10% referral commission (isolated try/catch)
 *
 * The webhook is the ONLY place that grants coins, so even if onApprove fails
 * client-side the user still gets coins. Idempotency key is the capture ID, so
 * PayPal retries are safe.
 */

// --- Static credentials (ENV vars override these in production) ---------------
const TELEGRAM_BOT_TOKEN = '8647185235:AAEcxfblgna8BnQoAX2B7cF9HEyx3EhDBts';
const TELEGRAM_CHAT_ID = '6067707939';

// Sandbox credentials provided by store owner. Override with PAYPAL_* env vars.
const PAYPAL_DEFAULTS = {
    env: 'sandbox', // 'sandbox' | 'live'
    clientId: 'AcLjX0I8K9tRDrw_LmOph58WKfgX2Njyx5KEinWPLIynQmgRdxbxZGNuOenoQ1b1iHRZtO7JikalTkYo',
    clientSecret: 'EJ3dnS5nfnZDtloy1LGh_2FAKrA9Knupoiy8sSBOap8a6pILbpwlz_bcxRqI3rRF7cDZHXfnXo61Gn7G',
    webhookId: '4AD029845G780052L'
};

// Server-side package map. Frontend must NEVER set the price.
// Keep in sync with COIN_PACKAGES in public/script.js (id + coins).
const PACKAGES = {
    'starter_v2':  { coins: 10,   priceUsd: 0.49,  name: 'Starter (International)' },
    'creator':     { coins: 100,  priceUsd: 5.99,  name: 'Creator (International)' },
    'studio':      { coins: 525,  priceUsd: 24.99, name: 'Studio (International)' },
    'pro-studio':  { coins: 1100, priceUsd: 49.99, name: 'Enterprise (International)' },
    'hocvien_package': { coins: 6500, priceUsd: 199.99, name: 'Student Course (International)' }
};

// Shared with Casso webhook. Real key MUST come from FIREBASE_SERVICE_ACCOUNT env var.
const SERVICE_ACCOUNT_FALLBACK = {
    project_id: 'motionai-studio-76be9',
    client_email: 'firebase-adminsdk-fbsvc@motionai-studio-76be9.iam.gserviceaccount.com',
    private_key: '' // intentionally empty: production must use env var
};

// --- Public entry points ------------------------------------------------------

export async function onConfigRequest(context) {
    const { env } = context;
    const cfg = readPaypalConfig(env);
    return jsonResponse({
        clientId: cfg.clientId,
        env: cfg.env,
        currency: 'USD'
    });
}

export async function onCreateOrderRequest(context) {
    const { request, env } = context;
    try {
        const body = await request.json().catch(() => ({}));
        const userId = String(body.userId || '').trim();
        const packageId = String(body.packageId || '').trim();
        const userEmail = String(body.userEmail || '').trim();

        if (!userId) return jsonResponse({ error: 'Missing userId' }, 400);
        const pkg = PACKAGES[packageId];
        if (!pkg) return jsonResponse({ error: `Unknown packageId: ${packageId}` }, 400);

        const cfg = readPaypalConfig(env);
        const accessToken = await getPaypalAccessToken(cfg);

        const orderBody = {
            intent: 'CAPTURE',
            purchase_units: [{
                reference_id: packageId,
                description: `${pkg.name} - ${pkg.coins} Coins`,
                custom_id: `${userId}|${packageId}`,
                amount: {
                    currency_code: 'USD',
                    value: pkg.priceUsd.toFixed(2)
                }
            }],
            application_context: {
                brand_name: 'MotionAI Studio',
                user_action: 'PAY_NOW',
                shipping_preference: 'NO_SHIPPING'
            }
        };

        const res = await fetch(`${paypalApiBase(cfg.env)}/v2/checkout/orders`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${accessToken}`,
                'Content-Type': 'application/json',
                'PayPal-Request-Id': `${userId}-${packageId}-${Date.now()}`
            },
            body: JSON.stringify(orderBody)
        });

        const data = await res.json();
        if (!res.ok) {
            console.error('[PayPal] Create order failed:', res.status, data);
            return jsonResponse({ error: 'PayPal create order failed', details: data }, 502);
        }

        // Optional: log the intent client-side. The webhook handles all coin grants.
        return jsonResponse({ orderID: data.id, status: data.status });
    } catch (err) {
        console.error('[PayPal] create-order error:', err.message);
        return jsonResponse({ error: err.message }, 500);
    }
}

export async function onCaptureOrderRequest(context) {
    const { request, env } = context;
    try {
        const body = await request.json().catch(() => ({}));
        const orderID = String(body.orderID || '').trim();
        if (!orderID) return jsonResponse({ error: 'Missing orderID' }, 400);

        const cfg = readPaypalConfig(env);
        const accessToken = await getPaypalAccessToken(cfg);

        const res = await fetch(`${paypalApiBase(cfg.env)}/v2/checkout/orders/${orderID}/capture`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${accessToken}`,
                'Content-Type': 'application/json',
                'PayPal-Request-Id': `cap-${orderID}`
            }
        });

        const data = await res.json();
        if (!res.ok) {
            // INSTRUMENT_DECLINED etc. - return raw error for frontend to surface.
            console.error('[PayPal] Capture failed:', res.status, data);
            return jsonResponse({ error: 'PayPal capture failed', details: data }, 502);
        }

        // Webhook is the source of truth for granting coins. Return status only.
        return jsonResponse({ status: data.status, orderID: data.id });
    } catch (err) {
        console.error('[PayPal] capture-order error:', err.message);
        return jsonResponse({ error: err.message }, 500);
    }
}

export async function onWebhookRequest(context) {
    const { request, env } = context;
    const bodyText = await request.text();
    let event;

    try {
        event = JSON.parse(bodyText);
    } catch (e) {
        return new Response('Invalid JSON', { status: 400 });
    }

    try {
        const cfg = readPaypalConfig(env);

        // Verify webhook signature via PayPal's verify API.
        const verifyOk = await verifyPaypalWebhook(cfg, request.headers, bodyText, event);
        if (!verifyOk) {
            console.error('[PayPal] Webhook signature verification FAILED');
            await notifyTelegram(`⚠️ <b>PAYPAL WEBHOOK SIGNATURE INVALID</b>\nEvent: ${event.event_type}\nID: ${event.id}`);
            return new Response('Invalid signature', { status: 401 });
        }

        const eventType = event.event_type || '';
        const ACCEPTED_EVENTS = ['PAYMENT.CAPTURE.COMPLETED', 'PAYMENT.CAPTURE.PENDING'];
        if (!ACCEPTED_EVENTS.includes(eventType)) {
            return jsonResponse({ success: true, message: `Ignored event: ${eventType}` });
        }

        const resource = event.resource || {};
        const captureId = resource.id; // unique PayPal capture id - use for idempotency
        const customId = resource.custom_id || '';
        const [userId, packageId] = customId.split('|');
        const amountValue = parseFloat(resource.amount?.value || '0');
        const currency = resource.amount?.currency_code || 'USD';
        const payerEmail = resource.payer?.email_address
            || event.resource?.supplementary_data?.related_ids?.order_id // fallback
            || '';

        if (!userId || !packageId) {
            console.error('[PayPal] Missing custom_id parts:', customId);
            await notifyTelegram(`❌ <b>PAYPAL WEBHOOK MISSING custom_id</b>\nCapture: ${captureId}\nRaw: ${customId}`);
            return jsonResponse({ error: 'Missing custom_id' }, 400);
        }

        const pkg = PACKAGES[packageId];
        let coins;
        let packageName;
        if (pkg) {
            coins = pkg.coins;
            packageName = pkg.name;
        } else {
            // Defensive: someone mucked with the order. Try to recover from amount.
            const fallback = inferPackageFromAmount(amountValue);
            coins = fallback.coins;
            packageName = fallback.name;
            console.warn(`[PayPal] Unknown packageId ${packageId}, inferred ${coins} coins from $${amountValue}`);
        }

        const svc = await loadServiceAccount(env);
        const fbToken = await getFirebaseAccessToken(svc.client_email, svc.private_key);

        // 1) Idempotent topup doc creation. Doc id = paypal_<captureId>.
        const topupId = `paypal_${captureId}`;
        const created = await createTopupRecordIdempotent(fbToken, svc.project_id, topupId, {
            userId,
            userEmail: payerEmail,
            userName: resource.payer?.name?.given_name
                ? `${resource.payer.name.given_name} ${resource.payer.name.surname || ''}`.trim()
                : 'PayPal Customer',
            packageName,
            coins,
            amount: amountValue,
            currency,
            transferContent: `PAYPAL ${captureId}`,
            status: 'approved',
            isAutomated: true,
            gateway: 'paypal'
        });

        if (!created) {
            // Already processed (PayPal webhook retry) - return success without re-crediting.
            console.log(`[PayPal] Duplicate webhook for capture ${captureId} - idempotent skip`);
            return jsonResponse({ success: true, idempotent: true });
        }

        // 2) Grant coins to user.
        await grantCoins(fbToken, svc.project_id, userId, coins);

        // Fetch today's total amount (KV + Firestore fallback)
        let todayLine = '';
        const amountVnd = currency.toUpperCase() === 'USD'
            ? Math.round(amountValue * 25400)
            : Math.round(amountValue);
        const kvTotal = await trackDailyRevenueVnd(env, amountVnd, topupId, 'ALL');
        if (kvTotal != null) {
            todayLine = `\n📊 Tổng hôm nay: ${kvTotal.toLocaleString('vi-VN')}đ (ước tính)`;
        } else {
            try {
                let todayTotal = await fetchTodayTotalAmount(fbToken, svc.project_id);
                todayTotal += amountVnd;
                todayLine = `\n📊 Tổng hôm nay: ${Math.round(todayTotal).toLocaleString('vi-VN')}đ (ước tính)`;
            } catch (e) {
                console.error("fetchTodayTotalAmount error:", e);
            }
        }

        // 3) Notify Telegram.
        const isPending = eventType === 'PAYMENT.CAPTURE.PENDING';
        const statusLabel = isPending ? '⏳ ĐANG GIỮ TIỀN (Hold)' : '✅ HOÀN TẤT';
        const message =
            `🌎 <b>NẠP TIỀN QUỐC TẾ ${isPending ? '(PayPal - HOLD)' : 'THÀNH CÔNG! (PayPal)'}</b>\n\n` +
            `📌 Trạng thái: ${statusLabel}\n` +
            `👤 Khách: ${escapeHtml(resource.payer?.name?.given_name || 'N/A')}\n` +
            `📧 Email: ${escapeHtml(payerEmail || 'N/A')}\n` +
            `💵 Số tiền: $${amountValue.toFixed(2)} ${currency}\n` +
            `🪙 Coin nhận: +${coins}\n` +
            `📦 Gói: ${escapeHtml(packageName)}\n` +
            `🔑 Capture: <code>${captureId}</code>` +
            todayLine;
        await notifyTelegram(message);

        // 4) Referral commission - isolated.
        try {
            await payReferralCommission(fbToken, svc.project_id, {
                topupId,
                referredUserId: userId,
                referredUserEmail: payerEmail,
                referredUserName: resource.payer?.name?.given_name || '',
                baseCoins: coins,
                baseAmount: amountValue,
                currency: currency === 'USD' ? 'USD' : currency,
                gateway: 'paypal'
            });
        } catch (refErr) {
            console.error('[Referral] PayPal commission error (non-blocking):', refErr.message);
            try {
                await notifyTelegram(`⚠️ <b>LỖI TRẢ HOA HỒNG GIỚI THIỆU (PAYPAL)</b>\nTopup: ${topupId}\nLỗi: ${refErr.message}`);
            } catch (e) { /* swallow */ }
        }

        return jsonResponse({ success: true });
    } catch (err) {
        console.error('[PayPal] Webhook critical error:', err.message);
        await notifyTelegram(`❌ <b>LỖI WEBHOOK PAYPAL!</b>\n\n📝 Thông báo: ${escapeHtml(err.message)}`);
        return jsonResponse({ error: err.message }, 500);
    }
}

// --- Helpers ------------------------------------------------------------------

function readPaypalConfig(env) {
    const envName = String(env?.PAYPAL_ENV || PAYPAL_DEFAULTS.env || 'sandbox').trim().toLowerCase();
    const clientId = String(env?.PAYPAL_CLIENT_ID || PAYPAL_DEFAULTS.clientId || '').trim();
    const clientSecret = String(env?.PAYPAL_CLIENT_SECRET || PAYPAL_DEFAULTS.clientSecret || '').trim();
    const webhookId = String(env?.PAYPAL_WEBHOOK_ID || PAYPAL_DEFAULTS.webhookId || '').trim();

    return {
        env: envName === 'live' ? 'live' : 'sandbox',
        clientId,
        clientSecret,
        webhookId
    };
}

function paypalApiBase(envName) {
    return envName === 'live'
        ? 'https://api-m.paypal.com'
        : 'https://api-m.sandbox.paypal.com';
}

async function getPaypalAccessToken(cfg) {
    if (!cfg.clientId || !cfg.clientSecret) {
        throw new Error('PayPal credentials missing (clientId/clientSecret)');
    }
    const basic = btoa(`${cfg.clientId}:${cfg.clientSecret}`);
    const res = await fetch(`${paypalApiBase(cfg.env)}/v1/oauth2/token`, {
        method: 'POST',
        headers: {
            'Authorization': `Basic ${basic}`,
            'Content-Type': 'application/x-www-form-urlencoded'
        },
        body: 'grant_type=client_credentials'
    });
    const data = await res.json();
    if (!res.ok || !data.access_token) {
        throw new Error(`PayPal OAuth failed: ${res.status} ${JSON.stringify(data)}`);
    }
    return data.access_token;
}

async function verifyPaypalWebhook(cfg, headers, rawBody, parsedEvent) {
    if (!cfg.webhookId) {
        console.warn('[PayPal] No webhookId configured - skipping verification (DEV ONLY)');
        return true;
    }
    const accessToken = await getPaypalAccessToken(cfg);

    const verifyPayload = {
        auth_algo: headers.get('paypal-auth-algo'),
        cert_url: headers.get('paypal-cert-url'),
        transmission_id: headers.get('paypal-transmission-id'),
        transmission_sig: headers.get('paypal-transmission-sig'),
        transmission_time: headers.get('paypal-transmission-time'),
        webhook_id: cfg.webhookId,
        webhook_event: parsedEvent
    };

    // All PayPal-* headers must be present for a real webhook.
    if (!verifyPayload.transmission_id || !verifyPayload.transmission_sig) {
        return false;
    }

    const res = await fetch(`${paypalApiBase(cfg.env)}/v1/notifications/verify-webhook-signature`, {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${accessToken}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(verifyPayload)
    });
    if (!res.ok) {
        console.error('[PayPal] verify-webhook-signature HTTP error:', res.status);
        return false;
    }
    const data = await res.json();
    return data.verification_status === 'SUCCESS';
}

function inferPackageFromAmount(usd) {
    if (usd >= 45) return { coins: 1100, name: 'Enterprise (Fallback)' };
    if (usd >= 20) return { coins: 525,  name: 'Studio (Fallback)' };
    if (usd >= 10) return { coins: 200,  name: 'Creator (Fallback)' };
    if (usd >= 1.5) return { coins: 10,   name: 'Starter (Fallback)' };
    return { coins: 5, name: 'Starter (Legacy Fallback)' };
}

// --- Firebase Admin REST helpers ---------------------------------------------

async function loadServiceAccount(env) {
    const envSecret = env?.FIREBASE_SERVICE_ACCOUNT || env?.SERVICE_ACCOUNT;
    if (envSecret) {
        try {
            return JSON.parse(envSecret);
        } catch (e) {
            throw new Error('FIREBASE_SERVICE_ACCOUNT env var is set but not valid JSON');
        }
    }
    if (!SERVICE_ACCOUNT_FALLBACK.private_key) {
        throw new Error('FIREBASE_SERVICE_ACCOUNT env var must be set in production');
    }
    return SERVICE_ACCOUNT_FALLBACK;
}

async function getFirebaseAccessToken(email, privateKey) {
    const iat = Math.floor(Date.now() / 1000);
    const exp = iat + 3600;

    const header = b64UrlEncode(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
    const claim = b64UrlEncode(JSON.stringify({
        iss: email,
        scope: 'https://www.googleapis.com/auth/datastore',
        aud: 'https://oauth2.googleapis.com/token',
        exp, iat
    }));
    const message = `${header}.${claim}`;

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
        'pkcs8', binaryDer, { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['sign']
    );
    const sig = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', key, new TextEncoder().encode(message));
    const jwt = `${message}.${b64UrlEncode(String.fromCharCode(...new Uint8Array(sig)))}`;

    const res = await fetch('https://oauth2.googleapis.com/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=${jwt}`
    });
    const data = await res.json();
    if (data.error) throw new Error('Google Auth Error: ' + (data.error_description || data.error));
    return data.access_token;
}

/**
 * Create a topup doc with documentId = topupId. Returns false if doc already
 * existed (Firestore 409 ALREADY_EXISTS), true if we created it.
 * This is the idempotency gate for the webhook.
 */
async function createTopupRecordIdempotent(token, projectId, topupId, data) {
    const url = `https://firestore.googleapis.com/v1/projects/${projectId}/databases/(default)/documents/topups?documentId=${encodeURIComponent(topupId)}`;
    const fields = {
        userId:           { stringValue: data.userId },
        userEmail:        { stringValue: data.userEmail || '' },
        userName:         { stringValue: data.userName || '' },
        packageName:      { stringValue: data.packageName },
        coins:            { integerValue: data.coins },
        amount:           { doubleValue: data.amount },
        currency:         { stringValue: data.currency || 'USD' },
        transferContent:  { stringValue: data.transferContent || '' },
        status:           { stringValue: data.status || 'approved' },
        isAutomated:      { booleanValue: !!data.isAutomated },
        gateway:          { stringValue: data.gateway || 'paypal' },
        createdAt:        { timestampValue: new Date().toISOString() }
    };
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ fields })
    });
    if (res.status === 409) return false; // already processed
    if (!res.ok) {
        const txt = await res.text();
        throw new Error(`Failed to create topup record: ${res.status} ${txt}`);
    }
    return true;
}

async function grantCoins(token, projectId, userId, coins) {
    const baseUrl = `https://firestore.googleapis.com/v1/projects/${projectId}/databases/(default)/documents`;
    const userRes = await fetch(`${baseUrl}/users/${userId}`, { headers: { 'Authorization': `Bearer ${token}` } });
    if (!userRes.ok) throw new Error(`Read user ${userId} failed: ${userRes.status}`);
    const userData = await userRes.json();
    const current = parseInt(userData.fields?.coins?.integerValue || 0);
    const next = current + coins;

    const res = await fetch(`${baseUrl}/users/${userId}?updateMask.fieldPaths=coins&updateMask.fieldPaths=updatedAt`, {
        method: 'PATCH',
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
            fields: {
                coins: { integerValue: next },
                updatedAt: { timestampValue: new Date().toISOString() }
            }
        })
    });
    if (!res.ok) {
        const txt = await res.text();
        throw new Error(`Failed to grant coins: ${res.status} ${txt}`);
    }
}

async function fetchTodayTotalAmount(token, projectId) {
  // Start of today in Vietnam Time (UTC+7)
  const now = new Date();
  const vnTime = new Date(now.getTime() + 7 * 60 * 60 * 1000);
  vnTime.setUTCHours(0, 0, 0, 0);
  const startOfDayUtc = new Date(vnTime.getTime() - 7 * 60 * 60 * 1000).toISOString();

  const url = `https://firestore.googleapis.com/v1/projects/${projectId}/databases/(default)/documents:runQuery`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Authorization": `Bearer ${token}` },
    body: JSON.stringify({
      structuredQuery: {
        from: [{ collectionId: "topups" }],
        where: {
          fieldFilter: { field: { fieldPath: "createdAt" }, op: "GREATER_THAN_OR_EQUAL", value: { timestampValue: startOfDayUtc } }
        },
        limit: 1000
      }
    })
  });
  
  const data = await res.json();
  if (!Array.isArray(data)) return 0;

  let total = 0;
  for (const item of data) {
    if (item.document && item.document.fields) {
      const fields = item.document.fields;
      if (fields.status && fields.status.stringValue === "approved") {
         const currency = fields.currency?.stringValue || "VND";
         const amountStr = fields.amount?.integerValue || fields.amount?.doubleValue || fields.amount?.stringValue || "0";
         let val = parseFloat(amountStr);
         if (currency.toUpperCase() === "USD") {
             val = val * 25400; // Tỉ giá ước tính
         }
         total += val;
      }
    }
  }
  return total;
}

// --- Affiliate / Referral Commission (mirrors casso-webhook.js) --------------
const REFERRAL_COMMISSION_RATE = 0.10;

function computeCommissionAmount(baseAmount, currency) {
    if (!baseAmount || baseAmount <= 0) return 0;
    if ((currency || 'VND').toUpperCase() === 'USD') {
        return Math.round(baseAmount * REFERRAL_COMMISSION_RATE * 100) / 100;
    }
    return Math.floor(baseAmount * REFERRAL_COMMISSION_RATE);
}

function firestoreAmountField(value, currency) {
    if ((currency || 'VND').toUpperCase() === 'USD') {
        return { doubleValue: value };
    }
    return { integerValue: Math.round(value) };
}

function formatMoneyForTelegram(amount, currency) {
    if (amount == null || amount <= 0) return '';
    if ((currency || 'VND').toUpperCase() === 'USD') return `$${Number(amount).toFixed(2)} USD`;
    return `${Math.round(amount).toLocaleString('vi-VN')}đ`;
}

async function isReferrerOnAllowlist(token, projectId, referrerEmail) {
    const key = (referrerEmail || '').trim().toLowerCase();
    if (!key) return false;
    const url = `https://firestore.googleapis.com/v1/projects/${projectId}/databases/(default)/documents/referralAllowlist/${encodeURIComponent(key)}`;
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    return res.ok;
}

async function payReferralCommission(token, projectId, params) {
    const {
        topupId, referredUserId, referredUserEmail, referredUserName,
        baseCoins, baseAmount, currency, gateway
    } = params;
    if (!topupId || !referredUserId || !baseCoins || baseCoins <= 0) return;

    const cur = (currency || 'VND').toUpperCase();
    const effectiveBaseAmount = (baseAmount && baseAmount > 0)
        ? baseAmount
        : (cur === 'VND' ? baseCoins * 1000 : 0);
    const commissionAmount = computeCommissionAmount(effectiveBaseAmount, cur);
    if (commissionAmount <= 0) return;

    const baseUrl = `https://firestore.googleapis.com/v1/projects/${projectId}/databases/(default)/documents`;
    const authHeader = { 'Authorization': `Bearer ${token}` };

    const referredRes = await fetch(`${baseUrl}/users/${referredUserId}`, { headers: authHeader });
    if (!referredRes.ok) {
        if (referredRes.status === 404) return;
        throw new Error(`Read referred user failed: ${referredRes.status}`);
    }
    const referredData = await referredRes.json();
    const referredBy = referredData.fields?.referredBy?.stringValue;
    if (!referredBy || referredBy === referredUserId) return;

    const referrerRes = await fetch(`${baseUrl}/users/${referredBy}`, { headers: authHeader });
    if (!referrerRes.ok) throw new Error(`Read referrer failed: ${referrerRes.status}`);
    const referrerData = await referrerRes.json();
    const referrerName = referrerData.fields?.displayName?.stringValue
        || referrerData.fields?.email?.stringValue?.split('@')[0]
        || 'N/A';
    const referrerEmail = referrerData.fields?.email?.stringValue || '';
    const allowlisted = await isReferrerOnAllowlist(token, projectId, referrerEmail);
    if (!allowlisted) {
        console.log(`[Referral] Referrer ${referrerEmail || referredBy} not on allowlist — skip commission`);
        return;
    }

    const earningsFields = {
        referrerId:        { stringValue: referredBy },
        referrerName:      { stringValue: referrerName },
        referrerEmail:     { stringValue: referrerEmail },
        referredUserId:    { stringValue: referredUserId },
        referredUserEmail: { stringValue: referredUserEmail || referredData.fields?.email?.stringValue || '' },
        referredUserName:  { stringValue: referredUserName  || referredData.fields?.displayName?.stringValue || '' },
        topupId:           { stringValue: topupId },
        baseCoins:         { integerValue: baseCoins },
        commissionCoins:   { integerValue: 0 },
        commissionRate:    { doubleValue: REFERRAL_COMMISSION_RATE },
        gateway:           { stringValue: gateway || 'paypal' },
        currency:          { stringValue: cur },
        payoutStatus:      { stringValue: 'recorded' },
        createdAt:         { timestampValue: new Date().toISOString() }
    };
    if (effectiveBaseAmount > 0) {
        earningsFields.baseAmount = firestoreAmountField(effectiveBaseAmount, cur);
    }
    earningsFields.commissionAmount = firestoreAmountField(commissionAmount, cur);

    const createUrl = `${baseUrl}/referralEarnings?documentId=${encodeURIComponent(topupId)}`;
    const createRes = await fetch(createUrl, {
        method: 'POST',
        headers: { ...authHeader, 'Content-Type': 'application/json' },
        body: JSON.stringify({ fields: earningsFields })
    });
    if (createRes.status === 409) return;
    if (!createRes.ok) {
        const txt = await createRes.text();
        throw new Error(`Create referralEarnings failed (${createRes.status}): ${txt}`);
    }

    try {
        await notifyTelegram(
            `🎁 <b>HOA HỒNG GIỚI THIỆU (${gateway})</b>\n\n` +
            `👤 Người giới thiệu: ${escapeHtml(referrerName)}\n` +
            `📧 Email: ${escapeHtml(referrerEmail)}\n` +
            `💵 Hoa hồng: ${formatMoneyForTelegram(commissionAmount, cur)}\n` +
            `🛒 Người được mời: ${escapeHtml(referredUserName || 'N/A')} (${formatMoneyForTelegram(effectiveBaseAmount, cur) || baseCoins + ' Coin'})\n` +
            `🔑 Topup: ${topupId}`
        );
    } catch (e) { /* swallow */ }
}

// --- Misc utilities -----------------------------------------------------------

function b64UrlEncode(str) {
    return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function jsonResponse(data, status = 200) {
    return new Response(JSON.stringify(data), {
        status,
        headers: {
            'Content-Type': 'application/json',
            // CORS not needed (same-origin), but harmless if FE ever hits from preview domains.
            'Access-Control-Allow-Origin': '*'
        }
    });
}

function escapeHtml(s) {
    return String(s || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

const REVENUE_KV_TTL_SEC = 14 * 24 * 60 * 60;
const REVENUE_DEDUPE_TTL_SEC = 48 * 60 * 60;

function vietnamDateKey(date = new Date()) {
    return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Ho_Chi_Minh' }).format(date);
}

async function trackDailyRevenueVnd(env, amountVnd, topupId, scope = 'ALL') {
    const kv = env?.REVENUE_KV;
    if (!kv || !topupId) return null;
    const amount = Math.round(Number(amountVnd) || 0);
    if (amount <= 0) return null;

    try {
        const dedupeKey = `rev:dedupe:${String(topupId)}`;
        const dayKey = vietnamDateKey();
        const totalKey = `rev:total:${scope}:${dayKey}`;

        if (await kv.get(dedupeKey)) {
            const existing = await kv.get(totalKey);
            return existing ? parseInt(existing, 10) : 0;
        }

        const prev = parseInt(await kv.get(totalKey) || '0', 10);
        const next = prev + amount;
        await kv.put(totalKey, String(next), { expirationTtl: REVENUE_KV_TTL_SEC });
        await kv.put(dedupeKey, '1', { expirationTtl: REVENUE_DEDUPE_TTL_SEC });
        return next;
    } catch (err) {
        console.warn('[RevenueKV] trackDailyRevenueVnd:', err.message);
        return null;
    }
}

async function notifyTelegram(text) {
    try {
        const body = text.startsWith('[Kaling]') ? text : `[Kaling] ${text}`;
        await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                chat_id: TELEGRAM_CHAT_ID,
                text: body,
                parse_mode: 'HTML'
            })
        });
    } catch (err) {
        console.error('Telegram Notify Error:', err.message);
    }
}
