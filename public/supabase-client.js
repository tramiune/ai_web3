/**
 * Kaling (kaling.cloud) — Shared Supabase Client & Data Layer
 * Connects to aquaai.vn's Supabase project (omqyvuwdyqpolvxbntru) using
 * isolated kaling_* tables + atomic SECURITY DEFINER RPCs.
 */

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2.49.4';

export const SUPABASE_URL = 'https://omqyvuwdyqpolvxbntru.supabase.co';
export const SUPABASE_ANON_KEY = 'sb_publishable_mx4GztfvRIdSDKGG3JNPGw_C3Pa8G3s';
export const ADMIN_EMAILS = ['traderfinn0312@gmail.com', 'dinhhoangvan.hh@gmail.com'];
export const AQUA_ADMIN_KALING_URL = 'https://aquaai.vn/admin?app=kaling';

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
        storageKey: 'kaling_sb_auth',
    },
});

// ---------------------------------------------------------------------------
// Timestamp & Field Mappers (Supabase snake_case -> Frontend camelCase)
// ---------------------------------------------------------------------------

/**
 * Wraps an ISO timestamp string in a Firestore-Timestamp-compatible object so
 * existing UI code using `.seconds`, `.toDate()`, `.toMillis()`, or `safeToDate()`
 * works seamlessly with zero edge-case drift.
 */
export function toCompatTimestamp(isoVal) {
    if (!isoVal) return null;
    if (typeof isoVal === 'object' && typeof isoVal.toMillis === 'function') return isoVal;
    const ms = typeof isoVal === 'number' ? isoVal : Date.parse(String(isoVal));
    if (!Number.isFinite(ms)) return null;
    const seconds = Math.floor(ms / 1000);
    const iso = new Date(ms).toISOString();
    return {
        seconds,
        _seconds: seconds,
        toDate: () => new Date(ms),
        toMillis: () => ms,
        valueOf: () => ms,
        toISOString: () => iso,
        toString: () => iso,
    };
}

export function mapKalingUserRow(row) {
    if (!row) return null;
    const extra = (row.extra && typeof row.extra === 'object') ? row.extra : {};
    return {
        ...extra,
        uid: row.id,
        id: row.id,
        authUserId: row.auth_user_id || null,
        email: row.email || '',
        displayName: row.display_name || (row.email ? row.email.split('@')[0] : ''),
        photoURL: row.photo_url || '',
        coins: Number(row.coins ?? 0),
        role: row.role || 'user',
        apiKey: row.api_key || '',
        referralCode: row.referral_code || '',
        referredBy: row.referred_by || '',
        promo1CoinCount: Number(row.promo_1_coin_count ?? 0),
        promo1CoinLastDay: row.promo_1_coin_last_day || '',
        createdAt: toCompatTimestamp(row.created_at),
        updatedAt: toCompatTimestamp(row.updated_at),
    };
}

export function mapKalingOrderRow(row) {
    if (!row) return null;
    const extra = (row.extra && typeof row.extra === 'object') ? row.extra : {};
    return {
        ...extra,
        id: row.id,
        userId: row.user_id || '',
        userEmail: row.user_email || '',
        userName: row.user_name || '',
        packageName: row.package_name || '',
        status: row.status || 'pending',
        modelId: row.model_id || '',
        renderProvider: row.render_provider || '',
        maxVideoSec: row.max_video_sec ?? null,
        qualityMode: row.quality_mode || '',
        quality: row.quality || '',
        aspectRatio: row.aspect_ratio || '16:9',
        vaeResolution: row.vae_resolution || '',
        vaeDurationSec: row.vae_duration_sec ?? null,
        serviceType: row.service_type || '',
        serviceLabel: row.service_label || '',
        characterImageLink: row.character_image_link || '',
        referenceVideoLink: row.reference_video_link || '',
        resultLink: row.result_link || '',
        costCoins: Number(row.cost_coins ?? 0),
        promo1Coin: Boolean(row.promo_1_coin),
        roboneoTrial: Boolean(row.roboneo_trial),
        isBatchChannel: Boolean(row.is_batch_channel),
        batchChannelRunId: row.batch_channel_run_id || '',
        clientVersion: row.client_version ?? null,
        referer: row.referer || '',
        adminNote: row.admin_note || '',
        systemNote: row.system_note || '',
        errorMessage: row.error_message || '',
        submittedAt: toCompatTimestamp(row.submitted_at),
        createdAt: toCompatTimestamp(row.created_at),
        updatedAt: toCompatTimestamp(row.updated_at),
    };
}

