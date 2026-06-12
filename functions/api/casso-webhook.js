/**
 * Casso Webhook Handler (Gateway for multiple sites)
 *
 * IMPORTANT: Never hardcode Firebase service account credentials in git.
 * Provide JSON via env vars:
 * - FIREBASE_SERVICE_ACCOUNT_MS (MotionAI)
 * - FIREBASE_SERVICE_ACCOUNT_NH (Nhay Cloud)
 * - FIREBASE_SERVICE_ACCOUNT_KL (Kaling — kaling.cloud)
 */

const TELEGRAM_BOT_TOKEN = '8783657660:AAHRfxHNiohZzPJ2OaQ7TEMNKwb7AAlp2uo';
const TELEGRAM_CHAT_ID = '6067707939';

function isStarterTopup(topup) {
  return Number(topup?.coins) === 10 && Number(topup?.amount) === 10000;
}

function getServiceAccountFromEnv(env, key) {
  const envSecret = env ? env[key] : null;
  if (!envSecret) throw new Error(`Missing ${key} env var`);
  try {
    return JSON.parse(envSecret);
  } catch (e) {
    throw new Error(`Invalid ${key} JSON`);
  }
}

function pickPrefixFromDescription(descUpper) {
  // Match e.g. KL200ABCD, NH200ABCD or MS550Z9K1 anywhere in description
  const m = (descUpper || '').match(/\b(KL|NH|MS)\d{1,6}[A-Z0-9]{2,8}\b/);
  return m ? m[1] : null;
}