export function mapKalingTopupRow(row) {
    if (!row) return null;
    const extra = (row.extra && typeof row.extra === 'object') ? row.extra : {};
    return {
        ...extra,
        id: row.id,
        userId: row.user_id || '',
        userEmail: row.user_email || '',
        userName: row.user_name || '',
        packageId: row.package_id || '',
        packageName: row.package_name || '',
        coins: Number(row.coins ?? 0),
        amount: Number(row.amount ?? 0),
        currency: row.currency || 'VND',
        transferContent: row.transfer_content || '',
        status: row.status || 'pending',
        isAutomated: row.is_automated !== false,
        gateway: row.gateway || 'casso',
        createdAt: toCompatTimestamp(row.created_at),
        updatedAt: toCompatTimestamp(row.updated_at),
    };
}

export function mapReferralEarningRow(row) {
    if (!row) return null;
    return {
        id: row.id,
        topupId: row.topup_id || row.id,
        referrerId: row.referrer_id || '',
        referrerName: row.referrer_name || '',
        referrerEmail: row.referrer_email || '',
        referredUserId: row.referred_user_id || '',
        referredUserEmail: row.referred_user_email || '',
        referredUserName: row.referred_user_name || '',
        baseCoins: Number(row.base_coins ?? 0),
        baseAmount: Number(row.base_amount ?? 0),
        commissionCoins: Number(row.commission_coins ?? 0),
        commissionAmount: Number(row.commission_amount ?? 0),
        commissionRate: Number(row.commission_rate ?? 0.10),
        currency: row.currency || 'VND',
        gateway: row.gateway || 'casso',
        payoutStatus: row.payout_status || 'recorded',
        createdAt: toCompatTimestamp(row.created_at),
    };
}

export function mapBatchConfigRow(row) {
    if (!row) return null;
    const extra = (row.extra && typeof row.extra === 'object') ? row.extra : {};
    return {
        ...extra,
        id: row.id,
        channelUrl: row.channel_url || '',
        channelUsername: row.channel_username || '',
        sourceMode: row.source_mode || '',
        templateImageUrl: row.template_image_url || '',
        wardrobeReplace: row.wardrobe_replace || 'full',
        batchModelKey: row.batch_model_key || 'ad10',
        modelId: row.model_id || '',
        renderProvider: row.render_provider || '',
        serviceLabel: row.service_label || '',
        costCoins: row.cost_coins != null ? Number(row.cost_coins) : null,
        maxVideoSec: row.max_video_sec ?? null,
        vaeDurationSec: row.vae_duration_sec ?? null,
        vaeResolution: row.vae_resolution || '',
        cronHour: row.cron_hour ?? 3,
        frameSec: row.frame_sec != null ? Number(row.frame_sec) : 2.5,
        enabled: Boolean(row.enabled),
        selectedOrderIds: Array.isArray(row.selected_order_ids) ? row.selected_order_ids : [],
        activeRunId: row.active_run_id || '',
        activeRunPhase: row.active_run_phase || '',
        activeRunStatus: row.active_run_status || '',
        activeRunVideosFound: row.active_run_videos_found ?? 0,
        activeRunOrdersCreated: row.active_run_orders_created ?? 0,
        activeRunErrors: Array.isArray(row.active_run_errors) ? row.active_run_errors : [],
        runNowRequestedAt: toCompatTimestamp(row.run_now_requested_at),
        runNowHandledAt: toCompatTimestamp(row.run_now_handled_at),
        runNowMode: row.run_now_mode || '',
        lastRunAt: toCompatTimestamp(row.last_run_at),
        lastRunStatus: row.last_run_status || '',
        lastRunMessage: row.last_run_message || '',
        lastDailyCronDateVN: row.last_daily_cron_date_vn || '',
        yesterdayVideoCount: row.yesterday_video_count ?? 0,
        createdBy: row.created_by || '',
        createdByEmail: row.created_by_email || '',
        createdByName: row.created_by_name || '',
        startedAt: toCompatTimestamp(row.started_at),
        updatedAt: toCompatTimestamp(row.updated_at),
    };
}