export async function onRequestPost(context) {
    const { request, env } = context;
    try {
      const body = await request.json();
      if (!body.data || !Array.isArray(body.data)) return new Response("No data", { status: 400 });

      const configs = {};
      const prefixEnvKeys = {
        KL: 'FIREBASE_SERVICE_ACCOUNT_KL',
        NH: 'FIREBASE_SERVICE_ACCOUNT_NH',
        MS: 'FIREBASE_SERVICE_ACCOUNT_MS',
      };
      for (const [pfx, envKey] of Object.entries(prefixEnvKeys)) {
        try {
          configs[pfx] = getServiceAccountFromEnv(env, envKey);
        } catch (e) {
          // Prefix chưa cấu hình trên worker này — bỏ qua
        }
      }

      const cache = new Map(); // prefix -> { token, pendingTopups, cfg }

      for (const transaction of body.data) {
        const description = (transaction.description || "").toUpperCase();
        const amount = transaction.amount || 0;

        const prefix = pickPrefixFromDescription(description);
        if (!prefix || !configs[prefix]) continue;

        let state = cache.get(prefix);
        if (!state) {
          const cfg = configs[prefix];
          const token = await getAccessToken(cfg.client_email, cfg.private_key);
          const pendingTopups = await fetchPendingTopups(token, cfg.project_id);
          state = { token, pendingTopups, cfg };
          cache.set(prefix, state);
        }

        // Tìm đơn nạp khớp với nội dung chuyển khoản (chỉ cần nội dung chứa mã là được)
        const topup = state.pendingTopups.find(t => description.includes(t.transferContent.toUpperCase()));

        if (topup) {
           const coins = topup.coins;
           const code = topup.transferContent;

           // Kaling: gói Starter 10k chỉ được nạp 1 lần / user
           if (prefix === 'KL' && isStarterTopup(topup)) {
             const usedStarter = await userHasApprovedStarterTopup(state.token, state.cfg.project_id, topup.userId, topup.id);
             if (usedStarter) {
               console.warn(`[CẢNH BÁO] User ${topup.userId} đã nạp gói Starter trước đó`);
               const message = `⚠️ *TỪ CHỐI NẠP TRÙNG GÓI STARTER (KL)*\n\n` +
                               `👤 Khách: ${topup.userName || 'N/A'}\n` +
                               `📝 Nội dung: ${code}\n` +
                               `*Gói 10.000đ chỉ dùng 1 lần — không cộng coin.*`;
               await notifyTelegram(message);
               continue;
             }
           }

           // KIỂM TRA BẢO MẬT: Xác minh số tiền chuyển khoản thực tế có đủ không
           if (topup.amount && amount < topup.amount) {
               console.warn(`[CẢNH BÁO] Nạp thiếu tiền: Yêu cầu ${topup.amount}, nhận ${amount}`);
               const message = `⚠️ *CẢNH BÁO NẠP THIẾU TIỀN!*\n\n` +
                               `👤 Khách: ${topup.userName || 'N/A'}\n` +
                               `💵 Số tiền nhận: ${amount.toLocaleString()}đ\n` +
                               `📉 Yêu cầu: ${topup.amount.toLocaleString()}đ\n` +
                               `🪙 Đơn: ${coins} Coin\n` +
                               `📝 Nội dung: ${code}\n` +
                               `*Lưu ý:* Hệ thống KHÔNG cộng coin tự động cho giao dịch này.`;
               await notifyTelegram(message);
               continue; // Bỏ qua, không cộng coin
           }

           await grantCoins(state.token, state.cfg.project_id, topup.userId, coins, topup.id);
           console.log(`Successfully granted ${coins} coins to user ${topup.userId}`);
           
           // Gửi thông báo Telegram
           const tidDisplay = transaction.tid || transaction.id || 'N/A';
           const message = `💰 *NẠP TIỀN THÀNH CÔNG!*\n\n` +
                           `👤 Khách: ${topup.userName || 'N/A'}\n` +
                           `📧 Email: ${topup.userEmail || 'N/A'}\n` +
                           `💵 Số tiền: ${amount.toLocaleString()}đ\n` +
                           `🪙 Coin nhận: +${coins}\n` +
                           `📝 Nội dung: ${code}\n` +
                           `🔑 Mã GD: \`${tidDisplay}\``;
           await notifyTelegram(message);

           // Affiliate / Referral commission - isolated, must never block topup flow
           try {
             await payReferralCommission(state.token, state.cfg.project_id, {
               topupId: topup.id,
               referredUserId: topup.userId,
               referredUserEmail: topup.userEmail,
               referredUserName: topup.userName,
               baseCoins: coins,
               baseAmount: topup.amount || amount,
               currency: 'VND',
               gateway: 'casso'
             });
           } catch (refErr) {
             console.error('[Referral] Casso commission error (non-blocking):', refErr.message);
             try { await notifyTelegram(`⚠️ *LỖI TRẢ HOA HỒNG GIỚI THIỆU (CASSO)*\nTopup: ${topup.id}\nLỗi: ${refErr.message}`); } catch (e) { }
           }
        }
      }

      return new Response(JSON.stringify({ success: true }), { headers: { "Content-Type": "application/json" } });
    } catch (err) {
      console.error("Critical Webhook Error:", err.message);
      // Gửi lỗi về Telegram để b biết chính xác chuyện gì đang xảy ra
      await notifyTelegram(`❌ *LỖI WEBHOOK CRITICAL!*\n\n` +
                           `📝 Thông báo: ${err.message}\n` +
                           `🔍 Hãy kiểm tra Logs trên Cloudflare để xem chi tiết.`);
      return new Response(JSON.stringify({ error: err.message }), { status: 500 });
    }
}

// --- Helpers ---