export function batchConfigPayloadToRow(configId, payload) {
    const nowIso = new Date().toISOString();
    const row = {
        id: configId,
        enabled: Boolean(payload.enabled),
        channel_url: payload.channelUrl || '',
        channel_username: payload.channelUsername || '',
        template_image_url: payload.templateImageUrl || '',
        source_mode: payload.sourceMode || 'tiktok',
        batch_model_key: payload.batchModelKey || 'ad10',
        model_id: String(payload.modelId || ''),
        render_provider: payload.renderProvider || '',
        vae_duration_sec: payload.vaeDurationSec ?? null,
        vae_resolution: payload.vaeResolution || '',
        max_video_sec: payload.maxVideoSec ?? null,
        cost_coins: payload.costCoins != null ? Number(payload.costCoins) : null,
        service_label: payload.serviceLabel || '',
        cron_hour: payload.cronHour ?? 3,
        yesterday_video_count: payload.yesterdayVideoCount ?? 0,
        wardrobe_replace: payload.wardrobeReplace || 'full',
        frame_sec: payload.frameSec != null ? Number(payload.frameSec) : 2.5,
        selected_order_ids: Array.isArray(payload.selectedOrderIds) ? payload.selectedOrderIds : [],
        created_by: payload.createdBy || configId,
        created_by_email: (payload.createdByEmail || '').trim().toLowerCase(),
        created_by_name: payload.createdByName || '',
        updated_at: nowIso,
    };
    if (payload.triggerRun) {
        row.run_now_requested_at = nowIso;
        row.run_now_mode = payload.runNowMode || 'full';
        row.active_run_status = payload.activeRunStatus || 'queued';
        row.active_run_phase = payload.activeRunPhase || '';
        row.active_run_videos_found = 0;
        row.active_run_orders_created = 0;
        row.active_run_errors = [];
    }
    return row;
}

function generateId(prefix = 'kl_') {
    const arr = new Uint8Array(10);
    if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
        crypto.getRandomValues(arr);
    } else {
        for (let i = 0; i < arr.length; i++) arr[i] = Math.floor(Math.random() * 256);
    }
    return prefix + Array.from(arr, (b) => b.toString(16).padStart(2, '0')).join('');
}

// ---------------------------------------------------------------------------
// High-level Kaling API (Auth, Profile, Orders, Topups, Referral, Batch, API)
// ---------------------------------------------------------------------------

const OAUTH_POPUP_NAME = 'kaling_google_oauth';
const OAUTH_CHANNEL_NAME = 'kaling_oauth_channel';
const OAUTH_POPUP_PENDING_KEY = 'kaling_oauth_popup_pending';
const OAUTH_POPUP_RESULT_KEY = 'kaling_oauth_popup_result';
const OAUTH_REDIRECT_CTX_KEY = 'kaling_oauth_redirect_ctx';

let _activeOAuthPopupCleanup = null;

function openCenteredOAuthPopup(name) {
    const w = 500;
    const h = 650;
    const dualLeft = typeof window.screenLeft === 'number' ? window.screenLeft : (window.screenX || 0);
    const dualTop = typeof window.screenTop === 'number' ? window.screenTop : (window.screenY || 0);
    const viewW = window.innerWidth || document.documentElement.clientWidth || screen.width;
    const viewH = window.innerHeight || document.documentElement.clientHeight || screen.height;
    const left = Math.max(0, Math.round(dualLeft + (viewW - w) / 2));
    const top = Math.max(0, Math.round(dualTop + (viewH - h) / 2));
    const features = `width=${w},height=${h},left=${left},top=${top},scrollbars=yes,resizable=yes`;
    let popup = null;
    try {
        popup = window.open('about:blank', name, features);
    } catch (_) {
        popup = null;
    }
    if (popup && !popup.closed) {
        try {
            popup.document.title = 'Đăng nhập Google — Kaling';
            popup.document.body.style.cssText = 'margin:0;background:#0b0d14;color:#e5e7eb;font-family:system-ui,-apple-system,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;text-align:center;';
            popup.document.body.innerHTML = '<div><div style="font-size:15px;font-weight:600;margin-bottom:8px;">Đang mở đăng nhập Google...</div><div style="font-size:12px;opacity:.65;">Vui lòng chờ trong giây lát</div></div>';
        } catch (_) { /* ignore cross-origin */ }
    }
    return popup;
}

function saveOAuthRedirectContext() {
    try {
        localStorage.setItem(OAUTH_REDIRECT_CTX_KEY, JSON.stringify({
            search: window.location.search || '',
            pendingAction: window.pendingAction || null,
            ts: Date.now(),
        }));
    } catch (_) { /* ignore storage errors */ }
}

function clearOAuthPopupMarkers() {
    try { localStorage.removeItem(OAUTH_POPUP_PENDING_KEY); } catch (_) {}
    try { localStorage.removeItem(OAUTH_POPUP_RESULT_KEY); } catch (_) {}
}