async function getAccessToken(email, privateKey) {
  const iat = Math.floor(Date.now() / 1000);
  const exp = iat + 3600;
  
  const header = b64(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const payload = b64(JSON.stringify({
    iss: email,
    scope: "https://www.googleapis.com/auth/datastore",
    aud: "https://oauth2.googleapis.com/token",
    exp, iat
  }));

  const message = `${header}.${payload}`;
  
  // Clean PEM Key - Siêu phòng thủ
  let pemContents = privateKey
    .replace(/-----BEGIN PRIVATE KEY-----/g, "")
    .replace(/-----END PRIVATE KEY-----/g, "")
    .replace(/\s+/g, "") // Xóa bỏ tất cả khoảng trắng, xuống dòng, tab...
    .replace(/\\n/g, ""); // Xóa bỏ ký tự \n nếu có
    
  while (pemContents.length % 4 !== 0) pemContents += "=";
    
  const binaryDerString = atob(pemContents);
  const binaryDer = new Uint8Array(binaryDerString.length);
  for (let i = 0; i < binaryDerString.length; i++) {
    binaryDer[i] = binaryDerString.charCodeAt(i);
  }
  
  const key = await crypto.subtle.importKey(
    "pkcs8", binaryDer, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]
  );
  
  const signature = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(message));
  const jwt = `${message}.${b64(String.fromCharCode(...new Uint8Array(signature)))}`;

  const res = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=${jwt}`
  });
  
  const data = await res.json();
  if (data.error) throw new Error("Google Auth Error: " + (data.error_description || data.error));
  return data.access_token;
}

async function userHasApprovedStarterTopup(token, projectId, userId, excludeTopupId = '') {
  const url = `https://firestore.googleapis.com/v1/projects/${projectId}/databases/(default)/documents:runQuery`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Authorization": `Bearer ${token}` },
    body: JSON.stringify({
      structuredQuery: {
        from: [{ collectionId: "topups" }],
        where: {
          compositeFilter: {
            op: "AND",
            filters: [
              { fieldFilter: { field: { fieldPath: "userId" }, op: "EQUAL", value: { stringValue: userId } } },
              { fieldFilter: { field: { fieldPath: "status" }, op: "EQUAL", value: { stringValue: "approved" } } }
            ]
          }
        },
        limit: 100
      }
    })
  });
  const data = await res.json();
  if (!Array.isArray(data)) return false;

  return data.some((item) => {
    if (!item.document) return false;
    const id = item.document.name.split("/").pop();
    if (excludeTopupId && id === excludeTopupId) return false;
    const fields = item.document.fields || {};
    const packageId = fields.packageId?.stringValue || '';
    if (packageId === 'starter_v2') return true;
    const coins = parseInt(fields.coins?.integerValue || 0);
    const amount = parseInt(fields.amount?.integerValue || fields.amount?.doubleValue || 0);
    return coins === 10 && amount === 10000;
  });
}

async function fetchPendingTopups(token, projectId) {
  const PROJECT_ID = projectId;
  const url = `https://firestore.googleapis.com/v1/projects/${PROJECT_ID}/databases/(default)/documents:runQuery`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Authorization": `Bearer ${token}` },
    body: JSON.stringify({
      structuredQuery: {
        from: [{ collectionId: "topups" }],
        where: {
          fieldFilter: { field: { fieldPath: "status" }, op: "EQUAL", value: { stringValue: "pending" } }
        },
        limit: 1000
      }
    })
  });
  const data = await res.json();
  if (!Array.isArray(data)) return [];
  
  return data
    .filter(item => item.document)
    .map(item => {
      const doc = item.document;
      const fields = doc.fields;
      return {
        id: doc.name.split("/").pop(),
        userId: fields.userId.stringValue,
        status: fields.status.stringValue,
        transferContent: fields.transferContent.stringValue,
        coins: parseInt(fields.coins?.integerValue || 0),
        userName: fields.userName?.stringValue || 'Khách',
        userEmail: fields.userEmail?.stringValue || '',
        amount: parseInt(fields.amount?.integerValue || fields.amount?.doubleValue || fields.amount?.stringValue || 0)
      };
    });
}

async function grantCoins(token, projectId, userId, coins, topupId) {
  const PROJECT_ID = projectId;
  const baseUrl = `https://firestore.googleapis.com/v1/projects/${PROJECT_ID}/databases/(default)/documents`;
  
  const userRes = await fetch(`${baseUrl}/users/${userId}`, { headers: { "Authorization": `Bearer ${token}` } });
  const userData = await userRes.json();
  const current = parseInt(userData.fields.coins?.integerValue || 0);

  await fetch(`${baseUrl}/users/${userId}?updateMask.fieldPaths=coins`, {
    method: "PATCH",
    headers: { "Authorization": `Bearer ${token}` },
    body: JSON.stringify({ fields: { coins: { integerValue: current + coins } } })
  });

  await fetch(`${baseUrl}/topups/${topupId}?updateMask.fieldPaths=status`, {
    method: "PATCH",
    headers: { "Authorization": `Bearer ${token}` },
    body: JSON.stringify({ fields: { status: { stringValue: "approved" } } })
  });
}

function b64(str) { return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); }

async function notifyTelegram(text) {
  const url = `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`;
  const body = text.startsWith('[Kaling]') ? text : `[Kaling] ${text}`;
  try {
    await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: TELEGRAM_CHAT_ID,
        text: body,
        parse_mode: "Markdown"
      })
    });
  } catch (err) {
    console.error("Telegram Notify Error:", err.message);
  }
}

// --- Affiliate / Referral Commission ---
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

/**
 * Record 10% referral commission (money only — no coin credit to referrer).
 * Idempotent: uses topupId as the referralEarnings doc ID and aborts if it already exists.
 */
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
  const authHeader = { "Authorization": `Bearer ${token}` };

  const referredUserRes = await fetch(`${baseUrl}/users/${referredUserId}`, { headers: authHeader });
  if (!referredUserRes.ok) {
    if (referredUserRes.status === 404) return;
    throw new Error(`Read referred user failed: ${referredUserRes.status}`);
  }
  const referredUserData = await referredUserRes.json();
  const referredBy = referredUserData.fields?.referredBy?.stringValue;
  if (!referredBy) return;
  if (referredBy === referredUserId) return;

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
    referrerId: { stringValue: referredBy },
    referrerName: { stringValue: referrerName },
    referrerEmail: { stringValue: referrerEmail },
    referredUserId: { stringValue: referredUserId },
    referredUserEmail: { stringValue: referredUserEmail || referredUserData.fields?.email?.stringValue || '' },
    referredUserName: { stringValue: referredUserName || referredUserData.fields?.displayName?.stringValue || '' },
    topupId: { stringValue: topupId },
    baseCoins: { integerValue: baseCoins },
    commissionCoins: { integerValue: 0 },
    commissionRate: { doubleValue: REFERRAL_COMMISSION_RATE },
    gateway: { stringValue: gateway || 'unknown' },
    currency: { stringValue: cur },
    payoutStatus: { stringValue: 'recorded' },
    createdAt: { timestampValue: new Date().toISOString() }
  };
  if (effectiveBaseAmount > 0) {
    earningsFields.baseAmount = firestoreAmountField(effectiveBaseAmount, cur);
  }
  earningsFields.commissionAmount = firestoreAmountField(commissionAmount, cur);

  const earningsBody = { fields: earningsFields };

  const createUrl = `${baseUrl}/referralEarnings?documentId=${encodeURIComponent(topupId)}`;
  const createRes = await fetch(createUrl, {
    method: "POST",
    headers: { ...authHeader, "Content-Type": "application/json" },
    body: JSON.stringify(earningsBody)
  });

  if (createRes.status === 409) {
    console.log(`[Referral] Commission already paid for topup ${topupId} - skipped (idempotent).`);
    return;
  }
  if (!createRes.ok) {
    const txt = await createRes.text();
    throw new Error(`Create referralEarnings failed (${createRes.status}): ${txt}`);
  }

  console.log(`[Referral] Recorded ${commissionAmount} ${cur} commission for ${referredBy} (topup ${topupId}, gateway=${gateway})`);

  try {
    await notifyTelegram(
      `🎁 *HOA HỒNG GIỚI THIỆU \\(${gateway}\\)*\n\n` +
      `👤 Người giới thiệu: ${referrerName}\n` +
      `📧 Email: ${referrerEmail}\n` +
      `💵 Hoa hồng: ${formatMoneyForTelegram(commissionAmount, cur)}\n` +
      `🛒 Người được mời nạp: ${referredUserName || 'N/A'} (${formatMoneyForTelegram(effectiveBaseAmount, cur) || baseCoins + ' Coin'})\n` +
      `🔑 Topup ID: ${topupId}`
    );
  } catch (e) { /* swallow */ }
}