function parseOAuthCallbackError() {
    const hashParams = new URLSearchParams((window.location.hash || '').replace(/^#/, ''));
    const queryParams = new URLSearchParams(window.location.search || '');
    const err = hashParams.get('error_description') || hashParams.get('error')
        || queryParams.get('error_description') || queryParams.get('error');
    return err ? String(err) : null;
}

export const kalingApi = {
    supabase,

    /**
     * Runs at page boot inside an OAuth popup callback window.
     * Hands the freshly obtained Supabase session back to the opener/main tab
     * via BroadcastChannel + postMessage + localStorage, then closes the popup.
     * Returns true if the main tab acknowledged the handoff and this popup closed
     * (or is closing), so the popup skips booting the full app UI.
     */
    async handleOAuthPopupCallbackIfNeeded() {
        if (!window.__OAUTH_IS_POPUP_CALLBACK) return false;

        try {
            document.documentElement.style.background = '#0b0d14';
            if (document.body) {
                document.body.style.cssText = 'margin:0;background:#0b0d14;color:#e5e7eb;font-family:system-ui,-apple-system,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;text-align:center;';
                document.body.innerHTML = '<div><div style="font-size:15px;font-weight:600;">Đang hoàn tất đăng nhập...</div></div>';
            }
        } catch (_) {}

        const oauthErr = parseOAuthCallbackError();
        let session = null;
        if (!oauthErr) {
            try {
                const { data } = await supabase.auth.getSession();
                session = data?.session || null;
            } catch (e) {
                console.warn('[KalingSB] popup getSession failed:', e);
            }
        }

        const payload = oauthErr
            ? { type: 'oauth_error', channel: OAUTH_CHANNEL_NAME, error: oauthErr, ts: Date.now() }
            : {
                type: 'oauth_done',
                channel: OAUTH_CHANNEL_NAME,
                access_token: session?.access_token || '',
                refresh_token: session?.refresh_token || '',
                uid: session?.user?.id || '',
                ts: Date.now(),
            };

        try { localStorage.removeItem(OAUTH_POPUP_PENDING_KEY); } catch (_) {}

        let acked = false;
        let bc = null;
        const ackPromise = new Promise((resolve) => {
            const onAck = () => {
                if (acked) return;
                acked = true;
                resolve(true);
            };
            try {
                if (typeof BroadcastChannel !== 'undefined') {
                    bc = new BroadcastChannel(OAUTH_CHANNEL_NAME);
                    bc.onmessage = (ev) => {
                        if (ev?.data?.type === 'oauth_ack') onAck();
                    };
                    bc.postMessage(payload);
                }
            } catch (_) {}

            try {
                if (window.opener && !window.opener.closed) {
                    window.opener.postMessage(payload, window.location.origin);
                }
            } catch (_) {}

            try {
                localStorage.setItem(OAUTH_POPUP_RESULT_KEY, JSON.stringify(payload));
            } catch (_) {}

            setTimeout(() => resolve(acked), 450);
        });

        await ackPromise;
        try { bc?.close(); } catch (_) {}

        if (acked) {
            try { window.close(); } catch (_) {}
            // Safety fallback: if mobile OS refuses window.close(), reload cleanly as logged-in app
            await new Promise((r) => setTimeout(r, 650));
            if (!window.closed) {
                window.location.replace(window.location.origin + '/');
            }
            return true;
        }

        // Main tab did not ACK (e.g., iOS evicted the original tab in background).
        // Mark fromPopupFallback so the clean reload suppresses duplicate PageView and restores pendingAction.
        try {
            const rawCtx = localStorage.getItem(OAUTH_REDIRECT_CTX_KEY);
            let target = window.location.origin + '/';
            if (rawCtx) {
                const ctx = JSON.parse(rawCtx);
                if (ctx && ctx.ts && (Date.now() - ctx.ts) < 10 * 60 * 1000) {
                    ctx.fromPopupFallback = true;
                    localStorage.setItem(OAUTH_REDIRECT_CTX_KEY, JSON.stringify(ctx));
                    if (ctx.search) {
                        target = window.location.origin + '/' + ctx.search;
                    }
                }
            }
            window.location.replace(target);
        } catch (_) {
            window.location.replace(window.location.origin + '/');
        }
        return true;
    },

    async signInWithGoogle() {
        // Cancel any previous in-flight popup watcher
        if (typeof _activeOAuthPopupCleanup === 'function') {
            _activeOAuthPopupCleanup();
            _activeOAuthPopupCleanup = null;
        }

        // Persist fbclid/utm & pendingAction so both redirect fallback and evicted-tab recovery preserve them
        saveOAuthRedirectContext();
        try { localStorage.removeItem(OAUTH_POPUP_RESULT_KEY); } catch (_) {}
        try { localStorage.setItem(OAUTH_POPUP_PENDING_KEY, String(Date.now())); } catch (_) {}

        // CRITICAL: open popup SYNCHRONOUSLY in click handler before any await so iOS Safari/Chrome don't block it
        const popup = openCenteredOAuthPopup(OAUTH_POPUP_NAME);
        const redirectTo = window.location.origin + '/';

        const { data, error } = await supabase.auth.signInWithOAuth({
            provider: 'google',
            options: {
                redirectTo,
                skipBrowserRedirect: true,
                queryParams: { prompt: 'select_account' },
            },
        });

        if (error || !data?.url) {
            clearOAuthPopupMarkers();
            if (popup && !popup.closed) {
                try { popup.close(); } catch (_) {}
            }
            throw error || new Error('Không lấy được đường dẫn đăng nhập Google');
        }

        // Fallback to full-page redirect if browser blocked the popup
        if (!popup || popup.closed) {
            try { localStorage.removeItem(OAUTH_POPUP_PENDING_KEY); } catch (_) {}
            window.location.assign(data.url);
            return { redirected: true };
        }

        try {
            popup.location.href = data.url;
            popup.focus();
        } catch (_) {
            try { localStorage.removeItem(OAUTH_POPUP_PENDING_KEY); } catch (_) {}
            window.location.assign(data.url);
            return { redirected: true };
        }

        return await new Promise((resolve, reject) => {
            let settled = false;
            let bc = null;
            let pollTimer = null;
            let timeoutTimer = null;

            const cleanup = () => {
                if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
                if (timeoutTimer) { clearTimeout(timeoutTimer); timeoutTimer = null; }
                window.removeEventListener('message', onMessage);
                window.removeEventListener('storage', onStorage);
                try { bc?.close(); } catch (_) {}
                bc = null;
                if (_activeOAuthPopupCleanup === cleanup) _activeOAuthPopupCleanup = null;
            };
            _activeOAuthPopupCleanup = cleanup;

            const finishWithPayload = async (msg) => {
                if (settled || !msg) return;
                if (msg.type === 'oauth_error') {
                    settled = true;
                    try { bc?.postMessage({ type: 'oauth_ack' }); } catch (_) {}
                    clearOAuthPopupMarkers();
                    try { localStorage.removeItem(OAUTH_REDIRECT_CTX_KEY); } catch (_) {}
                    cleanup();
                    if (popup && !popup.closed) { try { popup.close(); } catch (_) {} }
                    if (String(msg.error || '').toLowerCase().includes('access_denied')) {
                        resolve({ cancelled: true });
                    } else {
                        reject(new Error(msg.error || 'Đăng nhập Google thất bại'));
                    }
                    return;
                }
                if (msg.type !== 'oauth_done') return;

                settled = true;
                try { bc?.postMessage({ type: 'oauth_ack' }); } catch (_) {}
                clearOAuthPopupMarkers();
                try { localStorage.removeItem(OAUTH_REDIRECT_CTX_KEY); } catch (_) {}
                cleanup();
                if (popup && !popup.closed) { try { popup.close(); } catch (_) {} }

                try {
                    if (msg.access_token && msg.refresh_token) {
                        const { data: sessData } = await supabase.auth.setSession({
                            access_token: msg.access_token,
                            refresh_token: msg.refresh_token,
                        });
                        resolve({ session: sessData?.session || null });
                        return;
                    }
                    const { data: sessData } = await supabase.auth.getSession();
                    resolve({ session: sessData?.session || null });
                } catch (e) {
                    reject(e);
                }
            };

            const onMessage = (ev) => {
                if (ev.origin !== window.location.origin) return;
                if (ev?.data?.channel !== OAUTH_CHANNEL_NAME) return;
                finishWithPayload(ev.data);
            };

            const onStorage = (ev) => {
                if (ev.key === OAUTH_POPUP_RESULT_KEY && ev.newValue) {
                    try {
                        finishWithPayload(JSON.parse(ev.newValue));
                    } catch (_) {}
                } else if (ev.key === 'kaling_sb_auth' && ev.newValue) {
                    supabase.auth.getSession().then(({ data: sd }) => {
                        if (sd?.session) {
                            finishWithPayload({
                                type: 'oauth_done',
                                access_token: sd.session.access_token,
                                refresh_token: sd.session.refresh_token,
                            });
                        }
                    }).catch(() => {});
                }
            };

            try {
                if (typeof BroadcastChannel !== 'undefined') {
                    bc = new BroadcastChannel(OAUTH_CHANNEL_NAME);
                    bc.onmessage = (ev) => finishWithPayload(ev?.data);
                }
            } catch (_) {}

            window.addEventListener('message', onMessage);
            window.addEventListener('storage', onStorage);

            pollTimer = setInterval(async () => {
                if (settled) return;
                // Check localStorage result directly in case storage event was coalesced
                try {
                    const raw = localStorage.getItem(OAUTH_POPUP_RESULT_KEY);
                    if (raw) {
                        const parsed = JSON.parse(raw);
                        if (parsed && parsed.ts && (Date.now() - parsed.ts) < 5 * 60 * 1000) {
                            finishWithPayload(parsed);
                            return;
                        }
                    }
                } catch (_) {}

                let isClosed = false;
                try { isClosed = Boolean(popup.closed); } catch (_) { isClosed = false; }
                if (isClosed) {
                    // Brief grace window for localStorage commit before treating as user cancel
                    setTimeout(async () => {
                        if (settled) return;
                        try {
                            const { data: sd } = await supabase.auth.getSession();
                            if (sd?.session) {
                                finishWithPayload({
                                    type: 'oauth_done',
                                    access_token: sd.session.access_token,
                                    refresh_token: sd.session.refresh_token,
                                });
                                return;
                            }
                        } catch (_) {}
                        settled = true;
                        clearOAuthPopupMarkers();
                        try { localStorage.removeItem(OAUTH_REDIRECT_CTX_KEY); } catch (_) {}
                        cleanup();
                        resolve({ cancelled: true });
                    }, 350);
                }
            }, 450);

            timeoutTimer = setTimeout(() => {
                if (settled) return;
                settled = true;
                clearOAuthPopupMarkers();
                cleanup();
                resolve({ cancelled: true });
            }, 5 * 60 * 1000);
        });
    },

    async signOut() {
        const { error } = await supabase.auth.signOut();
        if (error) throw error;
    },

    onAuthChange(cb) {
        let lastSessionUid = '__INIT__';
        const emit = (session) => {
            const uid = session?.user?.id || null;
            if (uid === lastSessionUid) return;
            lastSessionUid = uid;
            cb(session?.user || null, session || null);
        };

        supabase.auth.getSession().then(({ data }) => {
            emit(data?.session || null);
        }).catch((err) => {
            console.error('[KalingSB] getSession failed:', err);
            emit(null);
        });

        const { data: sub } = supabase.auth.onAuthStateChange((event, session) => {
            if (event === 'SIGNED_OUT') {
                lastSessionUid = '__SIGNED_OUT__';
                emit(null);
            } else if (event === 'SIGNED_IN' || event === 'INITIAL_SESSION' || event === 'USER_UPDATED' || event === 'TOKEN_REFRESHED') {
                emit(session || null);
            }
        });
        return () => sub?.subscription?.unsubscribe?.();
    },

    async linkOrCreateUser(pendingRefCode = null) {
        const { data, error } = await supabase.rpc('kaling_link_or_create_user', {
            p_referred_by: pendingRefCode || null,
        });
        if (error) throw error;
        return {
            user: mapKalingUserRow(data?.user),
            isNew: Boolean(data?.is_new),
            isReferralAllowed: Boolean(data?.is_referral_allowed),
            isBatchChannelAllowed: Boolean(data?.is_batch_channel_allowed),
        };
    },

    async getUserProfile(kalingUid) {
        const { data, error } = await supabase
            .from('kaling_users')
            .select('*')
            .eq('id', kalingUid)
            .maybeSingle();
        if (error) throw error;
        return mapKalingUserRow(data);
    },

    subscribeUserProfile(kalingUid, onData) {
        let stopped = false;
        let lastJson = '';

        const pull = async () => {
            if (stopped) return;
            try {
                const u = await kalingApi.getUserProfile(kalingUid);
                if (!u || stopped) return;
                const sig = `${u.coins}|${u.role}|${u.apiKey}|${u.referralCode}|${u.displayName}`;
                if (sig !== lastJson) {
                    lastJson = sig;
                    onData(u);
                }
            } catch (e) {
                console.warn('[KalingSB] profile pull:', e.message);
            }
        };

        pull();

        const channel = supabase
            .channel(`kaling-user-${kalingUid}`)
            .on(
                'postgres_changes',
                { event: '*', schema: 'public', table: 'kaling_users', filter: `id=eq.${kalingUid}` },
                (payload) => {
                    if (stopped || !payload?.new) return;
                    const u = mapKalingUserRow(payload.new);
                    if (!u) return;
                    const sig = `${u.coins}|${u.role}|${u.apiKey}|${u.referralCode}|${u.displayName}`;
                    lastJson = sig;
                    onData(u);
                }
            )
            .subscribe();

        // Lightweight safety poll (fast while topup modal is open, gentle otherwise)
        const timer = setInterval(() => {
            const topupOpen = document.getElementById('topup-modal')?.style?.display === 'flex';
            if (topupOpen) pull();
        }, 4000);

        return () => {
            stopped = true;
            clearInterval(timer);
            supabase.removeChannel(channel);
        };
    },

    async fetchMyOrders(kalingUid, maxRows = 200) {
        const { data, error } = await supabase
            .from('kaling_orders')
            .select('*')
            .eq('user_id', kalingUid)
            .order('created_at', { ascending: false })
            .limit(maxRows);
        if (error) throw error;
        return (data || []).map(mapKalingOrderRow);
    },

    async getOrderById(orderId) {
        const { data, error } = await supabase
            .from('kaling_orders')
            .select('*')
            .eq('id', orderId)
            .maybeSingle();
        if (error) throw error;
        return mapKalingOrderRow(data);
    },

    subscribeMyOrders(kalingUid, onList) {
        let stopped = false;
        let byId = new Map();
        let initialized = false;

        const emit = (changes = []) => {
            if (stopped) return;
            const list = Array.from(byId.values()).sort(
                (a, b) => (b.createdAt?.seconds || 0) - (a.createdAt?.seconds || 0)
            );
            onList(list, changes);
        };

        const pull = async () => {
            if (stopped) return;
            try {
                const rows = await kalingApi.fetchMyOrders(kalingUid, 200);
                if (stopped) return;
                const changes = [];
                const nextMap = new Map();
                for (const r of rows) {
                    nextMap.set(r.id, r);
                    if (initialized) {
                        const prev = byId.get(r.id);
                        if (prev && prev.status !== r.status) {
                            changes.push({ type: 'modified', doc: r });
                        }
                    }
                }
                byId = nextMap;
                initialized = true;
                emit(changes);
            } catch (e) {
                console.warn('[KalingSB] orders pull:', e.message);
            }
        };

        pull();

        const channel = supabase
            .channel(`kaling-orders-${kalingUid}`)
            .on(
                'postgres_changes',
                { event: '*', schema: 'public', table: 'kaling_orders', filter: `user_id=eq.${kalingUid}` },
                (payload) => {
                    if (stopped) return;
                    if (payload.eventType === 'DELETE') {
                        const oldId = payload.old?.id;
                        if (oldId && byId.has(oldId)) {
                            byId.delete(oldId);
                            emit([]);
                        }
                        return;
                    }
                    const mapped = mapKalingOrderRow(payload.new);
                    if (!mapped) return;
                    const prev = byId.get(mapped.id);
                    const changes = [];
                    if (initialized && prev && prev.status !== mapped.status) {
                        changes.push({ type: 'modified', doc: mapped });
                    }
                    byId.set(mapped.id, mapped);
                    emit(changes);
                }
            )
            .subscribe();

        // Fallback poll every 12s only while user has pending/processing orders
        const timer = setInterval(() => {
            const hasActive = Array.from(byId.values()).some(
                (o) => o.status === 'pending' || o.status === 'processing'
            );
            if (hasActive) pull();
        }, 12000);

        return () => {
            stopped = true;
            clearInterval(timer);
            supabase.removeChannel(channel);
        };
    },

    async createOrderAtomic(orderPayload, costCoins, isPromo1Coin = false, promoDay = null) {
        const { data, error } = await supabase.rpc('kaling_create_order', {
            p_order: orderPayload,
            p_cost_coins: Number(costCoins),
            p_is_promo_1_coin: Boolean(isPromo1Coin),
            p_promo_day: promoDay,
        });
        if (error) throw error;
        return data; // { order_id, remaining_coins }
    },

    async fetchMyTopups(kalingUid, maxRows = 200) {
        const { data, error } = await supabase
            .from('kaling_topups')
            .select('*')
            .eq('user_id', kalingUid)
            .order('created_at', { ascending: false })
            .limit(maxRows);
        if (error) throw error;
        return (data || []).map(mapKalingTopupRow);
    },

    subscribeMyTopups(kalingUid, onList) {
        let stopped = false;
        let prevStatuses = new Map();
        let initialized = false;

        const pull = async () => {
            if (stopped) return;
            try {
                const rows = await kalingApi.fetchMyTopups(kalingUid, 200);
                if (stopped) return;
                const changes = [];
                const nextStatuses = new Map();
                for (const r of rows) {
                    nextStatuses.set(r.id, r.status);
                    if (initialized) {
                        const prev = prevStatuses.get(r.id);
                        if (prev && prev !== r.status) {
                            changes.push({ type: 'modified', doc: r });
                        }
                    }
                }
                prevStatuses = nextStatuses;
                initialized = true;
                onList(rows, changes);
            } catch (e) {
                console.warn('[KalingSB] topups pull:', e.message);
            }
        };

        pull();

        // Poll quickly when topup modal is open, gently otherwise
        const timer = setInterval(() => {
            const topupOpen = document.getElementById('topup-modal')?.style?.display === 'flex';
            const topupPageOpen = document.getElementById('topup-history-page')?.style?.display === 'block';
            if (topupOpen || topupPageOpen) pull();
        }, 5000);

        return () => {
            stopped = true;
            clearInterval(timer);
        };
    },

    async createOrReusePendingTopup(user, pkg, prefix = 'KL') {
        const { data: existingRows, error: qErr } = await supabase
            .from('kaling_topups')
            .select('*')
            .eq('user_id', user.uid)
            .eq('status', 'pending')
            .eq('package_name', pkg.name)
            .order('created_at', { ascending: false })
            .limit(1);
        if (qErr) throw qErr;

        const genCode = () => {
            const randomStr = Math.random().toString(36).substring(2, 6).toUpperCase();
            return `${prefix}${pkg.coins}${randomStr}`;
        };

        if (existingRows && existingRows.length > 0) {
            const existing = existingRows[0];
            const staleCoins = Number(existing.coins) !== Number(pkg.coins);
            const staleAmount = Number(existing.amount) !== Number(pkg.amount);
            if (staleCoins || staleAmount) {
                const transferContent = genCode();
                const { error: uErr } = await supabase
                    .from('kaling_topups')
                    .update({
                        package_id: pkg.id,
                        coins: pkg.coins,
                        amount: pkg.amount,
                        transfer_content: transferContent,
                        updated_at: new Date().toISOString(),
                    })
                    .eq('id', existing.id);
                if (uErr) throw uErr;
                return { topupId: existing.id, transferContent, reused: true, updated: true };
            }
            return { topupId: existing.id, transferContent: existing.transfer_content, reused: true, updated: false };
        }

        const topupId = generateId('tp_');
        const transferContent = genCode();
        const nowIso = new Date().toISOString();
        const { error: iErr } = await supabase.from('kaling_topups').insert({
            id: topupId,
            site: 'kaling',
            user_id: user.uid,
            user_email: (user.email || '').trim().toLowerCase(),
            user_name: user.displayName || '',
            package_id: pkg.id,
            package_name: pkg.name,
            coins: pkg.coins,
            amount: pkg.amount,
            currency: 'VND',
            transfer_content: transferContent,
            status: 'pending',
            is_automated: true,
            gateway: 'casso',
            created_at: nowIso,
            updated_at: nowIso,
        });
        if (iErr) throw iErr;
        return { topupId, transferContent, reused: false, updated: false };
    },

    async checkAllowlist(kind, email) {
        const key = String(email || '').trim().toLowerCase();
        if (!key) return false;
        const table = kind === 'referral' ? 'kaling_referral_allowlist' : 'kaling_batch_channel_allowlist';
        const { data, error } = await supabase.from(table).select('email').eq('email', key).maybeSingle();
        if (error) return false;
        return Boolean(data?.email);
    },

    async ensureReferralCode(generateFn) {
        for (let attempt = 0; attempt < 5; attempt++) {
            const candidate = generateFn();
            const { data, error } = await supabase.rpc('kaling_ensure_referral_code', {
                p_candidate: candidate,
            });
            if (!error && data) return String(data);
            const msg = String(error?.message || '');
            if (msg.includes('duplicate key') || msg.includes('unique')) continue;
            throw error;
        }
        throw new Error('Could not allocate unique referral code after 5 attempts');
    },

    subscribeReferralEarnings(kalingUid, onRows, onError) {
        let stopped = false;
        const pull = async () => {
            if (stopped) return;
            try {
                const { data, error } = await supabase
                    .from('kaling_referral_earnings')
                    .select('*')
                    .eq('referrer_id', kalingUid)
                    .order('created_at', { ascending: false })
                    .limit(200);
                if (error) throw error;
                if (!stopped) onRows((data || []).map(mapReferralEarningRow));
            } catch (e) {
                if (!stopped && onError) onError(e);
            }
        };
        pull();
        const timer = setInterval(() => {
            if (document.getElementById('referral-page')?.style?.display === 'block') pull();
        }, 15000);
        return () => {
            stopped = true;
            clearInterval(timer);
        };
    },

    async getBatchChannelConfig(configId) {
        const { data, error } = await supabase
            .from('kaling_batch_channel_config')
            .select('*')
            .eq('id', configId)
            .maybeSingle();
        if (error) throw error;
        return mapBatchConfigRow(data);
    },

    async upsertBatchChannelConfig(configId, payload) {
        const row = batchConfigPayloadToRow(configId, payload);
        const { error } = await supabase
            .from('kaling_batch_channel_config')
            .upsert(row, { onConflict: 'id' });
        if (error) throw error;
    },

    subscribeBatchChannelConfig(configId, onCfg, onError) {
        let stopped = false;
        const pull = async () => {
            if (stopped) return;
            try {
                const cfg = await kalingApi.getBatchChannelConfig(configId);
                if (!stopped) onCfg(cfg);
            } catch (e) {
                if (!stopped && onError) onError(e);
            }
        };
        pull();
        const timer = setInterval(() => {
            const modalOpen = document.getElementById('batch-channel-modal')?.style?.display === 'flex';
            if (modalOpen) pull();
        }, 4000);
        return () => {
            stopped = true;
            clearInterval(timer);
        };
    },

    async setApiKey(newKey) {
        const { data, error } = await supabase.rpc('kaling_set_api_key', {
            p_api_key: newKey,
        });
        if (error) throw error;
        return String(data || newKey);
    },
};
