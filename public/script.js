/**
 * script.js - Core logic for Kaling Cloud
 */

import { APP_CLIENT_VERSION } from "./app-version.js";

export { APP_CLIENT_VERSION };

const TELEGRAM_BOT_TOKEN = '8783657660:AAHRfxHNiohZzPJ2OaQ7TEMNKwb7AAlp2uo';
const TELEGRAM_CHAT_ID = '6067707939';
const TOPUP_COMPLAINT_DELAY_MS = 30 * 1000;

let topupComplaintTimer = null;

function resetTopupComplaintUi() {
    if (topupComplaintTimer) {
        clearTimeout(topupComplaintTimer);
        topupComplaintTimer = null;
    }
    const btn = document.getElementById('btn-topup-complaint');
    const hint = document.getElementById('topup-complaint-hint');
    if (hint) {
        hint.style.display = '';
        hint.textContent = t('payment.complaint_hint');
    }
    if (btn) {
        btn.disabled = true;
        btn.classList.add('topup-complaint-btn--waiting');
        btn.textContent = t('payment.complaint_btn_wait', { secs: 30 });
    }
}

function scheduleTopupComplaintButton() {
    resetTopupComplaintUi();
    topupComplaintTimer = setTimeout(() => {
        topupComplaintTimer = null;
        const ctx = window.__topupComplaintCtx;
        const btn = document.getElementById('btn-topup-complaint');
        const hint = document.getElementById('topup-complaint-hint');
        if (!ctx || ctx.reported) return;
        if (hint) {
            hint.textContent = t('payment.complaint_hint_ready');
        }
        if (btn) {
            btn.disabled = false;
            btn.classList.remove('topup-complaint-btn--waiting');
            btn.textContent = t('payment.complaint_btn');
        }
    }, TOPUP_COMPLAINT_DELAY_MS);
}

function clearTopupComplaintState() {
    if (topupComplaintTimer) {
        clearTimeout(topupComplaintTimer);
        topupComplaintTimer = null;
    }
}

function escapeTelegramHtml(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

window.reportTopupComplaint = async () => {
    const ctx = window.__topupComplaintCtx;
    if (!ctx) {
        showToast(t('payment.complaint_error'));
        return;
    }
    const elapsed = Date.now() - (ctx.openedAt || 0);
    if (elapsed < TOPUP_COMPLAINT_DELAY_MS) {
        const secs = Math.max(1, Math.ceil((TOPUP_COMPLAINT_DELAY_MS - elapsed) / 1000));
        showToast(t('payment.complaint_wait', { secs }));
        return;
    }
    if (ctx.reported) {
        showToast(t('payment.complaint_already_sent'));
        return;
    }

    const btn = document.getElementById('btn-topup-complaint');
    if (btn) btn.disabled = true;

    const openedLocal = new Date(ctx.openedAt).toLocaleString('vi-VN');
    const waitedSec = Math.max(1, Math.round(elapsed / 1000));
    const msg = [
        '🆘 <b>[Kaling] KHIẾU NẠI NẠP COIN</b>',
        '',
        `👤 Tên: ${escapeTelegramHtml(ctx.userName || 'N/A')}`,
        `📧 Email: ${escapeTelegramHtml(ctx.userEmail || 'N/A')}`,
        `🆔 UID: <code>${escapeTelegramHtml(ctx.userId || '')}</code>`,
        `📦 Gói: ${escapeTelegramHtml(ctx.packageName || 'N/A')} (${ctx.coins || 0} coin)`,
        `💵 Số tiền: ${Number(ctx.amount || 0).toLocaleString('vi-VN')}đ`,
        `📝 Nội dung CK: <code>${escapeTelegramHtml(ctx.transferContent || '')}</code>`,
        `🔑 Topup ID: <code>${escapeTelegramHtml(ctx.topupId || 'unknown')}</code>`,
        `🕒 Mở QR: ${escapeTelegramHtml(openedLocal)} (đã chờ ~${waitedSec} giây)`,
        '',
        '👉 Kiểm tra Casso + duyệt thủ công nếu đã nhận tiền.'
    ].join('\n');

    try {
        await sendTelegramMessage(msg);
        ctx.reported = true;
        showToast(t('payment.complaint_sent'));
        if (btn) {
            btn.textContent = t('payment.complaint_already_sent');
            btn.classList.add('topup-complaint-btn--sent');
        }
    } catch (e) {
        console.error('[TopupComplaint]', e);
        if (btn) btn.disabled = false;
        showToast(t('payment.complaint_error'));
    }
};

const KALING_VAE_10 = { cost: 5, maxVideoSec: 10, vaeDurationSec: 10, vaeResolution: '720p' };
const KALING_VAE_15 = { cost: 9, maxVideoSec: 15, vaeDurationSec: 15, vaeResolution: '720p' };
const KALING_VAE_20 = { cost: 10, maxVideoSec: 20, vaeDurationSec: 20, vaeResolution: '720p' };
const DURATION_MODEL_KEYS = ['ad10', 'ad15', 'ad20', 'ad25', 'ad30'];
const BATCH_CHANNEL_MODELS = {
    ad10: {
        cost: 3,
        modelId: '159',
        renderProvider: 'aidancing',
        maxVideoSec: 10,
        serviceLabel: '10 giây',
        vaeDurationSec: 10,
        vaeResolution: '720p',
    },
    ad15: {
        cost: 4.5,
        modelId: '248',
        renderProvider: 'aidancing',
        maxVideoSec: 15,
        serviceLabel: '15 giây',
        vaeDurationSec: 15,
        vaeResolution: '720p',
    },
    ad20: {
        cost: 6,
        modelId: '160',
        renderProvider: 'aidancing',
        maxVideoSec: 20,
        serviceLabel: '20 giây',
        vaeDurationSec: 20,
        vaeResolution: '720p',
    },
    ad25: {
        cost: 7.5,
        modelId: '248',
        renderProvider: 'aidancing',
        maxVideoSec: 25,
        serviceLabel: '25 giây',
        vaeDurationSec: 25,
        vaeResolution: '720p',
    },
    ad30: {
        cost: 9,
        modelId: '248',
        renderProvider: 'aidancing',
        maxVideoSec: 30,
        serviceLabel: '30 giây',
        vaeDurationSec: 30,
        vaeResolution: '720p',
    },
};
const KALING_VAE_30 = { cost: 20, maxVideoSec: 30, vaeDurationSec: 30, vaeResolution: '720p' };
/** Tạm ẩn trên UI — backend vẫn xử lý đơn cũ */
const HIDDEN_MODEL_KEYS = new Set(['vae20', 'vae1080_30', 'vae10', 'vae15', 'rbTrial']);
const MAX_VIDEO_DURATION_SEC = KALING_VAE_30.maxVideoSec;
const ROBONEO_TRIAL = {
    startMs: new Date('2026-06-19T00:00:00+07:00').getTime(),
    windowMs: 24 * 60 * 60 * 1000,
    modelKey: 'rbTrial',
    cost: 3,
    maxVideoSec: 10,
};
const MAX_CHAR_FILE_BYTES = 10 * 1024 * 1024;
const MAX_VIDEO_FILE_BYTES = 50 * 1024 * 1024;

/** Thời lượng video đã chọn — dùng validate tối đa 30s. */
let kalingSelectedDurationSec = null;

/** Làm tròn tối đa 2 chữ số thập phân để hỗ trợ giá .5 coin cho học viên mà không dính lỗi float. */
function normalizeCoins(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return 0;
    return Math.round(n * 100) / 100;
}

function formatCoinAmount(value) {
    return String(normalizeCoins(value));
}

function hasApprovedTopupHistory() {
    return (FB_CACHE.myTopups || []).some((t) => t.status === 'approved');
}

async function ensureMyTopupsLoaded() {
    if (fbHas('myTopups') && Array.isArray(FB_CACHE.myTopups)) {
        return FB_CACHE.myTopups;
    }
    if (!currentUser || !window.kalingApi) return [];
    FB_CACHE.myTopups = await window.kalingApi.fetchMyTopups(currentUser.uid);
    return FB_CACHE.myTopups;
}

function promptInsufficientCoinsAndTopup() {
    window.niceConfirm({
        title: t('modals.insufficient_coins_title'),
        message: t('modals.insufficient_coins_msg'),
        icon: '💰',
        onConfirm: () => {
            closeModal('order-modal');
            if (window.openPricingModal) window.openPricingModal();
        }
    });
}

async function getVideoDurationFromUrl(url) {
    if (!url) return null;
    try {
        const video = document.createElement('video');
        video.preload = 'metadata';
        video.crossOrigin = 'anonymous';
        const duration = await new Promise((resolve, reject) => {
            const cleanup = () => {
                video.removeAttribute('src');
                video.load();
            };
            video.onloadedmetadata = () => {
                const d = Number(video.duration);
                cleanup();
                resolve(Number.isFinite(d) ? d : null);
            };
            video.onerror = () => {
                cleanup();
                reject(new Error('metadata error'));
            };
            video.src = url;
        });
        return duration;
    } catch {
        return null;
    }
}

function isClientOlderThan(current, required) {
    const a = String(current).split('.').map((x) => parseInt(x, 10) || 0);
    const b = String(required).split('.').map((x) => parseInt(x, 10) || 0);
    const n = Math.max(a.length, b.length);
    for (let i = 0; i < n; i++) {
        const x = a[i] || 0;
        const y = b[i] || 0;
        if (x < y) return true;
        if (x > y) return false;
    }
    return false;
}

async function ensureClientVersionGate() {
    const minVer = APP_CLIENT_VERSION;
    window.__minClientVersion = minVer;
    if (!isClientOlderThan(APP_CLIENT_VERSION, minVer)) return;

    const bannerId = 'client-outdated-banner';
    if (document.getElementById(bannerId)) return;
    const banner = document.createElement('div');
    banner.id = bannerId;
    banner.className = 'client-outdated-banner';
    banner.innerHTML = `
        <p>${t('modals.client_outdated_banner')}</p>
        <button type="button" class="btn-primary client-outdated-refresh">${t('modals.client_outdated_refresh')}</button>
    `;
    banner.querySelector('button')?.addEventListener('click', () => {
        window.location.reload();
    });
    document.body.prepend(banner);
}

// --- EmailJS Config ---
const EMAILJS_SERVICE_ID = 'service_6r6rd2q';
const EMAILJS_TEMPLATE_ID = 'template_09eir3r';
const EMAILJS_PUBLIC_KEY = '92pP97oTzMGR4p_Zp';

// --- Utility Helpers ---
function safeToDate(field) {
    if (!field) return null;
    if (typeof field.toDate === 'function') return field.toDate();
    if (typeof field === 'string') return new Date(field);
    if (field.seconds) return new Date(field.seconds * 1000);
    if (field.toMillis) return new Date(field.toMillis());
    return new Date(field);
}

const PROMO_1_COIN_MAX_TOTAL = 3;
const PROMO_1_COIN_TIMEZONE = 'Asia/Ho_Chi_Minh';

function getLocalDayKey(date = new Date(), timeZone = PROMO_1_COIN_TIMEZONE) {
    const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
    }).formatToParts(date);
    const y = parts.find(p => p.type === 'year')?.value;
    const m = parts.find(p => p.type === 'month')?.value;
    const d = parts.find(p => p.type === 'day')?.value;
    return `${y}-${m}-${d}`;
}

function isPromo1CoinOrder(order) {
    return order?.promo1Coin === true || Number(order?.costCoins) === 1;
}

function computePromo1CoinStats(orders = [], userData = null) {
    const promoOrders = (orders || []).filter(isPromo1CoinOrder);
    const todayKey = getLocalDayKey();
    const totalFromOrders = promoOrders.length;
    const usedTodayFromOrders = promoOrders.some((o) => {
        const created = safeToDate(o.createdAt);
        return created && getLocalDayKey(created) === todayKey;
    });
    const totalFromUser = Number(userData?.promo1CoinCount) || 0;
    const lastDayUser = userData?.promo1CoinLastDay || '';
    const totalUsed = Math.max(totalFromOrders, totalFromUser);
    const usedToday = usedTodayFromOrders || lastDayUser === todayKey;
    const remainingTotal = Math.max(0, PROMO_1_COIN_MAX_TOTAL - totalUsed);
    const eligible = remainingTotal > 0 && !usedToday;
    return { eligible, totalUsed, usedToday, remainingTotal, todayKey };
}

function getPromo1CoinEligibilityFromUser(userData) {
    const todayKey = getLocalDayKey();
    const totalUsed = Number(userData?.promo1CoinCount) || 0;
    const usedToday = (userData?.promo1CoinLastDay || '') === todayKey;
    const remainingTotal = Math.max(0, PROMO_1_COIN_MAX_TOTAL - totalUsed);
    return {
        eligible: remainingTotal > 0 && !usedToday,
        totalUsed,
        usedToday,
        remainingTotal,
        todayKey
    };
}

async function ensureUserPromoFieldsSynced() {
    // Promo quota is tracked atomically server-side in Supabase RPC kaling_create_order
}

function syncPromo1CoinState(orders, userData = window.__currentUserData) {
    promo1CoinStats = { eligible: false, totalUsed: 0, usedToday: false, remainingTotal: 0, todayKey: getLocalDayKey() };
    isFirstTimeUser = false;
    return promo1CoinStats;
}

// --- Data Constants ---
const MODEL_COST_LEGACY_FAST = 3;
const MODEL_COST_LEGACY_TURBO = 10;

function getUserCreatedAtMs(userData) {
    const ca = userData?.createdAt;
    if (!ca) return null;
    if (typeof ca.toDate === 'function') return ca.toDate().getTime();
    if (typeof ca.seconds === 'number') return ca.seconds * 1000;
    if (typeof ca._seconds === 'number') return ca._seconds * 1000;
    if (typeof ca === 'string') {
        const ms = Date.parse(ca);
        return Number.isFinite(ms) ? ms : null;
    }
    return null;
}

function isRoboneoTrialEligible(userData) {
    const createdMs = getUserCreatedAtMs(userData);
    if (createdMs == null || createdMs < ROBONEO_TRIAL.startMs) return false;
    return Date.now() < createdMs + ROBONEO_TRIAL.windowMs;
}

function getRoboneoTrialRemainingMs(userData) {
    const createdMs = getUserCreatedAtMs(userData);
    if (createdMs == null) return 0;
    return Math.max(0, createdMs + ROBONEO_TRIAL.windowMs - Date.now());
}

function formatRoboneoTrialRemaining(userData) {
    const ms = getRoboneoTrialRemainingMs(userData);
    if (ms <= 0) return '';
    const h = Math.floor(ms / 3600000);
    const m = Math.floor((ms % 3600000) / 60000);
    return t('modals.roboneo_trial_remaining', { h, m });
}

function isHocVienPricingUser(userData) {
    const uData = userData || window.__currentUserData || (typeof FB_CACHE !== 'undefined' && FB_CACHE.userProfile) || null;
    return Boolean(
        canUseBatchChannel() ||
        (uData && (
            uData.role === 'hocvien' ||
            uData.role === 'student' ||
            uData.isHocVien === true ||
            uData.isStudent === true
        ))
    );
}

function getSelectedModelKey() {
    const checked = document.querySelector('input[name="model-type"]:checked');
    const key = checked ? checked.value : 'ad20';
    if (!DURATION_MODEL_KEYS.includes(key) || HIDDEN_MODEL_KEYS.has(key)) {
        return 'ad20';
    }
    return key;
}

function usesBatchChannelModelPricing() {
    return isHocVienPricingUser();
}

function getModelPreset(modelKey) {
    const key = modelKey || getSelectedModelKey();
    const base = MODELS[key] || MODELS.ad20;
    const batch = BATCH_CHANNEL_MODELS[key];
    if (usesBatchChannelModelPricing() && batch) {
        return {
            ...base,
            cost: batch.cost,
            modelId: batch.modelId,
            renderProvider: batch.renderProvider,
            maxVideoSec: batch.maxVideoSec,
            vaeDurationSec: batch.vaeDurationSec,
            vaeResolution: batch.vaeResolution,
            serviceLabel: batch.serviceLabel,
            batchChannelPricing: true,
        };
    }
    return base;
}

function getMaxVideoSecForModel(modelKey) {
    return getModelPreset(modelKey).maxVideoSec;
}

function getMaxVideoSecForSelectedModel() {
    return getMaxVideoSecForModel(getSelectedModelKey());
}

function modelCoinCost(modelKey) {
    return getModelPreset(modelKey).cost;
}

function syncModelPriceLabels() {
    Object.keys(MODELS).forEach((key) => {
        const el = document.getElementById(`model-${key}-cost`);
        if (el) el.textContent = formatCoinAmount(getModelPreset(key).cost);
    });
    const studentBadge = document.getElementById('student-pricing-badge');
    if (studentBadge) {
        studentBadge.style.display = isHocVienPricingUser() ? 'inline-flex' : 'none';
    }
}

function syncOrderModelCardCopy() {
    const cards = [
        { key: 'ad10', titleKey: 'modals.model_ad10', descKey: 'modals.model_ad10_desc' },
        { key: 'ad15', titleKey: 'modals.model_ad15', descKey: 'modals.model_ad15_desc' },
        { key: 'ad20', titleKey: 'modals.model_ad20', descKey: 'modals.model_ad20_desc' },
        { key: 'ad25', titleKey: 'modals.model_ad25', descKey: 'modals.model_ad25_desc' },
        { key: 'ad30', titleKey: 'modals.model_ad30', descKey: 'modals.model_ad30_desc' },
    ];
    cards.forEach(({ key, titleKey, descKey }) => {
        const label = document.querySelector(`input[name="model-type"][value="${key}"]`)?.closest('label');
        if (!label) return;
        const titleEl = label.querySelector('.model-card-title');
        const descEl = label.querySelector('.model-card-desc');
        if (titleEl) titleEl.textContent = t(titleKey);
        if (descEl) descEl.textContent = t(descKey);
    });
}

function updateOrderModelSelectionUI() {
    const trialWrap = document.getElementById('model-rbtrial-wrap');
    if (trialWrap) trialWrap.style.display = 'none';

    HIDDEN_MODEL_KEYS.forEach((modelKey) => {
        const label = document.querySelector(`input[name="model-type"][value="${modelKey}"]`)?.closest('label');
        if (label) label.style.display = 'none';
        const batchLabel = document.querySelector(`input[name="batch-model-type"][value="${modelKey}"]`)?.closest('label');
        if (batchLabel) batchLabel.style.display = 'none';
    });

    const checked = document.querySelector('input[name="model-type"]:checked');
    if (!checked || !DURATION_MODEL_KEYS.includes(checked.value) || HIDDEN_MODEL_KEYS.has(checked.value)) {
        const fallback = document.querySelector('input[name="model-type"][value="ad20"]');
        if (fallback) fallback.checked = true;
    }

    syncOrderModelCardCopy();
    syncModelPriceLabels();
}

function normalizeOrderCost(model) {
    model.promo1Coin = false;
    return model;
}

// IMPORTANT: usdPrice here is for display only. Server-side `PACKAGES` in
// functions/api/paypal.js is the source of truth for the actual charge.
// Keep them in sync (id + coins + USD value).
const COIN_PACKAGES = [
    { id: 'starter_v2', name: 'Starter',    coins: 10,  price: '10.000đ',  usdPrice: '$0.49', amount: 10000,  hasBonus: false, oneTime: true },
    { id: 'creator',    name: 'Creator',    coins: 100, price: '100.000đ', usdPrice: '$5.99', amount: 100000, featured: false, hasBonus: false },
    { id: 'studio',     name: 'Studio',     coins: 525,  price: '500.000đ',  usdPrice: '$24.99', amount: 500000,  featured: true, hasBonus: true },
    { id: 'pro-studio', name: 'Enterprise', coins: 1100, price: '1.000.000đ', usdPrice: '$49.99', amount: 1000000, hasBonus: true },
    { id: 'hocvien_package', name: 'Gói Học Viên', coins: 0, price: '699.000đ', usdPrice: '$29.99', amount: 699000, featured: true, hasBonus: false }
];

function topupMatchesPackage(topup, pkg) {
    if (!topup || !pkg) return false;
    if (topup.packageId && topup.packageId === pkg.id) return true;
    return topup.packageName === pkg.name
        && Number(topup.coins) === Number(pkg.coins)
        && Number(topup.amount) === Number(pkg.amount);
}

function hasCompletedOneTimeTopup(pkg) {
    if (!pkg?.oneTime) return false;
    return (FB_CACHE.myTopups || []).some(
        (t) => t.status === 'approved' && topupMatchesPackage(t, pkg)
    );
}

function getVisibleCoinPackages() {
    let list = COIN_PACKAGES.filter(p => p.id !== 'hocvien_package');
    if (currentUser) {
        list = list.filter((pkg) => !hasCompletedOneTimeTopup(pkg));
    }
    const uData = (window.__currentUserData || (typeof FB_CACHE !== 'undefined' && FB_CACHE.userProfile)) || null;
    const isHocVien = (window.__batchChannelAllowed === true) || (uData && (
        uData.role === 'hocvien' ||
        uData.role === 'student' ||
        uData.isHocVien === true ||
        uData.isStudent === true
    ));
    if (!isHocVien) {
        const hocvien = COIN_PACKAGES.find(p => p.id === 'hocvien_package');
        if (hocvien) {
            list.splice(1, 0, hocvien);
        }
    }
    return list;
}

const AI_MODELS = [
    {
        id: 'copy-motion-photo',
        titleKey: 'models.model1_title',
        descKey: 'models.model1_desc',
        cost: MODEL_COST_LEGACY_FAST,
        serviceType: 'motion-to-char',
        demoChar: 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&q=80&w=300',
        demoRef: 'https://pub-2b53cd37b4a44642afdbb8bb470bde66.r2.dev/banner.mp4',
        demoResult: 'https://pub-2b53cd37b4a44642afdbb8bb470bde66.r2.dev/banner.mp4'
    }
];
window.AI_MODELS = AI_MODELS;


const TEMPLATE_API_URL = '/api/templates';
let TREND_VIDEOS = [];
let _templatesFetched = false;

async function fetchTemplates() {
    if (_templatesFetched) return TREND_VIDEOS;
    try {
        const R2_FALLBACK = 'https://pub-4496e76c4ba34c28980998855e485fbd.r2.dev/api/template.json';
        console.log('[Templates] Fetching from', TEMPLATE_API_URL);
        let res = await fetch(TEMPLATE_API_URL).catch(() => null);
        if (!res || !res.ok) {
            console.log('[Templates] Proxy failed, trying R2 direct');
            res = await fetch(R2_FALLBACK);
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const raw = await res.json();
        console.log('[Templates] Got', raw.length, 'items');
        TREND_VIDEOS = raw.map(item => {
            const videoMedia = item.medias.find(m => m.contentType === 'video/mp4');
            const imageMedia = item.medias.find(m => m.contentType === 'image/webp');
            const name = (videoMedia?.name || item.id).replace(/\.\w+$/, '').replace(/[_-]/g, ' ');
            return {
                id: item.id,
                url: videoMedia?.url || '',
                thumb: imageMedia?.thumbUrl || imageMedia?.url || '',
                poster: imageMedia?.url || '',
                title: name,
                categoryId: item.categoryId || '',
                isPremium: !!item.isPremium
            };
        });
        _templatesFetched = true;
        console.log('[Templates] Mapped', TREND_VIDEOS.length, 'videos');
    } catch (e) {
        console.error('[Templates] Failed to fetch:', e);
    }
    return TREND_VIDEOS;
}

function trendTitle(video) {
    return video.titleKey ? t(video.titleKey) : (video.title || video.id);
}

function packageDisplayName(pkg) {
    if (!pkg) return '';
    const key = `pricing.packages.${pkg.id}`;
    const val = t(key);
    return val === key ? (pkg.name || pkg.id) : val;
}

function serviceDisplayName(pkg) {
    if (!pkg) return '';
    const key = `pricing.service_packages.${pkg.id}`;
    const val = t(key);
    return val === key ? (pkg.name || pkg.id) : val;
}

function supportedLangs() {
    return window.LANG_CONFIG?.supported || ['vi', 'en', 'es', 'pt', 'th', 'id'];
}

function gatewayLabel(gateway) {
    if (gateway === 'casso') return t('referral.gateway_casso');
    if (gateway === 'paypal') return t('referral.gateway_paypal');
    if (gateway === 'lemonsqueezy') return t('referral.gateway_lemon');
    if (gateway === 'admin') return t('referral.gateway_admin');
    return gateway || '—';
}

const MODELS = {
    rbTrial: {
        nameKey: "modals.model_rbTrial",
        cost: ROBONEO_TRIAL.cost,
        timeKey: "modals.model_rbTrial_desc",
        modelId: "159",
        renderProvider: "aidancing",
        maxVideoSec: ROBONEO_TRIAL.maxVideoSec,
        vaeResolution: "720p",
        roboneoTrial: true,
    },
    vae10: {
        nameKey: "modals.model_vae10",
        cost: KALING_VAE_10.cost,
        timeKey: "modals.model_vae10_desc",
        modelId: "124",
        renderProvider: "roboneo",
        maxVideoSec: KALING_VAE_10.maxVideoSec,
        vaeDurationSec: KALING_VAE_10.vaeDurationSec,
        vaeResolution: KALING_VAE_10.vaeResolution,
    },
    ad10: {
        nameKey: "modals.model_ad10",
        cost: 6,
        timeKey: "modals.model_ad10_desc",
        modelId: "159",
        renderProvider: "aidancing",
        maxVideoSec: 10,
        vaeDurationSec: 10,
        vaeResolution: "720p",
    },
    ad15: {
        nameKey: "modals.model_ad15",
        cost: 9,
        timeKey: "modals.model_ad15_desc",
        modelId: "248",
        renderProvider: "aidancing",
        maxVideoSec: 15,
        vaeDurationSec: 15,
        vaeResolution: "720p",
    },
    ad20: {
        nameKey: "modals.model_ad20",
        cost: 12,
        timeKey: "modals.model_ad20_desc",
        modelId: "160",
        renderProvider: "aidancing",
        maxVideoSec: 20,
        vaeDurationSec: 20,
        vaeResolution: "720p",
    },
    ad25: {
        nameKey: "modals.model_ad25",
        cost: 15,
        timeKey: "modals.model_ad25_desc",
        modelId: "248",
        renderProvider: "aidancing",
        maxVideoSec: 25,
        vaeDurationSec: 25,
        vaeResolution: "720p",
    },
    ad30: {
        nameKey: "modals.model_ad30",
        cost: 18,
        timeKey: "modals.model_ad30_desc",
        modelId: "248",
        renderProvider: "aidancing",
        maxVideoSec: 30,
        vaeDurationSec: 30,
        vaeResolution: "720p",
    },
    vae15: {
        nameKey: "modals.model_vae15",
        cost: KALING_VAE_15.cost,
        timeKey: "modals.model_vae15_desc",
        modelId: "131",
        renderProvider: "roboneo",
        maxVideoSec: KALING_VAE_15.maxVideoSec,
        vaeDurationSec: KALING_VAE_15.vaeDurationSec,
        vaeResolution: KALING_VAE_15.vaeResolution,
    },
    vae20: {
        nameKey: "modals.model_vae20",
        cost: KALING_VAE_20.cost,
        timeKey: "modals.model_vae20_desc",
        modelId: "125",
        renderProvider: "videoaieasy",
        maxVideoSec: KALING_VAE_20.maxVideoSec,
        vaeDurationSec: KALING_VAE_20.vaeDurationSec,
        vaeResolution: KALING_VAE_20.vaeResolution,
    },
    vae1080_30: {
        nameKey: "modals.model_vae1080_30",
        cost: KALING_VAE_30.cost,
        timeKey: "modals.model_vae1080_30_desc",
        modelId: "129",
        renderProvider: "videoaieasy",
        maxVideoSec: KALING_VAE_30.maxVideoSec,
        vaeDurationSec: KALING_VAE_30.vaeDurationSec,
        vaeResolution: KALING_VAE_30.vaeResolution,
    },
};

function localizedModel(key) {
    const modelKey = key || getSelectedModelKey();
    const m = getModelPreset(modelKey);
    return {
        ...m,
        name: t(m.nameKey),
        time: t(m.timeKey),
        cost: m.cost,
        renderProvider: m.renderProvider,
    };
}

const SERVICE_PACKAGES = [
    { id: 'plus', name: 'Plus', cost: MODEL_COST_LEGACY_FAST, featureKeys: ['services.plus_f1', 'services.plus_f2', 'services.plus_f3'], featured: true },
    { id: 'viral', name: 'Viral', cost: MODEL_COST_LEGACY_TURBO, featureKeys: ['services.viral_f1', 'services.viral_f2', 'services.viral_f3'] }
];

async function getVideoDurationSeconds(file) {
    if (!file) return null;
    try {
        const url = URL.createObjectURL(file);
        const video = document.createElement('video');
        video.preload = 'metadata';
        const duration = await new Promise((resolve, reject) => {
            const cleanup = () => {
                try { URL.revokeObjectURL(url); } catch { }
                video.removeAttribute('src');
                video.load();
            };
            video.onloadedmetadata = () => {
                const d = Number(video.duration);
                cleanup();
                resolve(Number.isFinite(d) ? d : null);
            };
            video.onerror = () => {
                cleanup();
                reject(new Error('metadata error'));
            };
            video.src = url;
        });
        return duration;
    } catch {
        return null;
    }
}

let currentUser = null;
let selectedTopupPackage = null;
let selectedPaymentMethod = 'vietqr';
let isFirstTimeUser = false; // true when 1-coin promo is still available
let promo1CoinStats = { eligible: false, totalUsed: 0, usedToday: false, remainingTotal: 0, todayKey: '' };
let orderCount = 0; // Track total orders
let initialCoinsBeforeTopup = 0; // Để theo dõi số dư trước khi nạp
let referralEarningsUnsubscribe = null; // Cleanup handle for referralEarnings onSnapshot (legacy - giờ dùng FB_LISTENERS)
let referralCurrentCode = null; // User's referral code, populated when opening referral page
window.__referralAllowed = false;
window.__batchChannelAllowed = false;
const SUPER_ADMIN_EMAILS = ["traderfinn0312@gmail.com", "dinhhoangvan.hh@gmail.com"]; // Bootstrap super-admin (khớp Firestore rules)

function normalizeReferralAllowlistEmail(email) {
    return (email || '').trim().toLowerCase();
}

function canUseBatchChannel() {
    return !!(window.__batchChannelAllowed || window.__isAdmin);
}

function updateReferralNavVisibility(allowed) {
    const item = document.getElementById('nav-referral-item');
    if (item) item.style.display = allowed ? 'flex' : 'none';
}

function updateBatchChannelNavVisibility(allowed) {
    const show = allowed || window.__isAdmin;
    const navItem = document.getElementById('nav-batch-channel-item');
    if (navItem) navItem.style.display = show ? 'flex' : 'none';
    const homeBtn = document.getElementById('home-auto-video-btn');
    if (homeBtn) homeBtn.style.display = show ? 'inline-flex' : 'none';
    
    // Toggle promo button visibility based on allowlist status
    updateCoursePromoBtnVisibility();
}

async function refreshReferralAllowance(user) {
    const email = user?.email || currentUser?.email || '';
    const key = normalizeReferralAllowlistEmail(email);
    if (!key || !window.kalingApi) {
        window.__referralAllowed = false;
        updateReferralNavVisibility(false);
        return false;
    }
    try {
        window.__referralAllowed = await window.kalingApi.checkAllowlist('referral', key);
    } catch (e) {
        console.warn('[Referral] allowlist check failed:', e.message);
        window.__referralAllowed = false;
    }
    updateReferralNavVisibility(window.__referralAllowed);
    return window.__referralAllowed;
}

async function refreshBatchChannelAllowance(user) {
    const email = user?.email || currentUser?.email || '';
    const key = normalizeReferralAllowlistEmail(email);
    if (!key || !window.kalingApi) {
        window.__batchChannelAllowed = false;
        updateBatchChannelNavVisibility(false);
        updateOrderModelSelectionUI();
        updateFirstOrderUI();
        return false;
    }
    try {
        window.__batchChannelAllowed = await window.kalingApi.checkAllowlist('batch_channel', key);
    } catch (e) {
        console.warn('[BatchChannel] allowlist check failed:', e.message);
        window.__batchChannelAllowed = false;
    }
    updateBatchChannelNavVisibility(window.__batchChannelAllowed);
    updateOrderModelSelectionUI();
    updateFirstOrderUI();
    renderPricing();
    return window.__batchChannelAllowed;
}

// =====================================================================
// FIREBASE LISTENER REGISTRY (chống leak listener gây tốn reads)
// =====================================================================
// Trước đây code gọi onSnapshot(...) khắp nơi mà KHÔNG bao giờ unsubscribe.
// Hậu quả: mỗi lần re-subscribe (đổi ngôn ngữ, đổi tab, gõ search, đổi trang)
// lại chồng thêm listener mới -> tốn reads gấp N lần.
//
// Cơ chế: mọi listener đều gắn vào registry này theo "key". Trước khi tạo
// listener mới ở cùng key, registry tự động unsub cái cũ. Logout -> unsub all.
//
// Keys đang dùng:
//   - userProfile     : doc(users/{uid}) - profile + coins của user hiện tại
//   - myOrders        : query orders của user hiện tại
//   - myTopups        : query topups của user hiện tại
//   - adminOrders     : admin tab Orders (theo currentOrderStatus)
//   - adminTopups     : admin tab Topups (theo currentTopupStatus)
//   - adminUsers      : admin tab Users
//   - referralEarnings: hoa hồng giới thiệu của user hiện tại
const FB_LISTENERS = Object.create(null);

// Cache snapshot data để re-render mà không phải re-subscribe
// (tiết kiệm reads khi user gõ search, đổi trang pagination, đổi ngôn ngữ).
const FB_CACHE = Object.create(null);

function fbUnsub(key) {
    const fn = FB_LISTENERS[key];
    if (typeof fn === 'function') {
        try { fn(); } catch (e) { console.warn('[FB] Unsub error', key, e); }
    }
    FB_LISTENERS[key] = null;
}

function fbSub(key, unsubscribeFn) {
    fbUnsub(key); // luôn cleanup cái cũ trước khi gắn cái mới
    FB_LISTENERS[key] = unsubscribeFn;
}

function fbUnsubAll() {
    Object.keys(FB_LISTENERS).forEach(fbUnsub);
}

function fbHas(key) {
    return typeof FB_LISTENERS[key] === 'function';
}
// --- i18n Logic ---
// Priority: manual choice in localStorage > geo (VN=vi, else=en) > browser language.
const LANG_STORAGE_KEY = 'app_lang';

function detectLangFromBrowser() {
    const langs = navigator.languages?.length ? navigator.languages : [navigator.language || ''];
    for (const l of langs) {
        if (String(l).toLowerCase().startsWith('vi')) return 'vi';
    }
    return 'en';
}

async function resolveInitialLanguage() {
    const saved = localStorage.getItem(LANG_STORAGE_KEY);
    if (supportedLangs().includes(saved)) return saved;

    try {
        const res = await fetch('/api/geo', { cache: 'no-store' });
        if (res.ok) {
            const data = await res.json();
            const lang = data.lang || window.LANG_CONFIG?.langFromCountry?.(data.country) || 'en';
            if (supportedLangs().includes(lang)) return lang;
        }
    } catch (e) {
        console.warn('[i18n] Geo detection failed, using browser fallback:', e.message);
    }

    return detectLangFromBrowser();
}

// vi/en only. Default: en (non-VN).
let currentLang = 'en';
window.currentLang = currentLang;

function logFirebaseEvent(name, params = {}) {
    if (typeof window.gtag === 'function') {
        try { window.gtag('event', name, params); } catch (_) {}
    }
}

function metaPixelId() {
    return (window.ANALYTICS_CONFIG && window.ANALYTICS_CONFIG.metaPixelId) || '';
}

function isMetaPixelReady() {
    return typeof fbq === 'function' && !!metaPixelId();
}

function metaEventId(prefix) {
    const safe = String(prefix || 'evt').replace(/\s+/g, '_');
    return `${safe}_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
}

function tiktokPixelId() {
    return (window.ANALYTICS_CONFIG && window.ANALYTICS_CONFIG.tiktokPixelId) || '';
}

function isTiktokPixelReady() {
    return typeof ttq === 'object' && typeof ttq.track === 'function' && !!tiktokPixelId();
}

function trackMetaEvent(eventName, params = {}) {
    // 1. Track Meta Pixel
    if (isMetaPixelReady()) {
        const payload = { ...params };
        if (!payload.eventID) payload.eventID = metaEventId(eventName);
        fbq('track', eventName, payload);
        console.log(`📘 Meta Pixel: ${eventName}`, payload);
    }

    // 2. Track TikTok Pixel
    if (isTiktokPixelReady()) {
        const payload = { ...params };
        ttq.track(eventName, payload);
        console.log(`🎵 TikTok Pixel: ${eventName}`, payload);
    }
}

function updateMetaAdvancedMatching(user) {
    if (!user?.email) return;
    const em = String(user.email).trim().toLowerCase();
    if (!em) return;

    if (isMetaPixelReady()) {
        fbq('init', metaPixelId(), { em });
    }
    if (isTiktokPixelReady()) {
        ttq.identify({ email: em });
    }
}

export function t(path, params = {}) {
    const langs = [currentLang || 'vi', 'en', 'vi'];
    for (const lang of langs) {
        if (!window.TRANSLATIONS?.[lang]) continue;
        const keys = path.split('.');
        let value = window.TRANSLATIONS[lang];
        for (const key of keys) {
            if (value && Object.prototype.hasOwnProperty.call(value, key)) {
                value = value[key];
            } else {
                value = null;
                break;
            }
        }
        if (value) {
            let translated = String(value);
            Object.keys(params).forEach(key => {
                translated = translated.replace(`{${key}}`, params[key]);
            });
            return translated;
        }
    }
    return path;
}
window.t = t;

const STATUS_MAP = () => ({
    'pending': t('status.pending'),
    'approved': t('status.approved'),
    'rejected': t('status.rejected'),
    'processing': t('status.processing'),
    'completed': t('status.completed'),
    'failed': t('status.failed'),
    'new': t('status.new'),
    'done': t('status.done')
});

const SERVICE_TYPE_MAP = () => ({
    'char-to-video': t('services.char_to_video'),
    'motion-to-char': t('services.motion_to_char')
});

window.STATUS_MAP = STATUS_MAP;
window.SERVICE_TYPE_MAP = SERVICE_TYPE_MAP;

export function applyTranslations() {
    document.documentElement.lang = currentLang || 'vi';
    document.title = t('meta.title');
    const metaDesc = document.querySelector('meta[name="description"]');
    if (metaDesc) metaDesc.content = t('meta.description');

    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        const translation = t(key);
        if (el.tagName === 'INPUT' && (el.type === 'button' || el.type === 'submit')) {
            el.value = translation;
        } else if ((el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') && (el.hasAttribute('placeholder') || el.getAttribute('data-i18n')?.includes('placeholder'))) {
            el.placeholder = translation;
        } else {
            el.innerHTML = translation;
        }
    });

    document.querySelectorAll('[data-i18n-title]').forEach(el => {
        const key = el.getAttribute('data-i18n-title');
        el.title = t(key);
        if (el.hasAttribute('aria-label')) el.setAttribute('aria-label', t(key));
    });

    // Flag UI removed

    // Render 4 Model AI grid
    if (window.renderAIModels) {
        window.renderAIModels();
    }
    renderShowcase();
    renderServicePackages();
}

window.toggleLangMenu = (e) => {
    // language UI removed
};

window.toggleUserMenu = (e) => {
    if (e) e.stopPropagation();
    document.getElementById('lang-menu')?.classList.remove('show');
    document.getElementById('dropdown-menu').classList.toggle('show');
};

window.switchLanguage = (lang) => {
    // language UI removed, but keep API for deep-links/testing
    currentLang = (lang === 'vi') ? 'vi' : 'en';
    window.currentLang = currentLang;
    applyTranslations();

    // Close menus after switch
    document.getElementById('dropdown-menu')?.classList.remove('show');

    if (currentUser) {
        const greetingEl = document.getElementById('user-greeting');
        if (greetingEl) greetingEl.innerText = t('dashboard.greeting', { name: currentUser.displayName });
        renderMyOrders();
        renderMyTopups();
    }
    renderPricing();
    renderShowcase();
    renderServicePackages();
};

// --- Referral / Affiliate Capture ---
const REFERRAL_STORAGE_KEY = 'pending_ref_code';
const REFERRAL_TTL_MS = 30 * 24 * 60 * 60 * 1000; // 30 days
const REFERRAL_CODE_REGEX = /^[A-Z0-9]{6,12}$/;

function captureReferralFromURL() {
    try {
        const params = new URLSearchParams(window.location.search);
        const code = (params.get('ref') || '').trim().toUpperCase();
        if (!code) return;
        if (!REFERRAL_CODE_REGEX.test(code)) {
            console.warn('[Referral] Invalid ref code in URL:', code);
            return;
        }
        const payload = JSON.stringify({ code, savedAt: Date.now() });
        localStorage.setItem(REFERRAL_STORAGE_KEY, payload);
        console.log('[Referral] Captured ref code from URL:', code);
    } catch (e) {
        console.warn('[Referral] Capture failed (non-blocking):', e.message);
    }
}

function getPendingReferralCode() {
    try {
        const raw = localStorage.getItem(REFERRAL_STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || !parsed.code) return null;
        if (Date.now() - (parsed.savedAt || 0) > REFERRAL_TTL_MS) {
            localStorage.removeItem(REFERRAL_STORAGE_KEY);
            return null;
        }
        return REFERRAL_CODE_REGEX.test(parsed.code) ? parsed.code : null;
    } catch (e) {
        return null;
    }
}

function clearPendingReferralCode() {
    try { localStorage.removeItem(REFERRAL_STORAGE_KEY); } catch (e) { }
}

// --- App Initialization ---
export async function initAppLogic() {
    if (!metaPixelId()) {
        console.warn('[Meta Pixel] Chưa cấu hình metaPixelId trong public/analytics-config.js — Facebook Ads sẽ không nhận event.');
    }
    try {
        currentLang = await resolveInitialLanguage();
    } catch (e) {
        currentLang = 'en';
    }
    if (!['vi', 'en'].includes(currentLang)) currentLang = 'en';
    window.currentLang = currentLang;

    // Global Error Handler for debugging
    window.onerror = function (msg, url, lineNo, columnNo, error) {
        const message = [
            'Message: ' + msg,
            'Line: ' + lineNo,
            'Column: ' + columnNo,
            'Error object: ' + JSON.stringify(error)
        ].join(' - ');
        console.error("Global Error:", message);
        showToast(t('common.error_system', { msg }));
        return false;
    };

    // Capture ?ref=XXX before auth state initialises so it survives signup
    captureReferralFromURL();

    // (Intro modal removed; login-required uses auth-modal)

    window.kalingApi.onAuthChange(async (authUser) => {
        try {
            if (requiresExternalBrowser()) {
                if (authUser) {
                    try {
                        await window.kalingApi.signOut();
                    } catch (e) {
                        console.warn('[Auth] signOut in external-browser gate:', e);
                    }
                }
                currentUser = null;
                handleUserLoggedOut(false);
                return;
            }

            if (authUser) {
                try {
                    await handleUserLoggedIn(authUser);
                } catch (e) {
                    console.error("Auth profile error:", e);
                    showToast(t('common.error_auth', { msg: e.message || e.code || 'Supabase' }));
                }
                return;
            }

            currentUser = null;
            handleUserLoggedOut(false);
        } catch (e) {
            console.error("Auth Change Error:", e);
            showToast(t('common.error_auth', { msg: e.message || e.code || 'Auth' }));
        }
    });

    // Render public content
    renderShowcase();
    renderPricing();
    renderServicePackages();
    initPremiumEffects();
    setupEventListeners();
    syncVideos();
    syncModelPriceLabels();
    // Initial UI update for first order offer
    updateFirstOrderUI();
    // Check maintenance status
    checkMaintenance();
    // Detect In-App Browsers
    detectInAppBrowser();

    // Call again after dynamic parts are rendered
    applyTranslations();
    await ensureClientVersionGate();
}

// --- In-app browser (TikTok / Facebook / …) ---
function isInAppBrowser() {
    const ua = navigator.userAgent || navigator.vendor || window.opera || '';
    return /TikTok|FBAV|FBAN|Instagram|Messenger|Line\/|WhatsApp|Telegram|MicroMessenger|Twitter|LinkedInApp/i.test(ua);
}

function isStandaloneBrowser() {
    const ua = navigator.userAgent || '';
    const isChrome = (/Chrome/i.test(ua) || /CriOS/i.test(ua)) && !/Edge|OPR|Edg|SamsungBrowser|Vivaldi|MiuiBrowser/i.test(ua);
    const isSafari = /Safari/i.test(ua) && !/Chrome|CriOS/i.test(ua) && !/SamsungBrowser|MiuiBrowser/i.test(ua);
    return (isChrome || isSafari) && !isInAppBrowser();
}

function requiresExternalBrowser() {
    return !isStandaloneBrowser();
}

function showExternalBrowserRequiredModal() {
    if (!requiresExternalBrowser()) return;
    const authModal = document.getElementById('auth-modal');
    if (authModal) authModal.style.display = 'none';
    const modal = document.getElementById('inapp-browser-modal');
    if (!modal) return;
    modal.hidden = false;
    document.body.classList.add('inapp-modal-open');
    applyTranslations();
}

function promptGoogleSignIn() {
    if (requiresExternalBrowser()) {
        showExternalBrowserRequiredModal();
        return;
    }
    const authModal = document.getElementById('auth-modal');
    if (!authModal) return;
    const v = document.getElementById('auth-banner-video');
    if (v && !v.src) {
        v.src = 'https://pub-2b53cd37b4a44642afdbb8bb470bde66.r2.dev/banner.mp4';
    }
    const googleBtn = document.getElementById('google-login-btn');
    const inAppNote = document.getElementById('inapp-auth-note');
    if (googleBtn) googleBtn.style.display = '';
    if (inAppNote) inAppNote.style.display = 'none';
    authModal.style.display = 'flex';
    applyTranslations();
}

window.copyPageLinkForExternal = async (url) => {
    const link = url || window.location.href;
    try {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(link);
        } else {
            const ta = document.createElement('textarea');
            ta.value = link;
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        }
        showToast(t('modals.inapp_link_copied'));
        return true;
    } catch (e) {
        showToast(t('common.toast_copy_failed', { msg: e?.message || '' }));
        return false;
    }
};

async function copyPageLinkSilent(url) {
    const link = url || window.location.href;
    try {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(link);
        } else {
            const ta = document.createElement('textarea');
            ta.value = link;
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        }
        return true;
    } catch {
        return false;
    }
}

window.openExternalBrowser = async (targetUrl) => {
    const url = targetUrl || window.location.href;
    const ua = navigator.userAgent || '';
    const isAndroid = /Android/i.test(ua);
    const isIOS = /iPhone|iPad|iPod/i.test(ua);

    await copyPageLinkSilent(url);

    const tryOpen = (href) => {
        try {
            const opened = window.open(href, '_blank');
            return opened != null;
        } catch {
            return false;
        }
    };

    if (isAndroid) {
        try {
            const parsed = new URL(url);
            const intent =
                `intent://${parsed.host}${parsed.pathname}${parsed.search}${parsed.hash}` +
                `#Intent;scheme=${parsed.protocol.replace(':', '')};` +
                `package=com.android.chrome;` +
                `S.browser_fallback_url=${encodeURIComponent(url)};end`;
            tryOpen(intent);
            showToast(t('modals.inapp_open_attempt'));
            return;
        } catch (e) {
            console.warn('[OpenBrowser] Android intent failed:', e);
        }
    }

    if (isIOS) {
        const noProto = url.replace(/^https?:\/\//, '');
        if (tryOpen(`x-safari-https://${noProto}`) || tryOpen(`googlechromes://${noProto}`)) {
            showToast(t('modals.inapp_open_attempt'));
            return;
        }
    }

    showToast(t('modals.inapp_open_attempt'));
};

// --- Browser Detection ---
function detectInAppBrowser() {
    if (requiresExternalBrowser()) {
        showExternalBrowserRequiredModal();
    }
}

// --- Premium Glow Effects ---
function initPremiumEffects() {
    // Mouse-follow Glow for Cards
    document.addEventListener('mousemove', e => {
        const cards = document.querySelectorAll('.card, .pricing-card, .wallet-card');
        cards.forEach(card => {
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            card.style.setProperty('--mouse-x', `${x}px`);
            card.style.setProperty('--mouse-y', `${y}px`);
        });
    });
}

// --- Video Synchronization ---
function syncVideos() {
    const v1 = document.getElementById('preview-motion');
    const v2 = document.getElementById('preview-result');

    if (!v1 || !v2) return;

    v1.addEventListener('play', () => {
        v2.currentTime = v1.currentTime;
        v2.play();
    });

    v1.addEventListener('pause', () => v2.pause());

    setInterval(() => {
        if (Math.abs(v1.currentTime - v2.currentTime) > 0.1) {
            v2.currentTime = v1.currentTime;
        }
    }, 1000);
}

// --- Video Interaction Helpers ---
window.handleVideoHover = (video, isHover) => {
    if (!video) return;

    // Detect desktop: precise pointer (mouse) OR wide screen
    const isDesktop = window.matchMedia('(pointer: fine)').matches || window.innerWidth > 1024;
    if (!isDesktop) return;

    if (isHover) {
        // Try to play with sound
        video.muted = false;
        video.volume = 1.0;
        
        const playPromise = video.play();
        if (playPromise !== undefined) {
            playPromise.catch(error => {
                // Autoplay policy: play muted if unmuted is blocked
                video.muted = true;
                video.play();
            });
        }
    } else {
        video.pause();
        video.muted = true;
    }
};

window.downloadUrl = (event, url, suggestedName) => {
    if (event) event.stopPropagation();
    if (!url) return;

    const clean = String(url).split('?')[0].split('#')[0].toLowerCase();
    const ext = clean.includes('.') ? clean.split('.').pop() : '';
    const mediaExts = {
        mp4: 'video/mp4', webm: 'video/webm', mov: 'video/quicktime',
        png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif'
    };
    if (mediaExts[ext]) {
        const name = suggestedName || `kaling_${Date.now()}.${ext}`;
        return window.downloadMedia(event, url, name, mediaExts[ext]);
    }

    const a = document.createElement('a');
    a.href = url;
    a.target = '_blank';
    a.download = suggestedName || url.split('/').pop().split('?')[0];
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
};

function normalizeDownloadUrl(url) {
    if (!url) return url;
    if (url.includes('workers.dev') && !url.includes('download=1')) {
        return url + (url.includes('?') ? '&' : '?') + 'download=1';
    }
    return url;
}

function buildNativeDownloadHref(sourceUrl, filename) {
    const params = new URLSearchParams({
        url: normalizeDownloadUrl(sourceUrl),
        name: filename || 'kaling_video.mp4',
    });
    return `/api/media-download?${params}`;
}

function triggerNativeBrowserDownload(sourceUrl, filename) {
    const href = buildNativeDownloadHref(sourceUrl, filename);
    const a = document.createElement('a');
    a.href = href;
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

window.downloadMedia = (event, url, filename) => {
    if (event) {
        event.stopPropagation();
        event.preventDefault();
    }
    if (!url) return;

    const name = filename || 'kaling_video.mp4';
    showToast(t('common.download_started'));
    try {
        triggerNativeBrowserDownload(url, name);
    } catch (err) {
        console.error('[downloadMedia]', err);
        try {
            const fallback = normalizeDownloadUrl(url);
            const a = document.createElement('a');
            a.href = fallback;
            a.rel = 'noopener';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            showToast(t('common.download_fallback'));
        } catch (e2) {
            showToast(t('common.error_with_msg', { msg: err.message || err }));
        }
    }
};

window.downloadMediaFromEl = (event, el) => {
    if (event) {
        event.stopPropagation();
        event.preventDefault();
    }
    if (!el?.dataset?.url) return;
    return window.downloadMedia(null, el.dataset.url, el.dataset.name, el.dataset.mime);
};

// --- Auth Functions ---
const SHOWCASE_VIDEOS_PAGE1 = 8;  // + upload card = 9 ô (3x3)
const SHOWCASE_VIDEOS_PER_PAGE = 9;

function getShowcaseRange(page) {
    if (page === 1) return { start: 0, count: SHOWCASE_VIDEOS_PAGE1 };
    const start = SHOWCASE_VIDEOS_PAGE1 + (page - 2) * SHOWCASE_VIDEOS_PER_PAGE;
    return { start, count: SHOWCASE_VIDEOS_PER_PAGE };
}

function getShowcaseTotalPages(totalVideos) {
    if (totalVideos <= SHOWCASE_VIDEOS_PAGE1) return 1;
    return 1 + Math.ceil((totalVideos - SHOWCASE_VIDEOS_PAGE1) / SHOWCASE_VIDEOS_PER_PAGE);
}

let _showcasePage = 1;
let _showcaseShuffled = [];

window.loadMoreShowcase = () => {
    _showcasePage++;
    window.renderShowcase();
};

window.renderShowcase = async (page) => {
    const gallery = document.getElementById('showcase-gallery');
    if (!gallery) return;

    if (!_showcaseShuffled.length) {
        gallery.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-muted)">Loading...</div>';
        await fetchTemplates();
        if (!TREND_VIDEOS.length) { gallery.innerHTML = ''; return; }
        _showcaseShuffled = [...TREND_VIDEOS].sort(() => Math.random() - 0.5);
    }

    if (page) _showcasePage = page;
    const visibleCount = _showcasePage * 8;
    const items = _showcaseShuffled.slice(0, visibleCount);

    const uploadCard = `
        <div class="showcase-card showcase-upload" onclick="window.pickVideoThenOpenModal()">
            <div class="showcase-upload-inner">
                <div class="showcase-upload-icon-wrap">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                        <polyline points="17 8 12 3 7 8"/>
                        <line x1="12" y1="3" x2="12" y2="15"/>
                    </svg>
                </div>
                <div class="showcase-upload-text">
                    <span class="showcase-upload-title" data-i18n="showcase.upload_your_video">${t('showcase.upload_your_video')}</span>
                    <small class="showcase-upload-hint">${t('showcase.upload_hint')}</small>
                </div>
            </div>
        </div>`;

    gallery.innerHTML = uploadCard + items.map(v => `
        <div class="showcase-card showcase-webp"
             onclick="window.playOrderVideo(event, '${v.url}')">
            <img class="showcase-preview" data-src="${v.thumb}" alt="${trendTitle(v)}">
            <div class="showcase-info">
                <div class="showcase-title">${trendTitle(v)}</div>
                <button class="use-trend-btn" onclick="event.stopPropagation(); window.useTrendShortcut('${v.id}', '${v.url}')">
                    ${window.t('showcase.use_this')}
                </button>
            </div>
        </div>
    `).join('');

    // Pagination / Load More
    let pagerEl = document.getElementById('showcase-pager');
    if (!pagerEl) {
        pagerEl = document.createElement('div');
        pagerEl.id = 'showcase-pager';
        pagerEl.className = 'pager';
        gallery.parentNode.appendChild(pagerEl);
    }
    if (visibleCount < _showcaseShuffled.length) {
        pagerEl.innerHTML = `<button class="use-trend-btn" style="padding: 0.75rem 2.5rem; font-size: 1rem; border-radius: 24px; cursor: pointer;" onclick="window.loadMoreShowcase()">${t('showcase.load_more')} (${visibleCount}/${_showcaseShuffled.length})</button>`;
    } else {
        pagerEl.innerHTML = '';
    }

    // Lazy load images
    gallery.querySelectorAll('img[data-src]').forEach(el => {
        const obs = new IntersectionObserver((entries) => {
            entries.forEach(e => { if (e.isIntersecting) { el.src = el.dataset.src; delete el.dataset.src; obs.unobserve(el); } });
        }, { rootMargin: '200px' });
        obs.observe(el);
    });

    initPremiumEffects();
};

// Lazy loading handled by IntersectionObserver in renderShowcase

window.pickVideoThenOpenModal = () => {
    const picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = 'video/*';
    picker.onchange = () => {
        if (!picker.files.length) return;
        window.openOrderModal();
        window.switchVideoSource('upload');
        setTimeout(() => {
            const fileInput = document.getElementById('file-video');
            if (fileInput) {
                const dt = new DataTransfer();
                dt.items.add(picker.files[0]);
                fileInput.files = dt.files;
                fileInput.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }, 150);
    };
    picker.click();
};

window.useTrendShortcut = (id, url) => {
    _tplPinnedId = id;
    _tplPage = 1;
    window.openOrderModal();
    window.switchVideoSource('library');
    setTimeout(() => {
        window.selectTemplate(id, url);
    }, 100);
};

async function login() {
    if (requiresExternalBrowser()) {
        showExternalBrowserRequiredModal();
        showToast(t('modals.inapp_browser_sub'));
        return;
    }
    try {
        await window.kalingApi.signInWithGoogle();
    } catch (error) {
        console.error("Login Error", error);
        showToast(t('common.toast_login_failed') + (error?.message ? ` (${error.message})` : ''));
    }
}

async function logout() {
    try {
        await window.kalingApi.signOut();
        showToast(t('common.toast_logout_success'));
    } catch (error) {
        console.error("Logout Error", error);
    }
}

// --- User Profile & Coin Balance (Supabase) ---
async function handleUserLoggedIn(authUser) {
    const pendingCode = getPendingReferralCode();
    const linked = await window.kalingApi.linkOrCreateUser(pendingCode || null);
    const kalingProfile = linked.user;
    if (!kalingProfile || !kalingProfile.uid) {
        throw new Error('Không thể liên kết tài khoản Kaling');
    }

    // Chuẩn hóa currentUser dùng đúng kaling_users.id (giữ nguyên Firebase UID cho user cũ)
    const user = {
        uid: kalingProfile.uid,
        authUid: authUser.id,
        email: kalingProfile.email || authUser.email || '',
        displayName: kalingProfile.displayName || authUser.user_metadata?.full_name || (authUser.email || '').split('@')[0],
        photoURL: kalingProfile.photoURL || authUser.user_metadata?.avatar_url || authUser.user_metadata?.picture || '',
    };
    currentUser = user;

    if (pendingCode && kalingProfile.referredBy) {
        try { clearPendingReferralCode(); } catch (_) { }
    }

    // Ẩn Auth Modal bắt buộc
    const authModal = document.getElementById('auth-modal');
    if (authModal) authModal.style.display = 'none';

    // Hiển thị Profile Menu
    document.getElementById('login-btn').style.display = 'none';
    document.getElementById('user-profile-menu').style.display = 'block';
    const navbarCoin = document.getElementById('navbar-coin-widget');
    if (navbarCoin) navbarCoin.style.display = 'flex';
    const navbarApi = document.getElementById('navbar-api-btn');
    if (navbarApi) navbarApi.style.display = 'flex';
    document.getElementById('dropdown-user-name').innerText = user.displayName || user.email.split('@')[0];
    document.getElementById('dropdown-user-email').innerText = user.email;

    const avatarImg = document.getElementById('user-menu-avatar');
    const avatarFallback = document.getElementById('user-menu-avatar-fallback');
    const photoUrl = user.photoURL;
    if (avatarImg && avatarFallback) {
        if (photoUrl) {
            avatarImg.src = photoUrl;
            avatarImg.style.display = 'block';
            avatarFallback.style.display = 'none';
        } else {
            avatarImg.style.display = 'none';
            avatarFallback.style.display = 'block';
        }
    }

    const dashIn = document.getElementById('dashboard-logged-in');
    const dashOut = document.getElementById('dashboard-auth-placeholder');
    if (dashIn) dashIn.style.display = 'block';
    if (dashOut) dashOut.style.display = 'none';

    if (window.pendingAction === 'openOrderModal') {
        window.pendingAction = null;
        setTimeout(() => {
            window.openOrderModal();
        }, 500);
    }

    if (typeof ttq !== 'undefined' && user.email) {
        ttq.identify({ email: user.email });
    }
    updateMetaAdvancedMatching(user);

    if (linked.isNew) {
        trackMetaEvent('CompleteRegistration', {
            value: 0,
            currency: 'VND',
            status: true,
            content_name: 'google.com'
        });
    }

    if (user.email) {
        trackAnalyticsEvent('login', { method: 'google' });
    }

    // Khởi tạo allowlist từ kết quả RPC luôn (không phải chờ thêm 2 query)
    window.__referralAllowed = Boolean(linked.isReferralAllowed);
    updateReferralNavVisibility(window.__referralAllowed);
    window.__batchChannelAllowed = Boolean(linked.isBatchChannelAllowed);
    updateBatchChannelNavVisibility(window.__batchChannelAllowed);

    const applyProfileData = (data) => {
        if (!data) return;
        FB_CACHE.userProfile = data;
        window.__currentUserData = data;
        renderPricing();
        updateCoursePromoBtnVisibility();
        const currentCoins = Number(data.coins || 0);
        if (FB_CACHE.myOrders) {
            syncPromo1CoinState(FB_CACHE.myOrders, data);
            updateFirstOrderUI();
        }

        // Tự động nhận biết nạp coin thành công
        const topupModal = document.getElementById('topup-modal');
        if (topupModal && topupModal.style.display === 'flex' && currentCoins > initialCoinsBeforeTopup) {
            showToast(t('common.toast_coins_added'));
            closeModal('topup-modal');
            document.querySelectorAll('.coin-balance-text').forEach(el => {
                el.classList.add('coin-update-glow');
                setTimeout(() => el.classList.remove('coin-update-glow'), 2000);
            });

            const addedCoins = currentCoins - initialCoinsBeforeTopup;
            const purchaseValue = selectedTopupPackage ? selectedTopupPackage.amount : addedCoins * 1000;
            const purchaseId = selectedTopupPackage ? selectedTopupPackage.id : 'coin_topup';
            const purchaseName = selectedTopupPackage ? selectedTopupPackage.name : 'Coin Topup';

            logFirebaseEvent('purchase', {
                value: purchaseValue,
                currency: 'VND',
                transaction_id: `topup_${Date.now()}`,
                items: [{ item_id: purchaseId, item_name: purchaseName }]
            });

            if (typeof ttq !== 'undefined') {
                ttq.track('CompletePayment', {
                    value: purchaseValue,
                    currency: 'VND',
                    content_id: purchaseId
                });
            }

            trackMetaEvent('Purchase', {
                value: purchaseValue,
                currency: 'VND',
                content_ids: [purchaseId],
                content_name: purchaseName,
                content_type: 'product',
                num_items: 1
            });

            sendTelegramMessage(`💰 <b>NẠP COIN THÀNH CÔNG!</b>\n👤 Khách: ${escapeHTML(data.displayName)}\n📧 Email: ${escapeHTML(data.email)}\n✨ Đã cộng: +${formatCoinAmount(addedCoins)} Coin\n💰 Số dư mới: ${formatCoinAmount(currentCoins)} Coin`);
        }

        document.querySelectorAll('.coin-balance-text').forEach(el => el.innerText = formatCoinAmount(currentCoins));
        document.querySelectorAll('.user-greeting-text').forEach(el => el.innerText = t('dashboard.greeting', { name: data.displayName }));
        document.querySelectorAll('.user-email-text').forEach(el => el.innerText = data.email);

        const isAdmin = data.role === 'admin' || data.role === 'super-admin' || SUPER_ADMIN_EMAILS.includes((data.email || '').toLowerCase());
        const isSuperAdmin = data.role === 'super-admin' || SUPER_ADMIN_EMAILS.includes((data.email || '').toLowerCase());
        window.__isAdmin = isAdmin;
        window.__isSuperAdmin = isSuperAdmin;

        updateBatchChannelNewBadge();
        updateBatchChannelNavVisibility(window.__batchChannelAllowed);
        updateFirstOrderUI();

        const adminProfileItem = document.getElementById('admin-dropdown-item-profile');
        const adminDivider = document.getElementById('admin-dropdown-divider');
        if (adminProfileItem) adminProfileItem.style.display = isAdmin ? 'flex' : 'none';
        if (adminDivider) adminDivider.style.display = isAdmin ? 'block' : 'none';
    };

    applyProfileData(kalingProfile);
    fbSub('userProfile', window.kalingApi.subscribeUserProfile(user.uid, applyProfileData));

    loadMyOrders();
    loadMyTopups();
    navigateFromURLParam();
}

function navigateFromURLParam() {
    try {
        const params = new URLSearchParams(window.location.search);
        const page = params.get('page');
        if (page === 'referral-page') {
            if (!window.__referralAllowed) {
                showDashboard();
                return;
            }
            showReferralPage();
        } else if (page === 'topup-history-page') {
            showTopupHistory();
        } else if (page === 'admin-panel' && window.__isAdmin) {
            showAdminPanel();
        } else if (page === 'build-channel-page' && currentUser) {
            if (!canUseBatchChannel()) {
                showDashboard();
                return;
            }
            showDashboard();
            window.openBatchChannelModal();
        } else if (page === 'user-dashboard') {
            showDashboard();
        } else {
            // Home = My videos
            showDashboard();
        }
        if (page) {
            const url = new URL(window.location.href);
            url.searchParams.delete('page');
            const clean = url.pathname + (url.search || '') + url.hash;
            window.history.replaceState({}, '', clean || '/');
        }
    } catch (e) {
        // Home = My videos
        showDashboard();
    }
}

function handleUserLoggedOut() {
    const v = document.getElementById('auth-banner-video');
    if (v && !v.src) {
        v.src = 'https://pub-2b53cd37b4a44642afdbb8bb470bde66.r2.dev/banner.mp4';
    }

    if (requiresExternalBrowser()) {
        showExternalBrowserRequiredModal();
        const loginBtn = document.getElementById('login-btn');
        if (loginBtn) loginBtn.style.display = 'none';
    } else {
        promptGoogleSignIn();
        const loginBtn = document.getElementById('login-btn');
        if (loginBtn) loginBtn.style.display = 'flex';
    }

    document.getElementById('user-profile-menu').style.display = 'none';
    const navbarCoin = document.getElementById('navbar-coin-widget');
    if (navbarCoin) navbarCoin.style.display = 'none';
    const navbarApi = document.getElementById('navbar-api-btn');
    if (navbarApi) navbarApi.style.display = 'none';

    // Toggle Dashboard sub-elements
    const dashIn = document.getElementById('dashboard-logged-in');
    const dashOut = document.getElementById('dashboard-auth-placeholder');
    if (dashIn) dashIn.style.display = 'none';
    if (dashOut) dashOut.style.display = 'block';

    const topupPage = document.getElementById('topup-history-page');
    if (topupPage) topupPage.style.display = 'none';
    const referralPage = document.getElementById('referral-page');
    if (referralPage) referralPage.style.display = 'none';
    const purgeBtnLogout = document.getElementById('btn-purge-inactive-users');
    if (purgeBtnLogout) purgeBtnLogout.style.display = 'none';
    const adminProfileItem = document.getElementById('admin-dropdown-item-profile');
    if (adminProfileItem) adminProfileItem.style.display = 'none';
    const adminDivider = document.getElementById('admin-dropdown-divider');
    if (adminDivider) adminDivider.style.display = 'none';

    // [TỐI ƯU] Cleanup TẤT CẢ Firebase listener khi logout.
    // Trước đây chỉ unsub referralEarnings -> các listener khác (myOrders, myTopups,
    // userProfile, adminOrders, adminTopups, adminUsers) tiếp tục sống và đọc data
    // dù user đã logout.
    fbUnsubAll();

    // Reset các flag/cache liên quan
    window.__isAdmin = false;
    window.__referralAllowed = false;
    updateReferralNavVisibility(false);
    window.__batchChannelAllowed = false;
    updateBatchChannelNavVisibility(false);
    window.__isSuperAdmin = false;
    window.__currentUserData = null;
    Object.keys(FB_CACHE).forEach(k => { delete FB_CACHE[k]; });
    if (typeof resetBatchChannelForm === 'function') {
        resetBatchChannelForm({ keepDefaults: true });
        closeModal('batch-channel-modal');
    }

    // Legacy var (giờ đã unsub trong fbUnsubAll, để null cho an toàn)
    referralEarningsUnsubscribe = null;

    isFirstTimeUser = false;
    updateFirstOrderUI();

    // Home = My videos (dashboard sẽ hiện placeholder login-required)
    showDashboard();
}

function showDashboard() {
    hideAllPages();
    document.getElementById('user-dashboard').style.display = 'block';
    window.scrollTo(0, 0);
    if (typeof updateBatchChannelNewBadge === 'function') updateBatchChannelNewBadge();
}

function showTopupHistory() {
    hideAllPages();
    document.getElementById('topup-history-page').style.display = 'block';
    window.scrollTo(0, 0);
}

function showBuildChannel() {
    if (!canUseBatchChannel()) {
        showToast(t('build_channel.not_allowed'));
        showDashboard();
        return;
    }
    window.openBatchChannelModal();
}

function showAdminPanel() {
    window.open(window.AQUA_ADMIN_KALING_URL || 'https://aquaai.vn/admin?app=kaling', '_blank', 'noopener');
}

function showLanding() {
    // Home = My videos
    showDashboard();
}

function hideAllPages() {
    const pages = ['landing-page', 'user-dashboard', 'topup-history-page', 'build-channel-page', 'referral-page'];
    pages.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
}

function showReferralPage() {
    if (!window.__referralAllowed) {
        showToast(t('referral.not_allowed'));
        showDashboard();
        return;
    }
    hideAllPages();
    document.getElementById('referral-page').style.display = 'block';
    window.scrollTo(0, 0);
    if (typeof openReferralPage === 'function') {
        openReferralPage();
    }
}

window.toggleDashboard = () => {
    if (document.getElementById('user-dashboard').style.display === 'none') {
        showDashboard();
    } else {
        showLanding();
    }
};

window.loginUser = login;
window.logoutUser = logout;
window.showLanding = showLanding;
window.showDashboard = showDashboard;

// Helper for navbar links
window.navTo = (target) => {
    document.getElementById('dropdown-menu')?.classList.remove('show');
    document.getElementById('lang-menu')?.classList.remove('show');

    if (target === 'user-dashboard') {
        showDashboard();
    } else if (target === 'topup-history-page') {
        showTopupHistory();
    } else if (target === 'build-channel-page') {
        showBuildChannel();
    } else if (target === 'referral-page') {
        showReferralPage();
    } else if (target === 'admin-panel') {
        showAdminPanel();
    } else if (target === 'landing-page') {
        showLanding();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    } else {
        // Cuộn đến section trong landing page
        showLanding();
        setTimeout(() => {
            const el = document.getElementById(target);
            if (el) el.scrollIntoView({ behavior: 'smooth' });
        }, 100);
    }
};

// Đóng menu khi click ra ngoài
window.addEventListener('click', () => {
    const userMenu = document.getElementById('dropdown-menu');
    if (userMenu) userMenu.classList.remove('show');
    const langMenu = document.getElementById('lang-menu');
    if (langMenu) langMenu.classList.remove('show');
});

window.logout = logout;

// Custom Confirm Helper
window.niceConfirm = ({ title, message, icon, onConfirm }) => {
    const modal = document.getElementById('confirm-modal');
    document.getElementById('confirm-title').innerText = title;
    document.getElementById('confirm-msg').innerText = message;
    document.getElementById('confirm-icon').innerText = icon || '⚠️';

    const yesBtn = document.getElementById('confirm-yes-btn');
    // Clear old listeners
    const newYesBtn = yesBtn.cloneNode(true);
    yesBtn.parentNode.replaceChild(newYesBtn, yesBtn);

    newYesBtn.onclick = () => {
        closeModal('confirm-modal');
        onConfirm();
    };

    modal.style.display = 'flex';
};

// Preview Helper
window.handlePreview = (input, containerId) => {
    const container = document.getElementById(containerId);
    const file = input.files[0];
    if (file) {
        const url = URL.createObjectURL(file);
        container.style.display = 'block';
        if (file.type.startsWith('image/')) {
            container.innerHTML = `<img src="${url}">`;
        } else {
            container.innerHTML = `<video src="${url}" autoplay muted loop></video>`;
        }
    }
};

window.copyToClipboard = (text) => {
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
        showToast(t('common.toast_copied'));
    }).catch(err => {
        console.error('Lỗi khi copy:', err);
    });
};

// Copy link kết quả trong admin order detail modal
window.copyAdminResultLink = () => {
    const input = document.getElementById('admin-result-link');
    if (!input) return;
    const link = input.value.trim();
    if (!link) {
        showToast(t('admin.toast_no_result_link'));
        return;
    }
    // Fallback cho trình duyệt cũ / context không phải HTTPS
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(link).then(() => {
            showToast(t('admin.toast_result_copied'));
        }).catch(() => {
            input.select();
            input.setSelectionRange(0, 99999);
            try { document.execCommand('copy'); showToast(t('admin.toast_result_copied')); }
            catch (e) { showToast(t('common.toast_copy_failed', { msg: e.message })); }
        });
    } else {
        input.select();
        input.setSelectionRange(0, 99999);
        try { document.execCommand('copy'); showToast(t('admin.toast_result_copied')); }
        catch (e) { showToast(t('common.toast_copy_failed', { msg: e.message })); }
    }
};


// --- Rendering ---
function renderPricing() {
    const coinGrid = document.getElementById('coin-packages');
    const modalCoinGrid = document.getElementById('modal-coin-packages');
    const filteredPackages = getVisibleCoinPackages();

    const vietqrPayIcon = `<svg class="pricing-pay-icon pricing-pay-icon--vietqr" viewBox="0 0 24 24" aria-hidden="true"><rect width="24" height="24" rx="3" fill="#DA251D"/><path fill="#FFCD00" d="M12 5.4l1.55 3.14 3.46.5-2.5 2.44.59 3.45L12 14.7l-3.1 1.63.59-3.45-2.5-2.44 3.46-.5L12 5.4z"/></svg>`;
    const coinIcon = `<svg class="coin-icon-svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 2L20.66 7V17L12 22L3.34 17V7L12 2Z" fill="url(#coin-gradient)" fill-opacity="0.2" stroke="url(#coin-gradient)" stroke-width="2"/><path d="M12 6L17.2 9V15L12 18L6.8 15V9L12 6Z" fill="url(#coin-gradient)"/><path d="M12 9V15M9 12H15" stroke="white" stroke-width="1.5" stroke-linecap="round"/></svg>`;

    const buildCoinCard = (pkg, { showFeatures = false } = {}) => {
        const noteText = t(`pricing.notes.${pkg.id}`);
        const showNote = noteText && !noteText.startsWith('pricing.notes.');

        // Custom render for Gói Học Viên (Student Course Package)
        if (pkg.id === 'hocvien_package') {
            const courseTitle = t('pricing.packages.hocvien_package') || 'Gói Học Viên';
            const featuresList = `
                <ul class="pkg-features" style="text-align: left; margin: 12px 0; padding-left: 0; list-style: none; font-size: 0.82rem; line-height: 1.6; color: #ececf1; display: flex; flex-direction: column; gap: 8px;">
                    <li style="display: flex; gap: 8px; align-items: flex-start;"><span style="color: #fbbf24;">🌱</span> <span>Làm video với giá <strong>3k/video</strong> (Giảm 50% trọn đời sau khi học)</span></li>
                    <li style="display: flex; gap: 8px; align-items: flex-start;"><span style="color: #fbbf24;">🌱</span> <span>Học <strong>1 kèm 1</strong></span></li>
                    <li style="display: flex; gap: 8px; align-items: flex-start;"><span style="color: #fbbf24;">🌱</span> <span>Tặng <strong>10 coin</strong></span></li>
                    <li style="display: flex; gap: 8px; align-items: flex-start;"><span style="color: #fbbf24;">🌱</span> <span>Tặng <strong>tool thay đồ, làm ảnh</strong> (199k)</span></li>
                </ul>
            `;
            return `
            <div class="price-card price-card--coin featured price-card--coin-featured" style="
                background: linear-gradient(135deg, rgba(28, 22, 16, 0.9) 0%, rgba(18, 14, 10, 0.96) 100%) !important;
                border: 2px solid #eab308 !important;
                box-shadow: 0 0 25px rgba(234, 179, 8, 0.25) !important;
                position: relative;
                transform: scale(1.02);
            ">
                <div class="featured-badge" style="background: #eab308; color: #000; font-weight: 800;">🔥 ${courseTitle.toUpperCase()}</div>
                <div class="price-card-note" style="color: #fbbf24; font-weight: 700; font-size: 0.85rem; text-transform: uppercase;">${showNote ? noteText : 'ƯU ĐÃI KHÓA HỌC'}</div>
                
                <div style="margin: 15px 0 10px 0; text-align: center;">
                    <span style="font-size: 0.85rem; color: var(--text-muted); text-decoration: line-through; display: block; margin-bottom: 2px;">Gốc 1.500.000đ</span>
                    <span style="font-size: 1.8rem; font-weight: 800; color: #fff; background: linear-gradient(135deg, #fef08a 0%, #eab308 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">699.000đ</span>
                </div>

                ${featuresList}

                <div class="pricing-pay-actions" style="display: flex; gap: 8px; width: 100%; margin-top: 10px;">
                    <button type="button" class="pricing-pay-btn pricing-pay-btn--vietqr" onclick="window.selectTopup('${pkg.id}', 'vietqr')" style="flex: 1.3; padding: 10px 8px; font-size: 0.78rem; border-radius: 8px; height: 38px; display: flex; align-items: center; justify-content: center; gap: 4px;">
                        ${vietqrPayIcon}
                        <span class="pricing-pay-label" style="font-size: 0.75rem; white-space: nowrap;">${t('pricing.pay_vietqr')}</span>
                    </button>
                    <a href="https://zalo.me/0965951536" target="_blank" rel="noopener noreferrer" class="btn-secondary" style="flex: 0.7; display: flex; align-items: center; justify-content: center; gap: 4px; padding: 10px 8px; font-size: 0.78rem; text-decoration: none; border-radius: 8px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-weight: 600; height: 38px; box-sizing: border-box; line-height: 1; margin: 0;">
                        <img src="/assets/zalo-icon.png" style="width: 14px; height: 14px; object-fit: contain;" />
                        <span>Tư vấn</span>
                    </a>
                </div>
            </div>
            `;
        }

        const featuresHtml = showFeatures ? `
            <ul class="pkg-features">
                <li><span class="check-icon">✓</span> ${t('pricing.instant_credit')}</li>
                <li><span class="check-icon">✓</span> ${t('pricing.high_quality')}</li>
                <li><span class="check-icon">✓</span> ${t('pricing.no_expiry')}</li>
            </ul>` : '';
        return `
        <div class="price-card price-card--coin${pkg.featured ? ' featured price-card--coin-featured' : ''}">
            ${pkg.featured ? `<div class="featured-badge">🔥 ${t('pricing.featured_hot')}</div>` : ''}
            <div class="price-card-note">${showNote ? noteText : '&#8203;'}</div>
            <div class="coin-amount-display">
                ${coinIcon}
                <span class="coin-amount-num">${pkg.coins}</span>
            </div>
            <div class="price-card-bonus-hint${pkg.hasBonus ? '' : ' price-card-bonus-hint--empty'}">${t('pricing.bonus_included_note')}</div>
            <div class="price-value">${pkg.price}</div>
            ${featuresHtml}
            <div class="pricing-pay-actions pricing-pay-actions--single">
                <button type="button" class="pricing-pay-btn pricing-pay-btn--vietqr pricing-pay-btn--full" onclick="window.selectTopup('${pkg.id}', 'vietqr')">
                    ${vietqrPayIcon}
                    <span class="pricing-pay-label pricing-pay-label--single">${t('pricing.pay_vietqr')}</span>
                </button>
            </div>
        </div>
    `;
    };

    if (coinGrid) {
        coinGrid.innerHTML = filteredPackages.map(pkg => buildCoinCard(pkg, { showFeatures: true })).join('');
    }
    if (modalCoinGrid) {
        modalCoinGrid.innerHTML = filteredPackages.map(pkg => buildCoinCard(pkg, { showFeatures: false })).join('');
    }
}

function renderServicePackages() {
    const grid = document.getElementById('service-packages');
    if (!grid) return;

    grid.innerHTML = SERVICE_PACKAGES.map(pkg => `
        <div class="price-card ${pkg.featured ? 'featured' : ''}">
            ${pkg.featured ? `<div class="featured-badge">🔥 ${t('pricing.featured_hot')}</div>` : ''}
            <h3>${serviceDisplayName(pkg)}</h3>
            <div class="coin-visual-wrapper">
                <svg class="coin-icon-svg" style="width: 24px; height: 24px;" viewBox="0 0 24 24" fill="none">
                    <path d="M12 2L20.66 7V17L12 22L3.34 17V7L12 2Z" fill="url(#coin-gradient)" fill-opacity="0.2" stroke="url(#coin-gradient)" stroke-width="2"/>
                    <path d="M12 6L17.2 9V15L12 18L6.8 15V9L12 6Z" fill="url(#coin-gradient)"/>
                    <path d="M12 9V15M9 12H15" stroke="white" stroke-width="1.5" stroke-linecap="round"/>
                </svg>
                <span>${pkg.cost} ${t('common.coins_unit')}</span>
            </div>
            <ul class="pkg-features">
                ${(pkg.featureKeys || []).map(k => `<li><span class="check-icon">✓</span> ${t(k)}</li>`).join('')}
            </ul>
            <button class="btn-primary" onclick="window.openOrderModal()" style="width: 100%; margin-top: auto;">
                ${t('pricing.start_now')}
            </button>
        </div>
    `).join('');
}

// --- Video Library ---
// --- Video Library ---
window.switchVideoSource = (type) => {
    const uploadBtn = document.getElementById('tab-upload');
    const tiktokBtn = document.getElementById('tab-tiktok');
    const libraryBtn = document.getElementById('tab-library');
    const uploadSection = document.getElementById('video-upload-section');
    const tiktokSection = document.getElementById('video-tiktok-section');
    const librarySection = document.getElementById('video-library-section');

    document.querySelectorAll('#order-modal .video-tab').forEach((tab) => tab.classList.remove('active'));
    if (uploadSection) uploadSection.style.display = 'none';
    if (tiktokSection) tiktokSection.style.display = 'none';
    if (librarySection) librarySection.style.display = 'none';

    if (type === 'upload') {
        uploadBtn?.classList.add('active');
        if (uploadSection) uploadSection.style.display = 'block';
        window.currentVideoSource = 'upload';
        const fileInput = document.getElementById('file-video');
        const existing = fileInput?.files?.[0];
        if (existing?.type?.startsWith('video/')) {
            renderVideoFilePreview('preview-video-container', existing, {
                inputId: 'file-video',
                changeKey: 'modals.video_change',
                maxDurationSec: getMaxVideoSecForSelectedModel()
            });
        }
    } else if (type === 'tiktok') {
        tiktokBtn?.classList.add('active');
        if (tiktokSection) tiktokSection.style.display = 'block';
        window.currentVideoSource = 'upload';
    } else if (type === 'library') {
        libraryBtn?.classList.add('active');
        if (librarySection) {
            librarySection.style.display = 'block';
            window.currentVideoSource = 'library';
            renderTemplates();
        }
    }
};

const TPL_PER_PAGE = 4;
let _tplPage = 1;
let _tplPinnedId = null;

window.renderTemplates = async (page) => {
    const grid = document.getElementById('template-library-grid');
    if (!grid) return;

    if (!_templatesFetched) {
        grid.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--text-muted)">Loading...</div>';
        await fetchTemplates();
    }
    if (!TREND_VIDEOS.length) {
        grid.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--text-muted)">No templates</div>';
        return;
    }

    // Build list: pinned item first, then rest shuffled
    let ordered;
    if (_tplPinnedId) {
        const pinned = TREND_VIDEOS.find(v => v.id === _tplPinnedId);
        const rest = TREND_VIDEOS.filter(v => v.id !== _tplPinnedId).sort(() => Math.random() - 0.5);
        ordered = pinned ? [pinned, ...rest] : rest;
    } else {
        ordered = [...TREND_VIDEOS].sort(() => Math.random() - 0.5);
    }

    if (page) _tplPage = page;
    const totalPages = Math.ceil(ordered.length / TPL_PER_PAGE);
    if (_tplPage < 1) _tplPage = 1;
    if (_tplPage > totalPages) _tplPage = totalPages;

    const start = (_tplPage - 1) * TPL_PER_PAGE;
    const items = ordered.slice(start, start + TPL_PER_PAGE);

    grid.innerHTML = items.map(t => `
        <div class="template-item${t.id === _tplPinnedId ? ' active' : ''}" id="tpl-${t.id}" 
             onclick="window.previewTemplate('${t.id}')"
             onmouseenter="window.handleVideoHover(this.querySelector('video'), true)" 
             onmouseleave="window.handleVideoHover(this.querySelector('video'), false)">
            <video class="template-video" src="${t.url}#t=1" poster="${t.thumb}" muted loop playsinline preload="metadata"></video>
            <div class="template-overlay">${trendTitle(t)}</div>
        </div>
    `).join('');

    // Pagination
    let pagerEl = document.getElementById('tpl-pager');
    if (!pagerEl) {
        pagerEl = document.createElement('div');
        pagerEl.id = 'tpl-pager';
        pagerEl.className = 'pager pager-compact';
        grid.parentNode.appendChild(pagerEl);
    }
    if (totalPages <= 1) {
        pagerEl.innerHTML = '';
    } else {
        let pagerHtml = '';
        if (_tplPage > 1) pagerHtml += `<button class="pager-btn" onclick="window.renderTemplates(${_tplPage - 1})">‹</button>`;
        for (let i = 1; i <= totalPages; i++) {
            pagerHtml += `<button class="pager-btn${i === _tplPage ? ' active' : ''}" onclick="window.renderTemplates(${i})">${i}</button>`;
        }
        if (_tplPage < totalPages) pagerHtml += `<button class="pager-btn" onclick="window.renderTemplates(${_tplPage + 1})">›</button>`;
        pagerEl.innerHTML = pagerHtml;
    }
};

window.previewTemplate = (id) => {
    const template = TREND_VIDEOS.find(t => t.id === id);
    if (!template) return;

    const modal = document.getElementById('template-preview-modal');
    const video = document.getElementById('template-preview-video');
    const nameText = document.getElementById('template-preview-name');
    const confirmBtn = document.getElementById('template-confirm-btn');

    if (modal && video) {
        video.src = template.url;
        nameText.innerText = trendTitle(template);
        modal.style.display = 'flex';
        video.play();

        confirmBtn.onclick = () => {
            window.selectTemplate(template.id, template.url);
            window.closeTemplatePreview();
        };
    }
};

window.closeTemplatePreview = () => {
    const modal = document.getElementById('template-preview-modal');
    const video = document.getElementById('template-preview-video');
    if (modal && video) {
        video.pause();
        video.src = '';
        modal.style.display = 'none';
    }
};

window.selectTemplate = async (id, url) => {
    document.querySelectorAll('.template-item').forEach(el => el.classList.remove('active'));
    const item = document.getElementById(`tpl-${id}`);
    if (item) item.classList.add('active');
    document.getElementById('selected-template-url').value = url;
    window.currentVideoSource = 'library';
    const trend = TREND_VIDEOS.find(t => t.id === id);
    showToast(t('modals.toast_trend_selected', { title: trend ? trendTitle(trend) : id }));
    const dur = await getVideoDurationFromUrl(url);
    const maxSec = getMaxVideoSecForSelectedModel();
    kalingSelectedDurationSec = dur;
    if (dur != null && dur > maxSec + 0.15) {
        showToast(t('modals.video_will_trim_on_submit', { sec: maxSec }));
    }
    updateFirstOrderUI();
};

window.currentVideoSource = 'upload';

// --- Modals ---
window.playOrderVideo = (event, videoUrl) => {
    if (event) event.stopPropagation();
    const modal = document.getElementById('video-viewer-modal');
    const video = document.getElementById('full-res-video');
    if (modal && video) {
        video.src = videoUrl;
        modal.style.display = 'flex';
        video.play();
    }
};

window.closeVideoModal = () => {
    const modal = document.getElementById('video-viewer-modal');
    const video = document.getElementById('full-res-video');
    if (modal && video) {
        video.pause();
        video.src = '';
        modal.style.display = 'none';
    }
};

window.openModal = (id) => {
    document.getElementById(id).style.display = 'flex';
};

window.closeModal = (id) => {
    if (id === 'auth-modal') return; // non-dismissible
    if (id === 'topup-modal') clearTopupComplaintState();
    document.getElementById(id).style.display = 'none';
};

window.openTopupModal = () => {
    window.openPricingModal();
};

window.openPricingModal = () => {
    if (!currentUser) return login();
    renderPricing();
    window.openModal('pricing-modal');
    
    // TikTok Pixel: ViewContent (Viewing Topup Packages)
    if (typeof ttq !== 'undefined') {
        ttq.track('ViewContent', {
            content_name: 'Topup Packages',
            content_type: 'product_group',
            content_id: 'all_packages'
        });
    }

    trackMetaEvent('ViewContent', {
        content_name: 'Topup Packages',
        content_type: 'product_group',
        content_ids: ['all_packages']
    });

    // Firebase Analytics: view_item_list
    logFirebaseEvent('view_item_list', { item_list_name: 'Topup Packages' });
};

window.selectTopup = async (id, method = 'vietqr') => {
    if (!currentUser) return login();

    selectedTopupPackage = COIN_PACKAGES.find(p => p.id === id);
    if (!selectedTopupPackage || !getVisibleCoinPackages().some((p) => p.id === id)) {
        return showToast(t('pricing.topup_once_used'));
    }
    selectedPaymentMethod = 'vietqr';

    initialCoinsBeforeTopup = parseInt((document.getElementById('coin-balance') || document.querySelector('.coin-balance-text'))?.innerText) || 0;

    closeModal('pricing-modal');
    showPaymentPanel('vietqr');

    if (typeof ttq !== 'undefined') {
        ttq.track('InitiateCheckout', {
            value: selectedTopupPackage.amount,
            currency: 'VND',
            content_id: selectedTopupPackage.id
        });
    }

    trackMetaEvent('InitiateCheckout', {
        value: selectedTopupPackage.amount,
        currency: 'VND',
        content_ids: [selectedTopupPackage.id],
        content_name: selectedTopupPackage.name,
        content_type: 'product',
        num_items: 1
    });

    logFirebaseEvent('begin_checkout', {
        value: selectedTopupPackage.amount,
        currency: 'VND',
        items: [{ item_id: selectedTopupPackage.id, item_name: selectedTopupPackage.name }]
    });

    let transferContent = "";
    let pendingTopupId = null;
    const TOPUP_PREFIX = "KL"; // Prefix Casso — Kaling (kaling.cloud)

    try {
        const res = await window.kalingApi.createOrReusePendingTopup(currentUser, selectedTopupPackage, TOPUP_PREFIX);
        pendingTopupId = res.topupId;
        transferContent = res.transferContent;
        console.log(res.reused ? "♻️ Đơn nạp pending:" : "📝 Tạo đơn nạp mới:", transferContent);
    } catch (err) {
        console.error("Lỗi khi kiểm tra/tạo bản ghi nạp tiền:", err);
        const randomStr = Math.random().toString(36).substring(2, 6).toUpperCase();
        transferContent = `${TOPUP_PREFIX}${selectedTopupPackage.coins}${randomStr}`;
    }

    window.__topupComplaintCtx = {
        topupId: pendingTopupId,
        transferContent,
        coins: selectedTopupPackage.coins,
        amount: selectedTopupPackage.amount,
        packageName: selectedTopupPackage.name,
        packageId: selectedTopupPackage.id,
        userId: currentUser.uid,
        userEmail: currentUser.email || '',
        userName: currentUser.displayName || currentUser.email || '',
        openedAt: Date.now(),
        reported: false
    };
    scheduleTopupComplaintButton();

    document.getElementById('topup-package-info').innerHTML = `
        <div class="topup-info-card">
            <div class="topup-info-main">
                <div class="coin-visual-wrapper">
                    <svg class="coin-icon-svg premium-coin" viewBox="0 0 24 24" fill="none">
                        <path d="M12 2L20.66 7V17L12 22L3.34 17V7L12 2Z" fill="url(#coin-gradient)" fill-opacity="0.2" stroke="url(#coin-gradient)" stroke-width="2"/>
                        <path d="M12 6L17.2 9V15L12 18L6.8 15V9L12 6Z" fill="url(#coin-gradient)"/>
                        <path d="M12 9V15M9 12H15" stroke="white" stroke-width="1.5" stroke-linecap="round"/>
                    </svg>
                </div>
                <div class="package-details">
                    <div class="pkg-label">${t('dashboard.col_package')}</div>
                    <div class="pkg-name">${packageDisplayName(selectedTopupPackage)}</div>
                    <div class="pkg-coins">${t('payment.intl_coins', { coins: selectedTopupPackage.coins })}</div>
                </div>
            </div>
            <div class="topup-info-price">
                <div class="price-label">${t('dashboard.col_amount')}</div>
                <div class="price-val">${selectedTopupPackage.price}</div>
            </div>
        </div>
    `;

    document.getElementById('transfer-code').innerText = transferContent;

    const qrImg = document.getElementById('qr-code-img');
    const qrLoader = document.getElementById('qr-loader');

    qrImg.style.display = 'none';
    qrLoader.style.display = 'flex';

    qrImg.onload = () => {
        qrLoader.style.display = 'none';
        qrImg.style.display = 'block';
        document.getElementById('btn-save-qr').style.display = 'block';
    };

    const amount = selectedTopupPackage.amount;
    const bankId = "OCB";
    const accNo = "CASS0965951536";
    const accName = "VAN DINH HOANG";
    const qrUrl = `https://img.vietqr.io/image/${bankId}-${accNo}-compact2.png?amount=${amount}&addInfo=${encodeURIComponent(transferContent)}&accountName=${encodeURIComponent(accName)}`;

    qrImg.src = qrUrl;

    window.openModal('topup-modal');
};

window.openOrderModal = () => {
    updateRoboneoTrialUI(window.__currentUserData);
    updateOrderModelSelectionUI();
    const checked = document.querySelector('input[name="model-type"]:checked');
    if (!checked || !DURATION_MODEL_KEYS.includes(checked.value)) {
        const defaultModel = document.querySelector('input[name="model-type"][value="ad20"]');
        if (defaultModel) defaultModel.checked = true;
    }
    updateFirstOrderUI();
    window.switchVideoSource('upload');
    window.openModal('order-modal');

    requestAnimationFrame(() => {
        setTimeout(() => {
            document.querySelectorAll('#order-modal .modal-body, #order-modal .modal-content').forEach(el => {
                el.scrollTop = 0;
            });
            const orderForm = document.getElementById('order-form');
            if (orderForm) orderForm.scrollTop = 0;
        }, 300);
    });

    // TikTok Pixel: ViewContent (Viewing AI Service)
    if (typeof ttq !== 'undefined') {
        ttq.track('ViewContent', {
            content_name: 'AI Video Service',
            content_type: 'product',
            content_id: 'ai_video_generation'
        });
    }

    trackMetaEvent('ViewContent', {
        content_name: 'AI Video Service',
        content_type: 'product',
        content_ids: ['ai_video_generation']
    });
};

function updateRoboneoTrialUI(userData = window.__currentUserData) {
    const wrap = document.getElementById('model-rbtrial-wrap');
    const countdownEl = document.getElementById('rbtrial-countdown');
    const eligible = isRoboneoTrialEligible(userData);

    if (wrap) wrap.style.display = eligible ? '' : 'none';
    if (countdownEl) {
        countdownEl.textContent = eligible ? formatRoboneoTrialRemaining(userData) : '';
    }

    if (!eligible) {
        const trialRadio = document.querySelector(`input[name="model-type"][value="${ROBONEO_TRIAL.modelKey}"]`);
        if (trialRadio?.checked) {
            const fallback = document.querySelector('input[name="model-type"][value="ad20"]');
            if (fallback) fallback.checked = true;
        }
    }
}

window.updateCoursePromoBtnVisibility = () => {
    const promoBtn = document.getElementById('home-course-promo-btn');
    if (promoBtn) {
        const uData = (window.__currentUserData || (typeof FB_CACHE !== 'undefined' && FB_CACHE.userProfile)) || null;
        const isHocVien = (window.__batchChannelAllowed === true) || (uData && (
            uData.role === 'hocvien' ||
            uData.role === 'student' ||
            uData.isHocVien === true ||
            uData.isStudent === true
        ));
        promoBtn.style.display = isHocVien ? 'none' : 'inline-flex';
    }
};

function updateFirstOrderUI() {
    updateRoboneoTrialUI(window.__currentUserData);
    updateOrderModelSelectionUI();
    const costEl = document.getElementById('submit-cost');
    const offerBanner = document.getElementById('first-order-offer-banner');
    const guestOfferBar = document.getElementById('guest-offer-bar');
    const modelGroupEl = document.getElementById('model-selection-group');

    if (offerBanner) offerBanner.style.display = 'none';
    if (guestOfferBar) guestOfferBar.style.display = 'none';
    if (modelGroupEl) modelGroupEl.style.display = '';

    if (costEl) {
        const submitBtn = document.getElementById('order-submit-btn');
        const submitText = submitBtn ? submitBtn.querySelector('[data-i18n="hero.cta_create"]') : null;
        const summaryEl = document.getElementById('submit-summary-line');
        const modelKey = getSelectedModelKey();
        const lm = localizedModel(modelKey);
        syncModelPriceLabels();

        if (lm && lm.cost !== '—') {
            costEl.innerText = String(lm.cost);
        } else {
            costEl.innerText = '—';
        }
        if (submitBtn) {
            submitBtn.classList.remove('btn-first-offer', 'btn-trial-offer');
        }
        const isTrialModel = modelKey === ROBONEO_TRIAL.modelKey
            && isRoboneoTrialEligible(window.__currentUserData);
        if (submitBtn && isTrialModel) {
            submitBtn.classList.add('btn-trial-offer');
        }
        const titleEl = document.getElementById('submit-title-line');
        if (titleEl) {
            titleEl.innerText = isTrialModel
                ? t('modals.trial_submit_cta')
                : t('hero.cta_create');
        } else if (submitText) {
            submitText.innerText = isTrialModel
                ? t('modals.trial_submit_cta')
                : t('hero.cta_create');
        }
        if (summaryEl) {
            if (isTrialModel) {
                const ms = getRoboneoTrialRemainingMs(window.__currentUserData);
                const h = Math.floor(ms / 3600000);
                const m = Math.floor((ms % 3600000) / 60000);
                summaryEl.innerText = ms > 0
                    ? t('modals.trial_submit_note_time', { h, m })
                    : t('modals.trial_submit_note');
                summaryEl.style.color = '';
            } else {
                summaryEl.innerText = lm ? lm.time : t(`modals.model_${modelKey}_desc`);
                summaryEl.style.color = '';
            }
        }
    }
}

window.closeOfferBar = () => {
    const bar = document.getElementById('guest-offer-bar');
    if (bar) bar.style.display = 'none';
    sessionStorage.setItem('offer_bar_dismissed', 'true');
};

window.niceConfirm = ({ title, message, icon, onConfirm }) => {
    document.getElementById('confirm-title').innerText = title;
    document.getElementById('confirm-msg').innerHTML = message; // Changed to innerHTML to support <br> and <i>
    document.getElementById('confirm-icon').innerText = icon || '❓';

    const yesBtn = document.getElementById('confirm-yes-btn');
    const newBtn = yesBtn.cloneNode(true);
    yesBtn.parentNode.replaceChild(newBtn, yesBtn);

    newBtn.onclick = () => {
        closeModal('confirm-modal');
        if (onConfirm) onConfirm();
    };

    window.openModal('confirm-modal');
};

function syncUploadZonePreviewState(container) {
    const zone = container?.closest('.upload-zone');
    if (!zone) return;
    zone.classList.toggle('has-preview', !!container?.querySelector('img, video'));
}

function appendPreviewChangeButton(container, inputId, labelKey) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'preview-change-btn btn-primary order-upload-btn';
    btn.textContent = t(labelKey);
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        document.getElementById(inputId)?.click();
    });
    container.appendChild(btn);
}

const TIKWM_API = 'https://www.tikwm.com/api/';
let _ffmpegLoadPromise = null;

function showVideoTrimOverlay(messageKey, params = {}, descKey = 'modals.video_trim_wait') {
    const overlay = document.getElementById('video-trim-overlay');
    const titleEl = document.getElementById('video-trim-title');
    const descEl = document.getElementById('video-trim-desc');
    if (!overlay) return;
    if (overlay.style.display === 'flex') {
        updateVideoTrimOverlay(messageKey, params, descKey);
        return;
    }
    document.body.classList.add('video-trim-active');
    if (titleEl && messageKey) titleEl.textContent = t(messageKey, params);
    if (descEl) descEl.textContent = t(descKey);
    overlay.style.display = 'flex';
    overlay.setAttribute('aria-hidden', 'false');
}

function updateVideoTrimOverlay(messageKey, params = {}, descKey) {
    const titleEl = document.getElementById('video-trim-title');
    const descEl = document.getElementById('video-trim-desc');
    if (titleEl && messageKey) titleEl.textContent = t(messageKey, params);
    if (descEl && descKey) descEl.textContent = t(descKey);
}

function hideVideoTrimOverlay() {
    const overlay = document.getElementById('video-trim-overlay');
    if (!overlay) return;
    overlay.style.display = 'none';
    overlay.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('video-trim-active');
}

function resetOrderSubmitUi(submitBtn, progressDiv) {
    hideVideoTrimOverlay();
    if (submitBtn) submitBtn.disabled = false;
    if (progressDiv) progressDiv.style.display = 'none';
    const mainText = submitBtn?.querySelector('[data-i18n="hero.cta_create"]');
    if (mainText) mainText.innerText = t('hero.cta_create');
    updateFirstOrderUI();
}

function referenceVideoNeedsTrim(refDurationSec, maxSec, { useLibrary = false } = {}) {
    if (prefersServerSideTrim()) {
        return false;
    }
    if (refDurationSec == null || !Number.isFinite(refDurationSec)) {
        return useLibrary;
    }
    return refDurationSec > maxSec + 0.15;
}

function isMobileLikeClient() {
    const ua = navigator.userAgent || '';
    if (/Android|iPhone|iPad|iPod|Mobile/i.test(ua)) return true;
    if (typeof isInAppBrowser === 'function' && isInAppBrowser()) return true;
    return navigator.maxTouchPoints > 1 && window.innerWidth <= 1024;
}

function prefersServerSideTrim() {
    return true;
}

function withTrimTimeout(promise, ms, label = 'trim') {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
            reject(new Error(`${label}_timeout`));
        }, ms);
        Promise.resolve(promise).then(
            (value) => {
                clearTimeout(timer);
                resolve(value);
            },
            (err) => {
                clearTimeout(timer);
                reject(err);
            }
        );
    });
}

function setVideoFileInput(file) {
    const fileInput = document.getElementById('file-video');
    if (!fileInput || !file) return;
    const dt = new DataTransfer();
    dt.items.add(file);
    fileInput.files = dt.files;
}

function isTikTokPageUrl(raw) {
    try {
        const u = new URL(raw.trim());
        if (u.protocol !== 'https:' && u.protocol !== 'http:') return false;
        const host = u.hostname.toLowerCase();
        return host === 'tiktok.com' || host.endsWith('.tiktok.com');
    } catch {
        return false;
    }
}

function tiktokErrorMessage(code) {
    const msgKey = {
        invalid_url: 'modals.tiktok_url_invalid',
        duration_limit: 'modals.video_duration_limit',
        size_limit: 'modals.video_size_limit',
        fetch_failed: 'modals.tiktok_fetch_failed',
        video_download: 'modals.tiktok_fetch_failed',
        tikwm_parse: 'modals.tiktok_fetch_failed',
        no_video: 'modals.tiktok_fetch_failed',
        trim_failed: 'modals.tiktok_trim_failed'
    }[code] || 'modals.tiktok_fetch_failed';
    return t(msgKey);
}

async function resolveTikTokViaTikwm(pageUrl) {
    const res = await fetch(`${TIKWM_API}?url=${encodeURIComponent(pageUrl.trim())}&hd=1`);
    if (!res.ok) throw Object.assign(new Error('tikwm_http'), { code: 'fetch_failed' });
    const payload = await res.json();
    if (payload?.code !== 0 || !payload?.data) {
        throw Object.assign(new Error('tikwm_parse'), { code: 'tikwm_parse' });
    }
    const data = payload.data;
    const videoUrl = data.hdplay || data.play || data.wmplay;
    if (!videoUrl) throw Object.assign(new Error('no_video'), { code: 'no_video' });
    return {
        videoUrl,
        duration: Number(data.duration || data.video_duration || 0)
    };
}

async function downloadTikTokBlobViaWorker(pageUrl) {
    const res = await fetch('/api/tiktok-video', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: pageUrl.trim() })
    });
    const contentType = (res.headers.get('content-type') || '').toLowerCase();

    if (!res.ok) {
        let code = 'fetch_failed';
        try {
            const errBody = await res.json();
            if (errBody?.error) code = errBody.error;
        } catch (_) { /* not json */ }
        throw Object.assign(new Error(code), { code });
    }

    if (contentType.includes('json') || contentType.includes('text/html')) {
        throw Object.assign(new Error('fetch_failed'), { code: 'fetch_failed' });
    }

    const blob = await res.blob();
    if (blob.size < 512 && contentType.includes('text')) {
        throw Object.assign(new Error('fetch_failed'), { code: 'fetch_failed' });
    }

    return {
        blob,
        duration: parseFloat(res.headers.get('X-Video-Duration') || 'NaN')
    };
}

async function downloadTikTokBlobDirect(pageUrl) {
    const meta = await resolveTikTokViaTikwm(pageUrl);
    const proxyUrl = `/api/media-download?url=${encodeURIComponent(meta.videoUrl)}`;
    const videoRes = await fetch(proxyUrl);
    if (!videoRes.ok) {
        throw Object.assign(new Error('video_download'), { code: 'video_download' });
    }
    return { blob: await videoRes.blob(), duration: meta.duration };
}

async function downloadTikTokVideoBlob(pageUrl) {
    if (!isTikTokPageUrl(pageUrl)) {
        throw Object.assign(new Error('invalid_url'), { code: 'invalid_url' });
    }
    return await downloadTikTokBlobDirect(pageUrl);
}

async function getBlobVideoDurationSec(blob) {
    const url = URL.createObjectURL(blob);
    try {
        const video = document.createElement('video');
        video.preload = 'metadata';
        video.muted = true;
        video.playsInline = true;
        video.setAttribute('playsinline', '');
        video.setAttribute('webkit-playsinline', '');
        video.src = url;
        await new Promise((resolve, reject) => {
            video.onloadedmetadata = () => resolve();
            video.onerror = () => reject(new Error('metadata'));
        });
        return video.duration;
    } finally {
        URL.revokeObjectURL(url);
    }
}

function loadExternalScript(src) {
    return new Promise((resolve, reject) => {
        const existing = document.querySelector(`script[data-trim-src="${src}"]`);
        if (existing) {
            if (existing.dataset.loaded === '1') resolve();
            else existing.addEventListener('load', () => resolve(), { once: true });
            return;
        }
        const script = document.createElement('script');
        script.src = src;
        script.async = true;
        script.dataset.trimSrc = src;
        script.onload = () => {
            script.dataset.loaded = '1';
            resolve();
        };
        script.onerror = () => reject(new Error(`script_load_failed:${src}`));
        document.head.appendChild(script);
    });
}

function guessVideoExt(blob, fallback = 'mp4') {
    const type = String(blob?.type || '').toLowerCase();
    if (type.includes('quicktime') || type.includes('mov')) return 'mov';
    if (type.includes('webm')) return 'webm';
    if (type.includes('3gp')) return '3gp';
    if (type.includes('mp4') || type.includes('mpeg')) return 'mp4';
    const name = blob?.name || '';
    const match = name.match(/\.([a-z0-9]+)$/i);
    if (match) return match[1].toLowerCase();
    return fallback;
}

function blobFromFfmpegOutput(outData, mimeType = 'video/mp4') {
    const bytes = outData instanceof Uint8Array ? outData : new Uint8Array(outData);
    return new Blob([bytes], { type: mimeType });
}

async function trimVideoBlobNative(blob, maxSec) {
    if (typeof MediaRecorder === 'undefined') {
        throw new Error('mediarecorder_unsupported');
    }

    const url = URL.createObjectURL(blob);
    try {
        const video = document.createElement('video');
        video.playsInline = true;
        video.setAttribute('playsinline', '');
        video.setAttribute('webkit-playsinline', '');
        video.preload = 'auto';
        video.src = url;

        await new Promise((resolve, reject) => {
            video.onloadedmetadata = () => resolve();
            video.onerror = () => reject(new Error('metadata'));
        });

        const captureStream = video.captureStream || video.mozCaptureStream;
        if (!captureStream) throw new Error('capture_stream_unsupported');

        const mimeCandidates = [
            'video/mp4;codecs="avc1.42E01E,mp4a.40.2"',
            'video/mp4',
            'video/webm;codecs=vp9,opus',
            'video/webm;codecs=vp8,opus',
            'video/webm'
        ];
        const mimeType = mimeCandidates.find((m) => MediaRecorder.isTypeSupported(m));
        if (!mimeType) throw new Error('mediarecorder_mime_unsupported');

        const stream = captureStream.call(video);
        const recorder = new MediaRecorder(stream, {
            mimeType,
            videoBitsPerSecond: 2800000,
            audioBitsPerSecond: 128000
        });
        const chunks = [];

        const outBlob = await new Promise((resolve, reject) => {
            let finished = false;
            const finish = (err, result) => {
                if (finished) return;
                finished = true;
                try { video.pause(); } catch (_) { /* ignore */ }
                stream.getTracks().forEach((track) => {
                    try { track.stop(); } catch (_) { /* ignore */ }
                });
                if (err) reject(err);
                else resolve(result);
            };

            recorder.ondataavailable = (event) => {
                if (event.data && event.data.size > 0) chunks.push(event.data);
            };
            recorder.onerror = (event) => finish(event.error || new Error('recorder_error'));
            recorder.onstop = () => {
                if (!chunks.length) {
                    finish(new Error('empty_recording'));
                    return;
                }
                finish(null, new Blob(chunks, { type: mimeType.split(';')[0] }));
            };

            recorder.start(200);
            video.currentTime = 0;
            const startPlayback = async () => {
                try {
                    await video.play();
                } catch (playErr) {
                    video.muted = true;
                    await video.play();
                }
            };
            startPlayback().catch((playErr) => finish(playErr));

            const stopMs = Math.max(500, Math.ceil(maxSec * 1000) + 250);
            setTimeout(() => {
                try { recorder.stop(); } catch (stopErr) { finish(stopErr); }
            }, stopMs);
        });

        if (!outBlob || outBlob.size < 1024) {
            throw new Error('empty_recording');
        }
        return { blob: outBlob, trimmed: true };
    } finally {
        URL.revokeObjectURL(url);
    }
}

async function loadFfmpegForTrim() {
    if (!_ffmpegLoadPromise) {
        _ffmpegLoadPromise = (async () => {
            const ffmpegScript = 'https://cdn.jsdelivr.net/npm/@ffmpeg/ffmpeg@0.12.10/dist/umd/ffmpeg.js';
            const utilScript = 'https://cdn.jsdelivr.net/npm/@ffmpeg/util@0.12.1/dist/umd/index.js';
            await loadExternalScript(ffmpegScript);
            await loadExternalScript(utilScript);

            const FFmpeg = window.FFmpegWASM?.FFmpeg;
            const fetchFile = window.FFmpegUtil?.fetchFile;
            const toBlobURL = window.FFmpegUtil?.toBlobURL;
            if (!FFmpeg || !fetchFile || !toBlobURL) {
                throw new Error('ffmpeg_umd_unavailable');
            }

            const ffmpeg = new FFmpeg();
            ffmpeg.on('log', ({ message }) => console.log('[ffmpeg]', message));

            const coreBase = 'https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.10/dist/umd';
            await ffmpeg.load({
                coreURL: await toBlobURL(`${coreBase}/ffmpeg-core.js`, 'text/javascript'),
                wasmURL: await toBlobURL(`${coreBase}/ffmpeg-core.wasm`, 'application/wasm')
            });
            return { ffmpeg, fetchFile };
        })().catch((err) => {
            _ffmpegLoadPromise = null;
            throw err;
        });
    }
    return _ffmpegLoadPromise;
}

async function trimVideoBlobWithFfmpeg(blob, maxSec, options = {}) {
    const { onProgress } = options;
    onProgress?.('loading_ffmpeg');
    const { ffmpeg, fetchFile } = await loadFfmpegForTrim();
    onProgress?.('trimming', { sec: maxSec });

    const ext = guessVideoExt(blob);
    const inputName = `trim_in.${ext}`;
    const outputName = 'trim_out.mp4';
    await ffmpeg.writeFile(inputName, await fetchFile(blob));

    const encodeAttempts = [
        ['-y', '-i', inputName, '-t', String(maxSec), '-c', 'copy', '-movflags', '+faststart', outputName],
        ['-y', '-i', inputName, '-t', String(maxSec), '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', outputName],
        ['-y', '-i', inputName, '-t', String(maxSec), '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', '-an', '-movflags', '+faststart', outputName],
        ['-y', '-i', inputName, '-t', String(maxSec), '-c:v', 'mpeg4', '-q:v', '5', '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', outputName],
        ['-y', '-i', inputName, '-t', String(maxSec), '-c:v', 'mpeg4', '-q:v', '5', '-an', '-movflags', '+faststart', outputName]
    ];

    let lastErr = null;
    for (const args of encodeAttempts) {
        try {
            try { await ffmpeg.deleteFile(outputName); } catch (_) { /* ignore */ }
            await ffmpeg.exec(args);
            const outData = await ffmpeg.readFile(outputName);
            if (!outData || (outData.byteLength != null && outData.byteLength < 1024)) {
                throw new Error('ffmpeg_empty_output');
            }
            try {
                await ffmpeg.deleteFile(inputName);
                await ffmpeg.deleteFile(outputName);
            } catch (_) { /* ignore */ }
            return {
                blob: blobFromFfmpegOutput(outData, 'video/mp4'),
                trimmed: true
            };
        } catch (attemptErr) {
            lastErr = attemptErr;
            console.warn('[VideoTrim] ffmpeg attempt failed:', args.join(' '), attemptErr);
        }
    }

    try {
        await ffmpeg.deleteFile(inputName);
        await ffmpeg.deleteFile(outputName);
    } catch (_) { /* ignore */ }
    throw lastErr || new Error('ffmpeg_all_attempts_failed');
}

async function trimVideoBlobToMaxSec(blob, maxSec = MAX_VIDEO_DURATION_SEC, options = {}) {
    let duration;
    try {
        duration = await getBlobVideoDurationSec(blob);
    } catch (_) {
        duration = Infinity;
    }
    if (isFinite(duration) && duration <= maxSec + 0.15) {
        return { blob, trimmed: false };
    }

    const trimStrategies = prefersServerSideTrim()
        ? []
        : [
            {
                name: 'native',
                run: () => withTrimTimeout(trimVideoBlobNative(blob, maxSec), 45000, 'native')
            },
            {
                name: 'ffmpeg',
                run: () => withTrimTimeout(trimVideoBlobWithFfmpeg(blob, maxSec, options), 120000, 'ffmpeg')
            }
        ];

    if (!trimStrategies.length) {
        throw new Error('server_trim_required');
    }

    let lastErr = null;
    for (const strategy of trimStrategies) {
        try {
            console.log(`[VideoTrim] trying ${strategy.name}...`);
            return await strategy.run();
        } catch (err) {
            lastErr = err;
            console.warn(`[VideoTrim] ${strategy.name} failed:`, err);
        }
    }
    throw lastErr || new Error('trim_failed');
}

async function prepareVideoFileForSubmit(videoFile, maxSec, options = {}) {
    const { onProgress } = options;
    if (!videoFile) {
        throw Object.assign(new Error(t('modals.video_upload_required')), { code: 'no_video' });
    }

    let durationSec = await getVideoDurationSeconds(videoFile);
    if (durationSec == null || !Number.isFinite(durationSec)) {
        throw Object.assign(new Error(t('modals.video_upload_required')), { code: 'metadata' });
    }
    if (durationSec <= maxSec + 0.15) {
        return { file: videoFile, trimmed: false, durationSec };
    }

    if (prefersServerSideTrim()) {
        onProgress?.('server_trim', { sec: maxSec });
        return {
            file: videoFile,
            trimmed: false,
            durationSec: maxSec,
            serverTrimPending: true
        };
    }

    onProgress?.('trimming', { sec: maxSec });
    let trimmedResult;
    try {
        trimmedResult = await trimVideoBlobToMaxSec(videoFile, maxSec, { onProgress });
    } catch (trimErr) {
        console.error('[VideoTrim] failed:', trimErr);
        throw Object.assign(new Error(t('modals.tiktok_trim_failed')), { code: 'trim_failed' });
    }

    const outType = trimmedResult.blob.type || 'video/mp4';
    const outExt = outType.includes('webm') ? '.webm' : outType.includes('quicktime') ? '.mov' : '.mp4';
    const outFile = new File([trimmedResult.blob], `trimmed_${Date.now()}${outExt}`, { type: outType });
    let outDuration = await getVideoDurationSeconds(outFile);
    if (outDuration == null || !Number.isFinite(outDuration) || outDuration > maxSec + 0.15) {
        outDuration = maxSec;
    }
    return {
        file: outFile,
        trimmed: true,
        durationSec: outDuration
    };
}

async function fetchUrlAsVideoFile(url, fileName = 'reference_video.mp4') {
    const res = await fetch(url);
    if (!res.ok) {
        throw Object.assign(new Error(t('modals.tiktok_fetch_failed')), { code: 'fetch_failed' });
    }
    const blob = await res.blob();
    if (blob.size > MAX_VIDEO_FILE_BYTES) {
        throw Object.assign(new Error(t('modals.video_size_limit')), { code: 'size_limit' });
    }
    return new File([blob], fileName, { type: blob.type || 'video/mp4' });
}

function buildTrimProgressHandler(maxSec) {
    return (phase, params) => {
        if (phase === 'loading_ffmpeg') {
            updateVideoTrimOverlay('modals.video_trim_loading');
        } else if (phase === 'server_trim') {
            updateVideoTrimOverlay('modals.video_server_trim_pending', params || { sec: maxSec });
        } else if (phase === 'trimming') {
            updateVideoTrimOverlay('modals.video_trimming', params || { sec: maxSec });
        } else if (phase === 'fetching') {
            updateVideoTrimOverlay('modals.tiktok_fetch_on_submit');
        }
    };
}

async function prepareReferenceVideoForSubmit({ videoFile, templateUrl, useLibrary, maxSec, onProgress }) {
    let sourceFile = videoFile;
    let fromLibrary = false;

    if (!sourceFile && useLibrary && templateUrl) {
        onProgress?.('fetching');
        sourceFile = await fetchUrlAsVideoFile(templateUrl, 'template_video.mp4');
        fromLibrary = true;
    }

    if (!sourceFile) {
        throw Object.assign(new Error(t('modals.video_upload_required')), { code: 'no_video' });
    }

    const prepared = await prepareVideoFileForSubmit(sourceFile, maxSec, { onProgress });
    return { ...prepared, fromLibrary };
}

async function applyTikTokVideoFromUrl(pageUrl, options = {}) {
    const { onProgress } = options;
    onProgress?.('fetching');
    const { blob: initialBlob, duration: metaDuration } = await downloadTikTokVideoBlob(pageUrl);
    let blob = initialBlob;
    if (blob.size > MAX_VIDEO_FILE_BYTES) {
        throw Object.assign(new Error(t('modals.video_size_limit')), { code: 'size_limit' });
    }

    let blobDuration = metaDuration;
    if (!isFinite(blobDuration)) {
        try {
            blobDuration = await getBlobVideoDurationSec(blob);
        } catch (_) {
            blobDuration = MAX_VIDEO_DURATION_SEC + 1;
        }
    }
    const tiktokMaxSec = getMaxVideoSecForSelectedModel();
    const needsTrim = blobDuration > tiktokMaxSec + 0.15;

    if (needsTrim && !prefersServerSideTrim()) {
        try {
            const trimmed = await trimVideoBlobToMaxSec(blob, tiktokMaxSec, { onProgress });
            blob = trimmed.blob;
        } catch (trimErr) {
            console.error('[TikTok] trim failed:', trimErr);
            throw Object.assign(new Error(t('modals.tiktok_trim_failed')), { code: 'trim_failed' });
        }
    } else if (needsTrim && prefersServerSideTrim()) {
        onProgress?.('server_trim', { sec: tiktokMaxSec });
    }

    const file = new File([blob], 'tiktok_video.mp4', { type: 'video/mp4' });
    const fileInput = document.getElementById('file-video');
    if (!fileInput) throw Object.assign(new Error(t('common.error')), { code: 'fetch_failed' });

    const dt = new DataTransfer();
    dt.items.add(file);
    fileInput.files = dt.files;

    const templateInput = document.getElementById('selected-template-url');
    if (templateInput) templateInput.value = '';
    window.currentVideoSource = 'upload';

    renderVideoFilePreview('preview-tiktok-video-container', file, {
        changeKey: 'modals.tiktok_pick_another',
        maxDurationSec: tiktokMaxSec,
        onChange: () => {
            fileInput.value = '';
            const tiktokPreview = document.getElementById('preview-tiktok-video-container');
            if (tiktokPreview) {
                tiktokPreview.innerHTML = '';
                syncUploadZonePreviewState(tiktokPreview);
            }
            document.getElementById('tiktok-video-url')?.focus();
        }
    });

    return { file, trimmed: needsTrim };
}

window.fetchTikTokVideo = async () => {
    const input = document.getElementById('tiktok-video-url');
    const btn = document.getElementById('tiktok-fetch-btn');
    const pageUrl = input?.value?.trim();
    if (!pageUrl) {
        return showToast(t('modals.tiktok_url_required'));
    }

    const prevBtnText = btn?.textContent;
    if (btn) {
        btn.disabled = true;
        btn.textContent = t('modals.tiktok_fetching');
    }
    showToast(t('modals.tiktok_fetching'));

    try {
        const tiktokMaxSec = getMaxVideoSecForSelectedModel();
        const { trimmed } = await applyTikTokVideoFromUrl(pageUrl, {
            onProgress: (phase, params) => {
                if (phase === 'trimming' && btn) {
                    btn.textContent = t('modals.video_trimming', params || { sec: tiktokMaxSec });
                }
                if (phase === 'trimming') {
                    showToast(t('modals.video_trimming', params || { sec: tiktokMaxSec }));
                }
            }
        });
        showToast(trimmed
            ? t('modals.tiktok_fetch_trimmed', { sec: tiktokMaxSec })
            : t('modals.tiktok_fetch_success'));
    } catch (e) {
        console.error('[TikTok] fetch failed:', e);
        showToast(e.code ? tiktokErrorMessage(e.code) : (e.message || t('modals.tiktok_fetch_failed')));
    } finally {
        if (btn) {
            btn.disabled = false;
            if (prevBtnText) btn.textContent = prevBtnText;
            else applyTranslations();
        }
    }
};

function renderVideoFilePreview(containerId, file, options = {}) {
    const container = document.getElementById(containerId);
    if (!container || !file) return;

    const maxDurationSec = options.maxDurationSec ?? getMaxVideoSecForSelectedModel();

    if (file.size > MAX_VIDEO_FILE_BYTES) {
        showToast(t('modals.video_size_limit'));
        if (options.inputId) {
            const input = document.getElementById(options.inputId);
            if (input) input.value = '';
        }
        container.innerHTML = '';
        syncUploadZonePreviewState(container);
        return;
    }

    const probe = document.createElement('video');
    probe.preload = 'metadata';
    probe.muted = true;
    probe.playsInline = true;
    const probeUrl = URL.createObjectURL(file);
    probe.onloadedmetadata = () => {
        const duration = probe.duration;
        URL.revokeObjectURL(probeUrl);
        kalingSelectedDurationSec = duration;
        updateFirstOrderUI();
        container.innerHTML = '';
        const previewVideo = document.createElement('video');
        const previewUrl = URL.createObjectURL(file);
        previewVideo.src = previewUrl;
        previewVideo.muted = true;
        previewVideo.loop = true;
        previewVideo.playsInline = true;
        previewVideo.setAttribute('playsinline', '');
        previewVideo.setAttribute('webkit-playsinline', '');
        previewVideo.preload = 'metadata';
        previewVideo.controls = false;
        previewVideo.disablePictureInPicture = true;
        previewVideo.style.width = '100%';
        previewVideo.style.height = '100%';
        previewVideo.style.objectFit = 'cover';
        previewVideo.style.borderRadius = '8px';
        previewVideo.addEventListener('loadeddata', () => {
            try {
                previewVideo.pause();
                previewVideo.currentTime = 0;
            } catch (_) { /* ignore */ }
        }, { once: true });

        container.appendChild(previewVideo);

        if (duration > 30.15) {
            const badge = document.createElement('div');
            badge.className = 'video-trim-hint-badge';
            badge.style.cssText = 'background:rgba(220,38,38,0.15);color:#ef4444;border:1px solid rgba(220,38,38,0.4);';
            badge.textContent = t('modals.video_too_long', { sec: 30 });
            container.appendChild(badge);
            const sb = document.getElementById('submit-btn');
            if (sb) sb.disabled = true;
        } else if (duration > maxDurationSec + 0.15) {
            const badge = document.createElement('div');
            badge.className = 'video-trim-hint-badge';
            badge.style.cssText = 'background:rgba(245,158,11,0.15);color:#f59e0b;border:1px solid rgba(245,158,11,0.4);';
            badge.textContent = t('modals.video_auto_trim_hint', { dur: Math.round(duration), sec: maxDurationSec });
            container.appendChild(badge);
            const sb = document.getElementById('submit-btn');
            if (sb) sb.disabled = false;
        } else {
            const sb = document.getElementById('submit-btn');
            if (sb) sb.disabled = false;
        }

        if (options.onChange) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'preview-change-btn btn-primary order-upload-btn';
            btn.textContent = t(options.changeKey || 'modals.video_change');
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                options.onChange();
            });
            container.appendChild(btn);
        } else if (options.inputId) {
            appendPreviewChangeButton(container, options.inputId, options.changeKey || 'modals.video_change');
        }

        syncUploadZonePreviewState(container);
    };
    probe.onerror = () => {
        URL.revokeObjectURL(probeUrl);
        showToast(t('modals.tiktok_fetch_failed'));
    };
    probe.src = probeUrl;
}

window.handlePreview = (input, containerId) => {
    const container = document.getElementById(containerId);
    if (!container) return;

    const previewMeta = {
        'preview-char-container': { inputId: 'file-char', changeKey: 'modals.char_change' },
        'preview-video-container': { inputId: 'file-video', changeKey: 'modals.video_change' }
    };
    const meta = previewMeta[containerId] || { inputId: input.id, changeKey: 'modals.char_change' };

    const file = input.files[0];
    if (!file) {
        container.innerHTML = '';
        syncUploadZonePreviewState(container);
        return;
    }

    container.innerHTML = '';

    if (file.type.startsWith('image/')) {
        if (file.size > MAX_CHAR_FILE_BYTES) {
            showToast(t('modals.char_size_limit'));
            input.value = '';
            syncUploadZonePreviewState(container);
            return;
        }
        const img = document.createElement('img');
        img.src = URL.createObjectURL(file);
        img.style.width = '100%';
        img.style.height = '100%';
        img.style.objectFit = 'cover';
        img.style.borderRadius = '8px';
        img.onload = () => URL.revokeObjectURL(img.src);
        container.appendChild(img);
        appendPreviewChangeButton(container, meta.inputId, meta.changeKey);
        syncUploadZonePreviewState(container);
    } else if (file.type.startsWith('video/')) {
        renderVideoFilePreview(containerId, file, {
            inputId: meta.inputId,
            changeKey: meta.changeKey,
            maxDurationSec: getMaxVideoSecForSelectedModel()
        });
    }
};

// --- File Upload Helper ---
// Tên file của khách (đặc biệt video tải từ TikTok/SnapTik) thường chứa các ký tự
// gây hỏng URL như '#', '?', '&', '+', '%' và khoảng trắng đã URL-encode sẵn.
// Khi qua nhiều bước encode/decode (client -> worker -> Firestore -> render HTML)
// chỉ cần một '%23' bị "hoàn nguyên" về '#' là toàn bộ phần đuôi tên file sẽ bị
// browser xem như URL fragment -> không tới được worker -> R2 trả "file không tồn tại".
// Vì vậy: làm sạch tên file NGAY TRƯỚC khi ghép vào key upload.
function sanitizeUploadFileName(name) {
    if (!name) return 'file';

    // Tách extension (.mp4, .png, ...)
    const lastDot = name.lastIndexOf('.');
    let base = lastDot > 0 ? name.substring(0, lastDot) : name;
    let ext  = lastDot > 0 ? name.substring(lastDot)   : '';

    // Chuẩn hoá Unicode về NFC để Vietnamese ký tự không bị tách combining marks lẻ
    try { base = base.normalize('NFC'); ext = ext.normalize('NFC'); } catch (_) {}

    // Loại bỏ ký tự gây lỗi URL/đường dẫn:
    //   # ? & + % = ' " < > \ : ; | * \r \n \t / và các whitespace -> '_'
    const dangerous = /[#?&+%='"<>\\:;|*\/\s\u0000-\u001F\u007F]+/g;
    base = base.replace(dangerous, '_');
    ext  = ext.replace(/[^A-Za-z0-9.]/g, '');

    // Gộp dấu '_' liên tiếp & cắt '_' ở 2 đầu
    base = base.replace(/_+/g, '_').replace(/^_+|_+$/g, '');

    // Giới hạn độ dài tên file để tránh key R2 quá dài
    if (base.length > 80) base = base.substring(0, 80);
    if (!base) base = 'file';

    return base + ext;
}

async function uploadFile(file, folder) {
    let workerUrl = "https://motionai-upload-api.traderfinn0312.workers.dev";
    if (workerUrl.endsWith('/')) workerUrl = workerUrl.slice(0, -1);

    const safeName = sanitizeUploadFileName(file.name);
    const fileName = `${folder}/${Date.now()}_${safeName}`;
    const fetchUrl = `${workerUrl}/?file=${encodeURIComponent(fileName)}&t=${Date.now()}`;

    const progressVal = document.getElementById('progress-val');

    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', fetchUrl, true);
        xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');

        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
                const percent = Math.round((e.loaded / e.total) * 100);
                if (progressVal) progressVal.innerText = percent;
                console.log(`Progress: ${percent}%`);
            }
        };

        xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    const data = JSON.parse(xhr.responseText);
                    if (data.url) {
                        resolve(data.url);
                    } else {
                        reject(new Error(t('upload.error_no_url')));
                    }
                } catch (e) {
                    reject(new Error(t('upload.error_bad_response')));
                }
            } else {
                reject(new Error(t('upload.error_server_rejected', { status: xhr.status })));
            }
        };

        xhr.onerror = () => {
            reject(new Error(t('upload.error_network')));
        };

        xhr.send(file);
    });
}

// --- Form Submissions ---
async function setupEventListeners() {
    // Model Selection change cost
    document.querySelectorAll('input[name="model-type"]').forEach(radio => {
        radio.addEventListener('change', () => {
            updateFirstOrderUI();
            const fileInput = document.getElementById('file-video');
            const existing = fileInput?.files?.[0];
            if (existing?.type?.startsWith('video/') && window.currentVideoSource === 'upload') {
                renderVideoFilePreview('preview-video-container', existing, {
                    inputId: 'file-video',
                    changeKey: 'modals.video_change',
                    maxDurationSec: getMaxVideoSecForSelectedModel()
                });
            }
        });
    });

    // Topup Form removed for automated flow
    // (Admin updates coins in Firestore -> Real-time listener detects change -> UI auto-closes)

    document.getElementById('tiktok-video-url')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            window.fetchTikTokVideo();
        }
    });

    // Order Form (Updated for File Upload & New Pricing)
    const orderForm = document.getElementById('order-form');
    if (orderForm) {
        orderForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            if (!currentUser) {
                promptGoogleSignIn();
                showToast(t('common.toast_login_required'));
                return;
            }

            if (window.__minClientVersion != null && isClientOlderThan(APP_CLIENT_VERSION, window.__minClientVersion)) {
                showToast(t('modals.client_outdated_banner'));
                return;
            }

            if (normalizeCoins(window.__currentUserData?.coins) < 1) {
                promptInsufficientCoinsAndTopup();
                return;
            }

            const submitBtn = document.getElementById('order-submit-btn');
            const progressDiv = document.getElementById('upload-progress');

            try {
                const charFile = document.getElementById('file-char').files[0];
                let videoFile = document.getElementById('file-video')?.files?.[0];
                const templateUrl = document.getElementById('selected-template-url')?.value || '';
                const tiktokUrl = document.getElementById('tiktok-video-url')?.value?.trim() || '';
                let modelKeySelected = getSelectedModelKey();
                let modelIdOverride = null;

                if (!charFile) {
                    const charZone = document.querySelector('#file-char')?.closest('.upload-zone');
                    if (charZone) {
                        document.querySelectorAll('#order-modal .modal-body, #order-modal .modal-content, #order-modal').forEach(el => el.scrollTo({ top: 0, behavior: 'smooth' }));
                        charZone.classList.add('highlight-pulse');
                        setTimeout(() => charZone.classList.remove('highlight-pulse'), 2000);
                    }
                    return showToast(t('modals.char_upload_required'));
                }

                if (window.currentVideoSource === 'library' && !templateUrl) {
                    return showToast(t('modals.video_upload_required'));
                }

                if (!videoFile && !templateUrl && tiktokUrl) {
                    if (!isTikTokPageUrl(tiktokUrl)) {
                        return showToast(t('modals.tiktok_url_invalid'));
                    }
                    const tiktokMaxSec = getMaxVideoSecForSelectedModel();
                    submitBtn.disabled = true;
                    showVideoTrimOverlay('modals.tiktok_fetch_on_submit');
                    try {
                        const result = await applyTikTokVideoFromUrl(tiktokUrl, {
                            onProgress: (phase, params) => {
                                if (phase === 'loading_ffmpeg') {
                                    updateVideoTrimOverlay('modals.video_trim_loading');
                                } else if (phase === 'trimming') {
                                    updateVideoTrimOverlay('modals.video_trimming', params || { sec: tiktokMaxSec });
                                } else if (phase === 'fetching') {
                                    updateVideoTrimOverlay('modals.tiktok_fetch_on_submit');
                                }
                            }
                        });
                        videoFile = result.file;
                    } catch (tiktokErr) {
                        console.error('[TikTok] auto fetch on submit:', tiktokErr);
                        hideVideoTrimOverlay();
                        submitBtn.disabled = false;
                        updateFirstOrderUI();
                        showToast(tiktokErr.code ? tiktokErrorMessage(tiktokErr.code) : (tiktokErr.message || t('modals.tiktok_fetch_failed')));
                        return;
                    }
                }

                if (window.currentVideoSource === 'upload' && !videoFile) {
                    return showToast(t('modals.video_upload_required'));
                }

                let kalingDurationSec = kalingSelectedDurationSec;
                let maxSec = getMaxVideoSecForModel(modelKeySelected);
                const useLibrary = window.currentVideoSource === 'library' && !!templateUrl;
                if (videoFile) {
                    kalingDurationSec = await getVideoDurationSeconds(videoFile);
                } else if (useLibrary) {
                    kalingDurationSec = await getVideoDurationFromUrl(templateUrl);
                }
                if (kalingDurationSec == null || !Number.isFinite(kalingDurationSec)) {
                    return showToast(t('modals.video_upload_required'));
                }

                // Tự động hạ mốc thời lượng nếu video tải lên ngắn hơn mốc khách chọn (tránh bị tính giá cao hơn)
                if (DURATION_MODEL_KEYS.includes(modelKeySelected)) {
                    let fittedKey = 'ad30';
                    if (kalingDurationSec <= 10.15) fittedKey = 'ad10';
                    else if (kalingDurationSec <= 15.15) fittedKey = 'ad15';
                    else if (kalingDurationSec <= 20.15) fittedKey = 'ad20';
                    else if (kalingDurationSec <= 25.15) fittedKey = 'ad25';
                    const fittedMaxSec = getMaxVideoSecForModel(fittedKey);
                    if (fittedMaxSec < maxSec) {
                        console.log(`🔄 Auto downgraded ${modelKeySelected} (${maxSec}s) -> ${fittedKey} (${fittedMaxSec}s) due to video ${kalingDurationSec.toFixed(2)}s`);
                        modelKeySelected = fittedKey;
                        maxSec = fittedMaxSec;
                    }
                }

                const longVideo = kalingDurationSec > 30.15;
                if (longVideo) {
                    alert(t('modals.video_too_long', { sec: 30 }));
                    resetOrderSubmitUi(submitBtn, progressDiv);
                    return;
                }

                kalingSelectedDurationSec = kalingDurationSec;
                updateFirstOrderUI();

                // Kiểm tra lại lần cuối trước khi upload
                if (charFile.size > MAX_CHAR_FILE_BYTES) {
                    resetOrderSubmitUi(submitBtn, progressDiv);
                    return showToast(t('modals.char_size_limit'));
                }
                if (window.currentVideoSource === 'upload' && videoFile && videoFile.size > MAX_VIDEO_FILE_BYTES) {
                    resetOrderSubmitUi(submitBtn, progressDiv);
                    return showToast(t('modals.video_size_limit'));
                }

                submitBtn.disabled = true;
                showVideoTrimOverlay('modals.order_uploading_char');

                // 1. Check coins first via fresh Supabase profile before uploading media
                const freshUser = await window.kalingApi.getUserProfile(currentUser.uid);
                if (!freshUser) throw new Error('Không tìm thấy tài khoản Kaling');
                const modelKey = modelKeySelected;
                const serviceType = document.querySelector('input[name="service-type"]:checked').value;
                let model = normalizeOrderCost({ ...localizedModel(modelKey) });
                if (modelIdOverride) model.modelId = modelIdOverride;

                if (modelKey === ROBONEO_TRIAL.modelKey && !isRoboneoTrialEligible(freshUser)) {
                    throw t('modals.roboneo_trial_expired');
                }
                if (modelKey === ROBONEO_TRIAL.modelKey && Number(model.cost) !== ROBONEO_TRIAL.cost) {
                    throw t('modals.roboneo_trial_expired');
                }
                if (normalizeCoins(freshUser.coins) < model.cost) {
                    throw t('modals.insufficient_coins_title');
                }
                if (!Number.isFinite(Number(model.cost)) || Number(model.cost) < 1) {
                    throw t('modals.video_upload_required');
                }

                console.log("Starting process");
                updateVideoTrimOverlay('modals.order_uploading_char');

                console.log("📤 Đang tải ảnh nhân vật...");
                const charUrl = await uploadFile(charFile, "characters");

                let videoUrl = "";
                if (window.currentVideoSource === 'library') {
                    videoUrl = document.getElementById('selected-template-url').value;
                    if (!videoUrl) throw new Error(t('modals.template_required'));
                    console.log("🔗 Sử dụng video mẫu từ thư viện:", videoUrl);
                } else {
                    updateVideoTrimOverlay('modals.order_uploading_video');
                    console.log("📤 Đang tải video tham chiếu...");
                    videoUrl = await uploadFile(videoFile, "motions");
                }

                updateVideoTrimOverlay('modals.order_creating');
                normalizeOrderCost(model);
                const aspectRatioEl = document.querySelector('input[name="aspect-ratio"]:checked');
                const aspectRatio = aspectRatioEl ? aspectRatioEl.value : '16:9';

                let orderId = '';
                try {
                    const rpcRes = await window.kalingApi.createOrderAtomic(
                        {
                            packageName: model.name,
                            modelId: String(model.modelId || ''),
                            renderProvider: model.renderProvider || "videoaieasy",
                            maxVideoSec: model.maxVideoSec || 15,
                            vaeDurationSec: model.vaeDurationSec || null,
                            vaeResolution: model.vaeResolution || '',
                            serviceType: serviceType,
                            serviceLabel: SERVICE_TYPE_MAP()[serviceType] || serviceType,
                            roboneoTrial: !!model.roboneoTrial,
                            clientVersion: APP_CLIENT_VERSION,
                            characterImageLink: charUrl,
                            referenceVideoLink: videoUrl,
                            aspectRatio: aspectRatio,
                            referer: 'web',
                        },
                        model.cost,
                        !!model.promo1Coin,
                        getLocalDayKey()
                    );
                    orderId = rpcRes?.order_id || '';
                    if (rpcRes?.remaining_coins != null && window.__currentUserData) {
                        window.__currentUserData.coins = Number(rpcRes.remaining_coins);
                        document.querySelectorAll('.coin-balance-text').forEach(el => el.innerText = formatCoinAmount(window.__currentUserData.coins));
                    }
                } catch (rpcErr) {
                    const msg = String(rpcErr?.message || rpcErr || '');
                    if (msg.includes('INSUFFICIENT_COINS')) {
                        throw t('modals.insufficient_coins_title');
                    }
                    if (msg.includes('PROMO_QUOTA_EXCEEDED')) {
                        throw t('modals.promo1coin_daily_limit');
                    }
                    throw rpcErr;
                }

                showToast(t('common.toast_order_created'));
                closeModal('order-modal');

                const serviceLabelPixel = SERVICE_TYPE_MAP()[serviceType] || serviceType;
                if (typeof ttq !== 'undefined') {
                    ttq.track('PlaceAnOrder', {
                        value: model.cost * 1000,
                        currency: 'VND',
                        content_name: serviceLabelPixel,
                        content_id: orderId
                    });
                }

                trackMetaEvent('Lead', {
                    value: model.cost * 1000,
                    currency: 'VND',
                    content_name: serviceLabelPixel,
                    content_ids: [orderId],
                    content_category: 'ai_video_order'
                });

                logFirebaseEvent('generate_lead', {
                    value: model.cost * 1000,
                    currency: 'VND',
                    content_name: serviceLabelPixel
                });

                orderCount++;
                syncPromo1CoinState(FB_CACHE.myOrders || [], window.__currentUserData);
                updateFirstOrderUI();

                document.getElementById('order-form').reset();
                ['preview-char-container', 'preview-video-container', 'preview-tiktok-video-container'].forEach((id) => {
                    const el = document.getElementById(id);
                    if (el) {
                        el.innerHTML = '';
                        syncUploadZonePreviewState(el);
                    }
                });
                const tiktokInput = document.getElementById('tiktok-video-url');
                if (tiktokInput) tiktokInput.value = '';
                showDashboard();
                const serviceLabel = SERVICE_TYPE_MAP()[serviceType] || serviceType;
                const msg = `🚀 <b>ĐƠN HÀNG MỚI: ${serviceLabel.toUpperCase()}</b>\n\n` +
                    `🆔 Mã đơn: #${orderId}\n` +
                    `👤 Khách: ${escapeHTML(currentUser.displayName)}\n` +
                    `📧 Email: ${escapeHTML(currentUser.email)}\n` +
                    `🔧 Dịch vụ: <b>${serviceLabel}</b>\n` +
                    `📦 Gói: ${model.name}\n` +
                    `💰 Chi phí: ${model.cost} Coin\n` +
                    `🖼 <a href="${charUrl}">Xem ảnh nhân vật</a>\n` +
                    `📹 <a href="${videoUrl}">Xem video tham chiếu</a>`;
                sendTelegramMessage(msg);
            } catch (error) {
                console.error(error);
                if (error === t('modals.insufficient_coins_title')) {
                    promptInsufficientCoinsAndTopup();
                } else if (error === t('modals.promo1coin_daily_limit') || error === t('modals.promo1coin_max_reached')) {
                    showToast(error);
                    syncPromo1CoinState(FB_CACHE.myOrders || [], window.__currentUserData);
                    updateFirstOrderUI();
                } else {
                    showToast(t('common.error') + ": " + error);
                }
            } finally {
                hideVideoTrimOverlay();
                submitBtn.disabled = false;
                const mainTextOuter = submitBtn.querySelector('[data-i18n="hero.cta_create"]');
                if (mainTextOuter) mainTextOuter.innerText = t('hero.cta_create');
                updateFirstOrderUI();
                progressDiv.style.display = 'none';
            }
        });
    }
}

// --- Data Loading (Real-time) ---
// [TỐI ƯU] Tách subscribe & render. Subscribe chỉ chạy 1 lần đầu (cache vào FB_CACHE.myOrders).
// Khi đổi ngôn ngữ hoặc cần re-render -> chỉ gọi renderMyOrders() (KHÔNG re-fetch / re-subscribe).
function loadMyOrders() {
    if (!currentUser || !window.kalingApi) return;

    // Đã có listener đang sống -> chỉ re-render từ cache, không re-subscribe
    if (fbHas('myOrders')) {
        renderMyOrders();
        return;
    }

    const grid = document.getElementById('my-orders-grid');

    if (grid) {
        grid.innerHTML = Array(4).fill(0).map(() => `
            <div class="order-card skeleton-card">
                <div class="skeleton" style="width:100%; aspect-ratio: 16/9; border-radius:12px;"></div>
                <div style="padding: 1rem;">
                    <div class="skeleton" style="width:60%; height:16px; margin-bottom:8px;"></div>
                    <div class="skeleton" style="width:40%; height:12px;"></div>
                </div>
            </div>
        `).join('');
    }

    fbSub('myOrders', window.kalingApi.subscribeMyOrders(currentUser.uid, (orders, changes) => {
        (changes || []).forEach(change => {
            if (change.type === 'modified' && change.doc) {
                const data = change.doc;
                const orderId = String(data.id || '').slice(-6).toUpperCase();
                const statusVN = STATUS_MAP()[data.status] || data.status;
                if (data.status === 'completed') {
                    showToast(t('notifications.order_completed', { id: orderId }));
                } else {
                    showToast(t('notifications.order_status_changed', { id: orderId, status: statusVN }));
                }
            }
        });

        FB_CACHE.myOrders = orders;
        orderCount = orders.length;
        syncPromo1CoinState(FB_CACHE.myOrders, window.__currentUserData);
        updateFirstOrderUI();
        renderMyOrders();
    }));
}

/** Ghi chú đơn hiển thị cho khách — không lộ engine render. */
function userFacingOrderNote(order) {
    const raw = (order && order.systemNote) || '';
    if (!raw) return '';
    return raw
        .replace(/\bXiaoYang\b/gi, 'hệ thống')
        .replace(/\bAidancing\b/gi, 'hệ thống')
        .replace(/\baidancing\.net\b/gi, 'hệ thống')
        .replace(/\bxiaoyang\.online\b/gi, 'hệ thống');
}

let _myOrdersLimit = 8;

window.loadMoreMyOrders = () => {
    _myOrdersLimit += 8;
    renderMyOrders();
};

function renderMyOrders() {
    const grid = document.getElementById('my-orders-grid');
    const countText = document.getElementById('orders-count-text');
    if (!grid) return;

    const docs = FB_CACHE.myOrders || [];

    if (docs.length === 0) {
        grid.innerHTML = `<div style="grid-column: 1/-1; text-align:center; opacity: 0.5; padding: 4rem 2rem; background: rgba(255,255,255,0.02); border-radius: 16px; border: 1px dashed var(--glass-border);">
            <div style="font-size: 3rem; margin-bottom: 1rem;">🎬</div>
            <div>${t('status.no_orders')}</div>
        </div>`;
        if (countText) countText.innerText = '';
        let btnContainer = document.getElementById('my-orders-load-more');
        if (btnContainer) btnContainer.innerHTML = '';
        return;
    }

    const sortedDocs = [...docs].sort((a, b) => {
        const timeA = a.createdAt?.seconds || 0;
        const timeB = b.createdAt?.seconds || 0;
        return timeB - timeA;
    });

    if (countText) countText.innerText = `${sortedDocs.length} Videos`;

    const visibleDocs = sortedDocs.slice(0, _myOrdersLimit);

    grid.innerHTML = visibleDocs.map(d => {
            const orderId = d.id.substring(d.id.length - 6).toUpperCase();
            const createdDateObj = safeToDate(d.createdAt);
            const date = createdDateObj ? createdDateObj.toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' }) : '...';
            const statusVN = STATUS_MAP()[d.status] || d.status;
            const isNew = createdDateObj && (Date.now() - createdDateObj.getTime() < 5 * 60 * 1000);
            const isCompleted = d.status === 'completed' || d.status === 'done';
            const finalResultLink = d.resultLink;

            const isPendingLong = d.status === 'pending' && createdDateObj && (Date.now() - createdDateObj.getTime() > 10 * 60 * 1000);
            const delayNote = isPendingLong ? `<div class="order-delay-note">${t('dashboard.delay_note')}</div>` : '';

            return `
                <div class="order-card ${isNew ? 'new-order-highlight' : ''}" onclick="${isCompleted && d.resultLink ? `window.playOrderVideo(event, '${d.resultLink}')` : `window.openUserOrderDetail('${d.id}')`}">
                    <div class="order-thumb-wrapper">
                        <img src="${d.characterImageLink}" class="order-thumb">
                        
                        ${isCompleted && d.resultLink ? `
                            <div class="play-button-overlay">
                                <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                            </div>
                        ` : ''}

                        <div class="order-status-overlay">
                            <span class="status-badge status-${d.status}">${statusVN}</span>
                        </div>
                        ${isNew ? '<span class="new-badge-float">NEW</span>' : ''}
                    </div>
                    <div class="order-info">
                        <div class="order-id-row">
                            <span class="order-id-text">#${orderId}</span>
                            <span class="order-date-text">${date}</span>
                        </div>
                        <div class="order-type-text">${d.serviceLabel || ''}</div>
                        ${delayNote}
                        ${userFacingOrderNote(d) ? `<div class="order-system-note">💬 ${escapeHTML(userFacingOrderNote(d))}</div>` : ''}
                        <div class="order-footer">
                            <div class="order-cost-tag">
                                <svg style="width: 12px; height: 12px;" viewBox="0 0 24 24" fill="none">
                                    <path d="M12 2L20.66 7V17L12 22L3.34 17V7L12 2Z" fill="url(#coin-gradient)" fill-opacity="0.2" stroke="url(#coin-gradient)" stroke-width="2"/>
                                    <path d="M12 6L17.2 9V15L12 18L6.8 15V9L12 6Z" fill="url(#coin-gradient)"/>
                                </svg>
                                <span>${d.costCoins}</span>
                            </div>
                            <div style="display: flex; gap: 8px; align-items: center;">
                                ${isCompleted && finalResultLink ? `
                                    <button type="button" class="order-download-btn" data-url="${escapeHTML(finalResultLink)}" data-name="${escapeHTML(`kaling_video_${orderId}.mp4`)}" data-mime="video/mp4" onclick="window.downloadMediaFromEl(event, this)">
                                        ${t('dashboard.download_btn')}
                                    </button>
                                ` : ''}
                                <button class="order-view-btn" onclick="event.stopPropagation(); window.openUserOrderDetail('${d.id}')">${t('dashboard.action_view_details')}</button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

    // Load More Button
    let btnContainer = document.getElementById('my-orders-load-more');
    if (!btnContainer) {
        btnContainer = document.createElement('div');
        btnContainer.id = 'my-orders-load-more';
        btnContainer.style.cssText = 'grid-column: 1 / -1; text-align: center; margin-top: 1.5rem;';
        grid.parentNode.appendChild(btnContainer);
    }

    if (sortedDocs.length > _myOrdersLimit) {
        btnContainer.innerHTML = `<button class="use-trend-btn" style="padding: 0.75rem 2.5rem; font-size: 0.95rem; border-radius: 24px; cursor: pointer;" onclick="window.loadMoreMyOrders()">${t('dashboard.load_more_orders')} (${visibleDocs.length}/${sortedDocs.length})</button>`;
    } else if (sortedDocs.length > 8) {
        btnContainer.innerHTML = `<div style="opacity: 0.5; font-size: 0.85rem; padding: 0.5rem;">${t('dashboard.all_orders_loaded')} (${sortedDocs.length})</div>`;
    } else {
        btnContainer.innerHTML = '';
    }
}


// [TỐI ƯU] Tách subscribe & render. Subscribe 1 lần, re-render miễn phí khi đổi ngôn ngữ.
function loadMyTopups() {
    if (!currentUser || !window.kalingApi) return;

    if (fbHas('myTopups')) {
        renderMyTopups();
        return;
    }

    const list = document.getElementById('my-topups-list');
    if (list) {
        list.innerHTML = Array(3).fill(0).map(() => `
            <tr>
                <td><div class="skeleton" style="width:100px; height:16px;"></div></td>
                <td><div class="skeleton" style="width:60px; height:16px;"></div></td>
                <td><div class="skeleton" style="width:40px; height:16px;"></div></td>
                <td><div class="skeleton" style="width:80px; height:20px; border-radius:10px;"></div></td>
                <td><div class="skeleton" style="width:100px; height:12px;"></div></td>
            </tr>
        `).join('');
    }

    fbSub('myTopups', window.kalingApi.subscribeMyTopups(currentUser.uid, (topups, changes) => {
        (changes || []).forEach(change => {
            if (change.type === 'modified' && change.doc) {
                const data = change.doc;
                if (data.status === 'approved') {
                    showToast(t('notifications.topup_approved', { pkg: data.packageName }));
                } else if (data.status === 'rejected') {
                    showToast(t('notifications.topup_rejected', { pkg: data.packageName }));
                }
            }
        });

        FB_CACHE.myTopups = topups;
        renderMyTopups();
        renderPricing();
    }));
}

function renderMyTopups() {
    const list = document.getElementById('my-topups-list');
    if (!list) return;

    const docs = FB_CACHE.myTopups || [];
    if (docs.length === 0) {
        list.innerHTML = `<tr><td colspan="5" style="text-align:center; opacity: 0.5; padding: 2rem;">${t('status.no_topups')}</td></tr>`;
        return;
    }

    const sortedDocs = [...docs].sort((a, b) => {
        const dateA = safeToDate(a.createdAt);
        const dateB = safeToDate(b.createdAt);
        const timeA = dateA ? dateA.getTime() : 0;
        const timeB = dateB ? dateB.getTime() : 0;
        return timeB - timeA;
    });

    list.innerHTML = sortedDocs.map(d => {
        const createdDateObj = safeToDate(d.createdAt);
        const date = createdDateObj ? createdDateObj.toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric' }) : '...';
        const statusVN = STATUS_MAP()[d.status] || d.status;
        return `
            <tr>
                <td>${d.packageName}</td>
                <td>${d.amount ? d.amount.toLocaleString() : 0}đ</td>
                <td>${formatCoinAmount(d.coins)}</td>
                <td><span class="status-badge status-${d.status}">${statusVN}</span></td>
                <td>${date}</td>
            </tr>
        `;
    }).join('');
}

window.saveQRImage = () => {
    const qrImg = document.getElementById('qr-code-img');
    if (!qrImg || !qrImg.src) return;

    // Create a temporary link
    const a = document.createElement('a');
    a.href = qrImg.src;
    a.download = `Kaling_QR_${Date.now()}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    showToast(t('payment.toast_qr_saved'));
};

window.saveQRImage = window.saveQRImage;

window.viewFullImage = (url) => {
    const modal = document.getElementById('image-viewer-modal');
    const img = document.getElementById('full-res-image');
    if (!modal || !img) return;
    img.src = url;
    modal.style.display = 'flex';
};

function checkMaintenance() {
    const now = new Date();
    const hour = now.getHours();
    const minute = now.getMinutes();
    const totalMinutes = hour * 60 + minute;

    // Maintenance from 00:30 to 07:00
    const maintenanceStart = 0 * 60 + 30; // 00:30
    const maintenanceEnd = 7 * 60; // 07:00

    const isMaintenance = totalMinutes >= maintenanceStart && totalMinutes < maintenanceEnd;

    const banner = document.getElementById('maintenance-banner');
    if (banner) {
        banner.style.display = isMaintenance ? 'flex' : 'none';
    }
}

// Check every minute
setInterval(checkMaintenance, 60000);

// Admin panel is now unified at https://aquaai.vn/admin?app=kaling

window.openUserOrderDetail = async (orderId) => {
    const d = await window.kalingApi.getOrderById(orderId);
    if (!d) return;
    const shortId = String(d.id || orderId).slice(-6).toUpperCase();
    const statusLabel = STATUS_MAP()[d.status] || d.status;

    // Timeline Steps logic
    const steps = ['pending', 'processing', 'completed'];
    const currentStepIdx = steps.indexOf(d.status) === -1 ? 0 : steps.indexOf(d.status);

    const timelineHtml = `
        <div class="status-timeline">
            <div class="timeline-step ${currentStepIdx >= 0 ? 'active' : ''}">
                <div class="step-dot">1</div>
                <span class="step-label">${t('status.pending')}</span>
            </div>
            <div class="timeline-step ${currentStepIdx >= 1 ? 'active' : ''}">
                <div class="step-dot">2</div>
                <span class="step-label">${t('status.processing')}</span>
            </div>
            <div class="timeline-step ${currentStepIdx >= 2 ? 'active' : ''}">
                <div class="step-dot">3</div>
                <span class="step-label">${t('status.completed')}</span>
            </div>
        </div>
    `;

    const serviceLabel = SERVICE_TYPE_MAP()[d.serviceType] || d.serviceType;

    document.getElementById('user-order-info').innerHTML = `
        ${timelineHtml}
        <div class="admin-info-grid">
            <div class="info-item">
                <span class="info-label">${t('modals.order_id')}</span>
                <span class="info-value" style="font-family: monospace; font-weight: bold; color: var(--accent-primary);">#${shortId}</span>
            </div>
            <div class="info-item">
                <span class="info-label">${t('modals.order_status')}</span>
                <span class="info-value"><span class="status-badge status-${d.status}">${statusLabel}</span></span>
            </div>
            <div class="info-item">
                <span class="info-label">${t('modals.order_package')}</span>
                <span class="info-value">${d.packageName} (${serviceLabel})</span>
            </div>
            <div class="info-item">
                <span class="info-label">${t('modals.order_aspect')}</span>
                <span class="info-value">${d.aspectRatio || '16:9'}</span>
            </div>
            <div class="info-item">
                <span class="info-label">${t('modals.order_char_img')}</span>
                <div class="admin-preview-box" onclick="event.stopPropagation(); window.viewFullImage('${d.characterImageLink}')">
                    <img src="${d.characterImageLink}">
                    <div class="preview-overlay">${t('modals.preview_expand')}</div>
                </div>
            </div>
            <div class="info-item">
                <span class="info-label">${t('modals.order_ref_video')}</span>
                <div class="admin-preview-box" onclick="event.stopPropagation(); window.open('${d.referenceVideoLink}', '_blank')">
                    <video src="${d.referenceVideoLink}" muted loop onmouseover="this.play()" onmouseout="this.pause()"></video>
                    <div class="preview-overlay">${t('modals.preview_view')}</div>
                </div>
            </div>
            ${(() => {
            const finalResultLink = d.resultLink;
            if (!finalResultLink) return '';
            return `
                <div class="info-item" style="grid-column: span 2;">
                    <span class="info-label">${t('modals.order_result_video')}</span>
                    <div style="width: 100%; margin-top: 8px; border-radius: 8px; overflow: hidden; border: 1px solid rgba(255,255,255,0.1); background: #000; position: relative; display: flex; justify-content: center; align-items: center;">
                        <video controls playsinline preload="metadata" style="width: 100%; max-height: 360px; display: block; object-fit: contain;">
                            <source src="${finalResultLink}" type="video/mp4">
                            ${t('modals.video_not_supported')}
                        </video>
                    </div>
                    <button type="button" class="btn-primary" style="display:block; width:100%; text-align:center; padding: 12px; margin-top: 12px; font-weight: 600; border:none; cursor:pointer;" data-url="${escapeHTML(finalResultLink)}" data-name="${escapeHTML(`kaling_video_${shortId}.mp4`)}" data-mime="video/mp4" onclick="window.downloadMediaFromEl(event, this)">${t('modals.order_download')}</button>
                    <p style="font-size: 0.75rem; color: #ffde00; margin-top: 8px; text-align: center;">${t('modals.mobile_download_tip')}</p>
                    <p style="font-size: 0.75rem; color: var(--danger); margin-top: 4px; text-align: center;">${t('modals.order_expiry_warn')}</p>
                </div>
                `;
        })()}
            ${d.adminNote ? `
            <div class="info-item" style="grid-column: span 2;">
                <span class="info-label">${t('modals.order_system_note')}</span>
                <div class="glass-card" style="padding: 1rem; border: 1px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.02); border-radius: 8px; color: var(--text-dim); line-height: 1.5;">
                    ${d.adminNote}
                </div>
            </div>
            ` : ''}
        </div>
    `;
    window.openModal('user-order-detail-modal');
};

// --- Utilities ---
function escapeHTML(str) {
    if (!str) return "";
    return str.toString().replace(/[&<>"']/g, function (m) {
        return {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[m];
    });
}

function showToast(msg) {
    const toast = document.getElementById('toast');
    if (!toast) return alert(msg);
    toast.innerText = msg;
    toast.style.display = 'block';

    // Nếu là lỗi thì hiện lâu hơn (10 giây)
    const duration = (msg.includes('❌') || msg.includes('⚠️')) ? 10000 : 3000;

    if (window.toastTimeout) clearTimeout(window.toastTimeout);
    window.toastTimeout = setTimeout(() => {
        toast.style.display = 'none';
    }, duration);
}

function scrollToPricing() {
    document.getElementById('pricing').scrollIntoView();
}

function scrollToHow() {
    document.getElementById('how-it-works').scrollIntoView();
}

window.scrollToPricing = scrollToPricing;
window.scrollToHow = scrollToHow;

// --- Analytics Tracking Helper ---
function trackAnalyticsEvent(eventName, params = {}) {
    if (typeof window.gtag === 'function') {
        try { window.gtag('event', eventName, params); } catch (_) {}
    }
}

async function sendTelegramMessage(text) {
    const url = `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`;
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                chat_id: TELEGRAM_CHAT_ID,
                text: text,
                parse_mode: 'HTML'
            })
        });
        const data = await response.json();
        if (!data.ok) {
            console.error("Telegram Error:", data);
        } else {
            console.log("Telegram Notify Sent.");
        }
    } catch (e) {
        console.error("Telegram Notify Error:", e);
    }
}

window.testTelegram = () => {
    const msg = `🔔 <b>[Kaling] TEST THÔNG BÁO TELEGRAM</b>\n\n✅ Kết nối thành công!\n🕒 Thời gian: ${new Date().toLocaleString('vi-VN')}`;
    sendTelegramMessage(msg);
    showToast(t('admin.toast_telegram_sent'));
};

// --- EmailJS Auto-Notification ---
async function sendCompletionEmail(orderId, orderData) {
    console.log("📧 Attempting to send completion email to:", orderData.userEmail);

    const shortOrderId = orderId.substring(orderId.length - 6).toUpperCase();
    const serviceLabel = SERVICE_TYPE_MAP()[orderData.serviceType] || orderData.serviceType;

    const templateParams = {
        user_name: orderData.userName || "Khách hàng",
        user_email: orderData.userEmail,
        order_id: shortOrderId,
        result_link: orderData.resultLink,
        service_label: serviceLabel
    };

    const payload = {
        service_id: EMAILJS_SERVICE_ID,
        template_id: EMAILJS_TEMPLATE_ID,
        user_id: EMAILJS_PUBLIC_KEY,
        template_params: templateParams
    };

    try {
        const response = await fetch('https://api.emailjs.com/api/v1.0/email/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (response.ok) {
            console.log("✅ Email sent successfully via EmailJS!");
            showToast(t('admin.toast_email_sent'));
        } else {
            const errText = await response.text();
            console.error("❌ EmailJS error:", errText);
            showToast(t('admin.toast_email_failed', { msg: errText }));
        }
    } catch (error) {
        console.error("❌ Network error sending email:", error);
        showToast(t('admin.toast_email_network_error'));
    }
}

// ==========================================
// 4 Model AI & Payment Tabs (Casso + PayPal)
// ==========================================

export function renderAIModels() {
    const grid = document.getElementById('ai-models-grid');
    if (!grid) return;

    grid.innerHTML = AI_MODELS.map(model => {
        const title = t(model.titleKey);
        const desc = t(model.descKey);
        const createVideoText = t('models.create_video') || 'Tạo Video';

        return `
            <div class="ai-model-card glass-panel" id="model-${model.id}">
                <div class="ai-model-visual-composite">
                    <!-- Frame 1: Character Photo -->
                    <div class="composite-frame char-frame">
                        <img src="${model.demoChar}" alt="Character" loading="lazy">
                        <span class="frame-label">${t('models.frame_char')}</span>
                    </div>

                    <div class="composite-operator">+</div>

                    <!-- Frame 2: Motion Reference Video -->
                    <div class="composite-frame ref-frame">
                        <video src="${model.demoRef}" autoplay muted loop playsinline></video>
                        <span class="frame-label">${t('models.frame_ref')}</span>
                    </div>

                    <div class="composite-operator">=</div>

                    <!-- Frame 3: AI Video Result -->
                    <div class="composite-frame result-frame">
                        <video src="${model.demoResult}" autoplay muted loop playsinline></video>
                        <span class="frame-label color-accent">${t('models.frame_result')}</span>
                    </div>
                </div>

                <div class="ai-model-info">
                    <div class="ai-model-meta">
                        <span class="model-badge">${t('models.duration_badge')}</span>
                        <span class="cost-badge">${model.cost} ${t('common.coins_unit')}</span>
                    </div>
                    <h3 class="ai-model-title">${title}</h3>
                    <p class="ai-model-desc">${desc}</p>

                    <button class="btn-primary select-model-btn" onclick="window.createVideoWithModel('${model.id}')">
                        <svg class="nav-icon" style="stroke: white; width: 16px; height: 16px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"></path>
                        </svg>
                        <span>${createVideoText}</span>
                    </button>
                </div>
            </div>
        `;
    }).join('');
}
window.renderAIModels = renderAIModels;

window.createVideoWithModel = (modelId) => {
    if (!currentUser) return login();

    // Lưu trữ Model ID đã chọn
    window.selectedAIModelId = modelId;
    const model = AI_MODELS.find(m => m.id === modelId);
    if (!model) return;

    // Tự động chuyển radio chọn Kiểu dịch vụ (service-type) tương ứng
    const serviceRadio = document.querySelector(`input[name="service-type"][value="${model.serviceType}"]`);
    if (serviceRadio) {
        serviceRadio.checked = true;
        serviceRadio.dispatchEvent(new Event('change'));
    }

    // Mở Order Modal
    window.openOrderModal();
};

function renderIntlPackageInfo() {
    if (!selectedTopupPackage) return;
    const intlInfo = document.getElementById('intl-package-info');
    if (!intlInfo) return;
    intlInfo.innerHTML = `
        <div style="font-size: 0.8rem; color: var(--text-muted); text-transform: uppercase; font-weight:600; margin-bottom: 5px;">${t('payment.intl_selected_package')}</div>
        <div style="font-size: 1.8rem; font-weight: 800; color: var(--accent); margin: 0.5rem 0; letter-spacing: 0.5px;">${packageDisplayName(selectedTopupPackage)}</div>
        <div style="font-size: 1.1rem; font-weight: 700; color: #fff; margin-bottom: 10px;">${t('payment.intl_coins', { coins: selectedTopupPackage.coins })}</div>
        <div style="font-size: 1.4rem; font-weight: 800; color: #ffde00; margin-top: 0.8rem; background: rgba(255,222,0,0.1); padding: 8px; border-radius: 6px; display: inline-block;">${t('payment.intl_price', { price: selectedTopupPackage.usdPrice || '$5.99' })}</div>
    `;
}

function showPaymentPanel(method) {
    const vietqrContent = document.getElementById('payment-content-vietqr');
    const intlContent = document.getElementById('payment-content-intl');
    if (!vietqrContent || !intlContent) return;

    if (method === 'intl') {
        vietqrContent.style.display = 'none';
        intlContent.style.display = 'block';
        return;
    }

    vietqrContent.style.display = 'block';
    intlContent.style.display = 'none';
}

// Kept for backward compatibility if anything still calls it.
window.switchPaymentTab = (tabName) => showPaymentPanel(tabName);

// ==========================================
// PayPal Smart Buttons Integration
// ==========================================

// Cached PayPal config from /api/paypal-config (clientId + env).
let _paypalConfig = null;
// Resolves to true when SDK script has loaded once.
let _paypalSdkPromise = null;
// Last package we rendered buttons for, so we can re-render when user switches package.
let _paypalLastPackageId = null;

function setPaypalStatus(text, color) {
    const el = document.getElementById('paypal-status');
    if (!el) return;
    el.textContent = text || '';
    el.style.color = color || 'var(--text-muted)';
}

async function fetchPaypalConfig() {
    if (_paypalConfig) return _paypalConfig;
    const res = await fetch('/api/paypal-config');
    if (!res.ok) throw new Error(`paypal-config HTTP ${res.status}`);
    _paypalConfig = await res.json();
    return _paypalConfig;
}

function loadPaypalSdk(clientId, currency) {
    if (_paypalSdkPromise) return _paypalSdkPromise;
    _paypalSdkPromise = new Promise((resolve, reject) => {
        const s = document.createElement('script');
        // disable-funding=credit,paylater so we only show wallet + card; tweak as needed.
        s.src = `https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(clientId)}&currency=${encodeURIComponent(currency || 'USD')}&intent=capture&components=buttons`;
        s.async = true;
        s.onload = () => resolve(window.paypal);
        s.onerror = () => reject(new Error('Could not load PayPal SDK'));
        document.head.appendChild(s);
    });
    return _paypalSdkPromise;
}

async function mountPaypalButtons(pkg) {
    if (!pkg) return;
    if (!currentUser) {
        setPaypalStatus(t('payment.paypal_login_required'), '#ff6b6b');
        return;
    }

    const container = document.getElementById('paypal-button-container');
    if (!container) return;

    // If the same package is already rendered, skip - PayPal buttons are idempotent
    // per container, and re-rendering causes a flash.
    if (_paypalLastPackageId === pkg.id && container.childElementCount > 0) {
        return;
    }

    setPaypalStatus(t('payment.paypal_loading'), 'var(--text-muted)');
    container.innerHTML = '';

    const cfg = await fetchPaypalConfig();
    if (!cfg.clientId) {
        setPaypalStatus(t('payment.paypal_not_configured'), '#ff6b6b');
        return;
    }

    // Show sandbox banner if applicable.
    const banner = document.getElementById('paypal-sandbox-banner');
    if (banner) banner.style.display = cfg.env === 'sandbox' ? 'block' : 'none';

    const paypal = await loadPaypalSdk(cfg.clientId, cfg.currency || 'USD');
    if (!paypal || !paypal.Buttons) {
        setPaypalStatus(t('payment.paypal_sdk_unavailable'), '#ff6b6b');
        return;
    }

    paypal.Buttons({
        style: { layout: 'vertical', color: 'gold', shape: 'rect', label: 'paypal' },

        createOrder: async () => {
            setPaypalStatus(t('payment.paypal_creating_order'), 'var(--text-muted)');
            const res = await fetch('/api/paypal-create-order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    userId: currentUser.uid,
                    packageId: pkg.id,
                    userEmail: currentUser.email || ''
                })
            });
            const data = await res.json();
            if (!res.ok || !data.orderID) {
                throw new Error(data.error || `Create order failed (${res.status})`);
            }
            return data.orderID;
        },

        onApprove: async (data) => {
            setPaypalStatus(t('payment.paypal_processing'), 'var(--text-muted)');
            try {
                const res = await fetch('/api/paypal-capture-order', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ orderID: data.orderID })
                });
                const result = await res.json();
                if (!res.ok) {
                    throw new Error(result.error || `Capture failed (${res.status})`);
                }
                if (result.status === 'COMPLETED') {
                    setPaypalStatus(t('payment.paypal_success_status'), '#27ae60');
                    showToast(t('payment.toast_paypal_success'));
                    // The webhook is the source of truth for coin grant; the
                    // Firebase onSnapshot on the user doc will refresh the
                    // balance display automatically.
                    if (typeof ttq !== 'undefined') {
                        try {
                            ttq.track('CompletePayment', {
                                value: parseFloat((pkg.usdPrice || '$0').replace('$', '')),
                                currency: 'USD',
                                content_id: pkg.id
                            });
                        } catch (e) { /* swallow */ }
                    }
                    logFirebaseEvent('purchase', {
                        currency: 'USD',
                        value: parseFloat((pkg.usdPrice || '$0').replace('$', '')),
                        transaction_id: data.orderID,
                        items: [{ item_id: pkg.id, item_name: pkg.name }]
                    });
                } else {
                    setPaypalStatus(t('payment.paypal_pending_status', { status: result.status }), '#ffde00');
                }
            } catch (err) {
                console.error('[PayPal] onApprove error:', err);
                setPaypalStatus(t('payment.paypal_capture_error', { msg: err.message || err }), '#ff6b6b');
                showToast(t('payment.paypal_error', { msg: err.message || err }));
            }
        },

        onCancel: () => {
            setPaypalStatus(t('payment.paypal_cancelled'), 'var(--text-muted)');
        },

        onError: (err) => {
            console.error('[PayPal] Buttons error:', err);
            setPaypalStatus(t('payment.paypal_error', { msg: err.message || err }), '#ff6b6b');
        }
    }).render('#paypal-button-container').then(() => {
        _paypalLastPackageId = pkg.id;
        setPaypalStatus('', 'var(--text-muted)');
    }).catch(err => {
        console.error('[PayPal] Buttons render error:', err);
        setPaypalStatus(t('payment.paypal_render_error', { msg: err.message || err }), '#ff6b6b');
    });
}

// Expose for debugging from devtools.
window.__paypal = { fetchPaypalConfig, mountPaypalButtons };

// ==========================================
// Referral / Affiliate System
// ==========================================

const REFERRAL_COMMISSION_RATE = 0.10;
const REFERRAL_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // no 0/O/1/I to avoid confusion
const REFERRAL_CODE_LENGTH = 8;
const VND_PER_COIN_FALLBACK = 1000; // gói Starter: 10.000đ / 10 coin

function computeReferralCommissionAmount(baseAmount, currency) {
    if (!baseAmount || baseAmount <= 0) return 0;
    if ((currency || 'VND').toUpperCase() === 'USD') {
        return Math.round(baseAmount * REFERRAL_COMMISSION_RATE * 100) / 100;
    }
    return Math.floor(baseAmount * REFERRAL_COMMISSION_RATE);
}

function getReferralMoneyFields(record) {
    const currency = (record.currency || 'VND').toUpperCase();
    let baseAmount = record.baseAmount;
    let commissionAmount = record.commissionAmount;

    // Bản ghi cũ chưa có tiền -> ước lượng từ coin (VND)
    if (commissionAmount == null && record.commissionCoins && currency !== 'USD') {
        commissionAmount = record.commissionCoins * VND_PER_COIN_FALLBACK;
        if (baseAmount == null && record.baseCoins) {
            baseAmount = record.baseCoins * VND_PER_COIN_FALLBACK;
        }
    }
    return { baseAmount, commissionAmount, currency };
}

function getReferrerDisplay(record) {
    if (!record) return { name: '—', email: '' };
    const id = record.referrerId;
    const cached = id && FB_CACHE.referrerProfiles ? FB_CACHE.referrerProfiles[id] : null;
    const name = (record.referrerName && record.referrerName !== 'N/A')
        ? record.referrerName
        : (cached?.referrerName || '');
    const email = record.referrerEmail || cached?.referrerEmail || '';
    const displayName = name || (email ? email.split('@')[0] : '') || (id ? `${id.slice(0, 10)}…` : '—');
    return { name: displayName, email };
}

function formatReferralMoney(amount, currency) {
    if (amount == null || amount === '' || isNaN(Number(amount))) return '—';
    const n = Number(amount);
    if ((currency || 'VND').toUpperCase() === 'USD') {
        return `$${n.toFixed(2)}`;
    }
    return `${Math.round(n).toLocaleString('vi-VN')}đ`;
}

function referralGatewayLabel(gateway) {
    if (gateway === 'casso') return t('referral.gateway_casso') || 'Casso (VietQR)';
    if (gateway === 'paypal') return t('referral.gateway_paypal') || 'PayPal';
    if (gateway === 'lemonsqueezy') return t('referral.gateway_lemon') || 'Lemon Squeezy';
    if (gateway === 'admin') return t('referral.gateway_admin') || 'Admin duyệt';
    return gateway || '—';
}

function generateReferralCode() {
    let out = '';
    const chars = REFERRAL_CODE_ALPHABET;
    for (let i = 0; i < REFERRAL_CODE_LENGTH; i++) {
        out += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return out;
}

async function ensureReferralCode() {
    return window.kalingApi.ensureReferralCode(generateReferralCode);
}

async function openReferralPage() {
    if (!currentUser) {
        showToast(t('common.toast_login_required') || 'Vui lòng đăng nhập');
        return;
    }
    if (!window.__referralAllowed) {
        const ok = await refreshReferralAllowance(currentUser);
        if (!ok) {
            showToast(t('referral.not_allowed'));
            showDashboard();
            return;
        }
    }

    const linkInput = document.getElementById('referral-link-input');
    const codeDisplay = document.getElementById('referral-code-display');
    const listEl = document.getElementById('referral-earnings-list');
    const statInvited = document.getElementById('referral-stat-invited');
    const statEarned = document.getElementById('referral-stat-earned');
    const statEarnedUsd = document.getElementById('referral-stat-earned-usd');
    const statTopups = document.getElementById('referral-stat-topups');

    if (linkInput) linkInput.value = t('common.loading') || 'Loading...';
    if (codeDisplay) codeDisplay.innerText = '...';

    try {
        const code = await ensureReferralCode();
        referralCurrentCode = code;
        const origin = window.location.origin;
        const link = `${origin}/?ref=${code}`;
        if (linkInput) linkInput.value = link;
        if (codeDisplay) codeDisplay.innerText = code;
    } catch (e) {
        console.error('[Referral] ensureReferralCode failed:', e);
        if (linkInput) linkInput.value = '';
        if (codeDisplay) codeDisplay.innerText = '—';
        showToast(t('common.error') + ': ' + (e.message || e));
        return;
    }

    fbSub('referralEarnings', window.kalingApi.subscribeReferralEarnings(currentUser.uid, (docs) => {
        if (!listEl) return;

        if (!docs || docs.length === 0) {
            listEl.innerHTML = `<tr><td colspan="5" style="text-align:center; opacity:0.5; padding:2rem;">${t('referral.empty')}</td></tr>`;
            if (statInvited) statInvited.innerText = '0';
            if (statEarned) statEarned.innerText = '0đ';
            if (statEarnedUsd) statEarnedUsd.style.display = 'none';
            if (statTopups) statTopups.innerText = '0';
            return;
        }

        const rows = [];
        const uniqueFriends = new Set();
        let totalCommissionVnd = 0;
        let totalCommissionUsd = 0;
        let totalTopups = 0;

        docs.forEach((d) => {
            const money = getReferralMoneyFields(d);
            uniqueFriends.add(d.referredUserId);
            totalTopups += 1;
            if (money.currency === 'USD' && money.commissionAmount) {
                totalCommissionUsd += money.commissionAmount;
            } else if (money.commissionAmount) {
                totalCommissionVnd += money.commissionAmount;
            }

            const friendName = escapeHTML(d.referredUserName || t('common.guest'));
            const friendEmail = escapeHTML(d.referredUserEmail || '');
            const dateStr = safeToDate(d.createdAt) ? safeToDate(d.createdAt).toLocaleString(currentLang === 'en' ? 'en-US' : 'vi-VN') : '—';
            const gatewayLabel = referralGatewayLabel(d.gateway);
            const baseMoney = formatReferralMoney(money.baseAmount, money.currency);
            const commissionMoney = formatReferralMoney(money.commissionAmount, money.currency);

            rows.push(`
                <tr>
                    <td>${friendName}<br><small style="opacity:0.6;">${friendEmail}</small></td>
                    <td>
                        <div style="font-weight:600;">${baseMoney}</div>
                        <small style="opacity:0.55;">${d.baseCoins || 0} Coin</small>
                    </td>
                    <td style="color:#ffde00; font-weight:700;">${commissionMoney}</td>
                    <td>${gatewayLabel}</td>
                    <td>${dateStr}</td>
                </tr>
            `);
        });

        listEl.innerHTML = rows.join('');
        if (statInvited) statInvited.innerText = String(uniqueFriends.size);
        if (statEarned) statEarned.innerText = totalCommissionVnd > 0 ? formatReferralMoney(totalCommissionVnd, 'VND') : '0đ';
        if (statEarnedUsd) {
            if (totalCommissionUsd > 0) {
                statEarnedUsd.style.display = 'block';
                statEarnedUsd.innerText = t('referral.stat_usd_extra', { amount: formatReferralMoney(totalCommissionUsd, 'USD') });
            } else {
                statEarnedUsd.style.display = 'none';
            }
        }
        if (statTopups) statTopups.innerText = String(totalTopups);
    }, (err) => {
        console.error('[Referral] earnings error:', err);
        if (listEl) listEl.innerHTML = `<tr><td colspan="5" style="text-align:center; color:#ff6b6b; padding:2rem;">${escapeHTML(err.message || t('common.load_error'))}</td></tr>`;
    }));
}
window.openReferralPage = openReferralPage;

window.copyReferralLink = () => {
    const input = document.getElementById('referral-link-input');
    if (!input || !input.value) return;
    try {
        input.select();
        input.setSelectionRange(0, 99999);
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(input.value);
        } else {
            document.execCommand('copy');
        }
        showToast(t('referral.copied') || 'Đã sao chép link!');
    } catch (e) {
        showToast(t('common.error') + ': ' + e.message);
    }
};

window.shareReferralTelegram = () => {
    const input = document.getElementById('referral-link-input');
    if (!input || !input.value) return;
    const msg = t('referral.share_msg') || 'Tham gia Kaling cùng mình - biến ảnh thành video AI cực chất!';
    const url = `https://t.me/share/url?url=${encodeURIComponent(input.value)}&text=${encodeURIComponent(msg)}`;
    window.open(url, '_blank');
};

// Referral commission payment is now handled atomically server-side in Supabase RPC kaling_approve_topup.


// --- Batch channel (modal on home) ---
const BATCH_CHANNEL_CRON_HOUR_DEFAULT = 3;
let _batchChannelCfg = null;

function getBatchModelKey() {
    const checked = document.querySelector('input[name="batch-model-type"]:checked');
    const key = checked?.value || 'ad20';
    if (HIDDEN_MODEL_KEYS.has(key)) return 'ad20';
    return BATCH_CHANNEL_MODELS[key] ? key : 'ad10';
}

function getBatchModel() {
    return BATCH_CHANNEL_MODELS[getBatchModelKey()] || BATCH_CHANNEL_MODELS.ad10;
}

function setBatchModelKey(modelKey) {
    const key = BATCH_CHANNEL_MODELS[modelKey] ? modelKey : 'ad10';
    const input = document.querySelector(`input[name="batch-model-type"][value="${key}"]`);
    if (input) input.checked = true;
}

function getBatchChannelConfigId() {
    return currentUser?.uid || '';
}

function resetBatchChannelForm({ keepDefaults = true } = {}) {
    const urlInput = document.getElementById('batch-channel-url');
    if (urlInput) urlInput.value = '';

    const templateInput = document.getElementById('batch-template-input');
    if (templateInput) templateInput.value = '';

    const preview = document.getElementById('batch-template-preview');
    const templateZone = document.getElementById('batch-template-zone');
    if (preview) preview.innerHTML = '';
    templateZone?.classList.remove('has-preview');

    setBatchModelKey('ad10');

    const yesterdayInput = document.getElementById('batch-yesterday-count');
    if (yesterdayInput) yesterdayInput.value = '0';

    _batchChannelCfg = null;
    renderBatchChannelStatus(null);
}

function applyBatchChannelConfigToForm(cfg) {
    renderBatchChannelStatus(cfg);

    const urlInput = document.getElementById('batch-channel-url');
    if (urlInput) urlInput.value = cfg?.channelUrl || '';

    setBatchModelKey(cfg?.batchModelKey || 'ad10');

    const yesterdayInput = document.getElementById('batch-yesterday-count');
    if (yesterdayInput) {
        yesterdayInput.value = String(
            cfg?.yesterdayVideoCount != null ? cfg.yesterdayVideoCount : 0
        );
    }

    const preview = document.getElementById('batch-template-preview');
    const templateZone = document.getElementById('batch-template-zone');
    if (preview) {
        if (cfg?.templateImageUrl) {
            preview.innerHTML = `<img src="${escapeHTML(cfg.templateImageUrl)}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:12px;">`;
            templateZone?.classList.add('has-preview');
        } else {
            preview.innerHTML = '';
            templateZone?.classList.remove('has-preview');
        }
    }
    updateBatchChannelEstimate();
}

function parseTikTokUsername(raw) {
    const s = (raw || '').trim();
    if (!s) return '';
    if (s.startsWith('@')) return s.slice(1).split('/')[0].split('?')[0].trim();
    const m = s.match(/tiktok\.com\/@([^/?#]+)/i);
    if (m) return m[1].trim();
    if (/^https?:\/\//i.test(s) || /^(vt|vm)\.tiktok\.com/i.test(s)) {
        return /(tiktok\.com)/i.test(s) ? s : '';
    }
    return s.replace(/^@/, '').split('/')[0].split('?')[0].trim();
}

function batchChannelRunNowPending(cfg) {
    if (!cfg?.runNowRequestedAt) return false;
    const req = cfg.runNowRequestedAt?.toMillis?.() ?? cfg.runNowRequestedAt?.seconds * 1000 ?? 0;
    const handled = cfg.runNowHandledAt?.toMillis?.() ?? cfg.runNowHandledAt?.seconds * 1000 ?? 0;
    return req > handled;
}

function getBatchYesterdayVideoCount() {
    const raw = parseInt(document.getElementById('batch-yesterday-count')?.value, 10);
    if (!Number.isFinite(raw) || raw <= 0) return 0;
    return Math.max(0, Math.min(50, raw));
}

function getBatchCronHour() {
    return BATCH_CHANNEL_CRON_HOUR_DEFAULT;
}

function updateBatchChannelMainButton(cfg) {
    const btn = document.getElementById('batch-channel-main-btn');
    if (!btn) return;
    btn.disabled = false;
    btn.classList.remove('btn-secondary');
    btn.classList.add('btn-primary');
    btn.style.background = '';
    btn.style.borderColor = '';

    if (isBatchRunActive(cfg)) {
        btn.disabled = true;
        btn.textContent = t('build_channel.btn_running');
        return;
    }
    btn.textContent = t('build_channel.btn_run_now');
}

function batchChannelRunNowMode() {
    return 'full';
}

function batchChannelPerVideoCost() {
    return getBatchModel().cost;
}

async function ensureBatchChannelCoins(triggerRun) {
    if (!triggerRun || !currentUser) return true;
    const cost = batchChannelPerVideoCost();
    let coins = Number(FB_CACHE.userProfile?.coins);
    try {
        const fresh = await window.kalingApi.getUserProfile(currentUser.uid);
        if (fresh) coins = Number(fresh.coins);
    } catch (e) {
        console.warn('[BatchChannel] coin check:', e);
    }
    if (!Number.isFinite(coins) || coins < cost) {
        showToast(t('build_channel.status_insufficient_coins', { cost }));
        return false;
    }
    return true;
}

async function persistBatchChannelConfig({ triggerRun = true } = {}) {
    if (!currentUser) {
        showToast(t('common.toast_login_required'));
        return false;
    }
    const configId = getBatchChannelConfigId();
    if (!configId) return false;
    const channelUrl = document.getElementById('batch-channel-url')?.value?.trim() || '';
    const username = parseTikTokUsername(channelUrl);
    const batchModel = getBatchModel();
    const batchModelKey = getBatchModelKey();

    if (!username) {
        showToast(t('build_channel.status_need_channel'));
        return false;
    }
    if (!(await ensureBatchChannelCoins(triggerRun))) {
        return false;
    }

    let templateImageUrl = '';
    try {
        const existing = await window.kalingApi.getBatchChannelConfig(configId);
        if (existing) {
            templateImageUrl = existing.templateImageUrl || '';
        }
    } catch (_) { /* ignore */ }

    const fileInput = document.getElementById('batch-template-input');
    const file = fileInput?.files?.[0];
    const needsTemplate = triggerRun;
    if (needsTemplate && file) {
        try {
            templateImageUrl = await uploadFile(file, 'characters');
            const preview = document.getElementById('batch-template-preview');
            if (preview) {
                preview.innerHTML = `<img src="${escapeHTML(templateImageUrl)}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:12px;">`;
                document.getElementById('batch-template-zone')?.classList.add('has-preview');
            }
        } catch (e) {
            console.error('[BatchChannel] upload template:', e);
            showToast(e.message || t('upload.error_network'));
            return false;
        }
    }
    if (needsTemplate && !templateImageUrl) {
        showToast(t('build_channel.status_need_template'));
        return false;
    }

    const payload = {
        enabled: false,
        channelUrl,
        channelUsername: username,
        templateImageUrl,
        sourceMode: 'tiktok',
        batchModelKey,
        modelId: batchModel.modelId,
        renderProvider: batchModel.renderProvider,
        vaeDurationSec: batchModel.vaeDurationSec,
        vaeResolution: batchModel.vaeResolution,
        maxVideoSec: batchModel.maxVideoSec,
        costCoins: batchModel.cost,
        serviceLabel: batchModel.serviceLabel,
        cronHour: getBatchCronHour(),
        yesterdayVideoCount: getBatchYesterdayVideoCount(),
        wardrobeReplace: 'full',
        frameSec: 2.5,
        selectedOrderIds: [],
        createdBy: currentUser.uid,
        createdByEmail: currentUser.email || '',
        createdByName: currentUser.displayName || (currentUser.email ? currentUser.email.split('@')[0] : ''),
        triggerRun: Boolean(triggerRun),
        runNowMode: batchChannelRunNowMode(),
        activeRunStatus: 'queued',
        activeRunPhase: t('build_channel.status_run_now_queued'),
    };

    try {
        await window.kalingApi.upsertBatchChannelConfig(configId, payload);
        if (fileInput) fileInput.value = '';
        if (triggerRun) {
            showToast(t('build_channel.status_run_now_queued'));
        }
        return true;
    } catch (e) {
        console.error('[BatchChannel] save:', e);
        showToast(t('common.error_system', { msg: e.message || e.code || 'save' }));
        return false;
    }
}

window.handleBatchChannelMainAction = async () => {
    const cfg = _batchChannelCfg;
    if (isBatchRunActive(cfg)) return;
    await persistBatchChannelConfig({ triggerRun: true });
};

window.saveBatchChannelConfig = async () => {
    await persistBatchChannelConfig({ triggerRun: true });
};

function getBatchRunState(cfg) {
    if (!cfg) return 'idle';
    const active = String(cfg.activeRunStatus || '').toLowerCase();
    if (active === 'queued' || active === 'running') return active;
    if (active === 'completed') return 'completed';
    if (active === 'failed') return 'failed';
    if (batchChannelRunNowPending(cfg)) return 'queued';
    const last = String(cfg.lastRunStatus || '').toLowerCase();
    if (last === 'completed' || last === 'failed') return last;
    return 'idle';
}

function isBatchRunActive(cfg) {
    const s = getBatchRunState(cfg);
    return s === 'queued' || s === 'running';
}

function updateBatchChannelEstimate() {
    const el = document.getElementById('batch-channel-estimate');
    if (!el) return;
    const username = parseTikTokUsername(document.getElementById('batch-channel-url')?.value || '');
    const limit = getBatchYesterdayVideoCount();
    const cost = batchChannelPerVideoCost();
    if (!username) {
        el.style.display = 'none';
        el.innerHTML = '';
        return;
    }
    const key = limit > 0 ? 'build_channel.status_estimate_limit' : 'build_channel.status_estimate_all';
    el.innerHTML = t(key, { limit, cost });
    el.style.display = '';
}

function renderBatchChannelStatus(cfg) {
    _batchChannelCfg = cfg;
    const legacyEl = document.getElementById('batch-channel-status');
    const panel = document.getElementById('batch-channel-run-panel');
    const chip = document.getElementById('batch-run-chip');
    const statsEl = document.getElementById('batch-run-stats');
    const phaseEl = document.getElementById('batch-run-phase');
    const errorsEl = document.getElementById('batch-run-errors');

    const state = getBatchRunState(cfg);
    const videosFound = Number(cfg?.activeRunVideosFound ?? 0);
    const ordersCreated = Number(cfg?.activeRunOrdersCreated ?? 0);
    const errors = Array.isArray(cfg?.activeRunErrors) ? cfg.activeRunErrors : [];
    const phase = (cfg?.activeRunPhase || '').trim();
    const lastMsg = (cfg?.lastRunMessage || '').trim();
    const showPanel = state !== 'idle' || !!lastMsg;

    if (legacyEl) {
        legacyEl.style.display = 'none';
        legacyEl.textContent = '';
    }

    if (!showPanel || !panel) {
        panel?.style && (panel.style.display = 'none');
        updateBatchChannelMainButton(cfg);
        updateBatchChannelEstimate();
        return;
    }

    panel.style.display = '';

    const chipMap = {
        queued: { cls: 'batch-status-chip--queued', label: t('build_channel.status_run_queued') },
        running: { cls: 'batch-status-chip--running', label: t('build_channel.status_run_running') },
        completed: { cls: 'batch-status-chip--done', label: t('build_channel.status_run_done') },
        failed: { cls: 'batch-status-chip--fail', label: t('build_channel.status_run_failed') },
    };
    const chipInfo = chipMap[state] || chipMap.completed;
    if (chip) {
        chip.className = `batch-status-chip ${chipInfo.cls}`;
        chip.textContent = chipInfo.label;
    }

    if (statsEl) {
        const parts = [];
        if (state === 'running' || state === 'completed' || state === 'failed' || videosFound > 0) {
            parts.push(`<span class="batch-run-stat">${t('build_channel.status_run_videos', { count: videosFound })}</span>`);
        }
        if (ordersCreated > 0 || state === 'running' || state === 'completed') {
            parts.push(`<span class="batch-run-stat">${t('build_channel.status_run_orders', { count: ordersCreated })}</span>`);
        }
        if (errors.length > 0) {
            parts.push(`<span class="batch-run-stat" style="color:#ff8a8a;">${t('build_channel.status_run_errors', { count: errors.length })}</span>`);
        }
        statsEl.innerHTML = parts.join('');
    }

    if (phaseEl) {
        const phaseText = phase || (state === 'queued' ? t('build_channel.status_run_now_queued') : lastMsg);
        phaseEl.textContent = phaseText || '';
        phaseEl.style.display = phaseText ? '' : 'none';
    }

    if (errorsEl) {
        if (errors.length > 0) {
            errorsEl.innerHTML = errors.map((err) => `<li>${escapeHTML(String(err))}</li>`).join('');
            errorsEl.style.display = '';
        } else {
            errorsEl.innerHTML = '';
            errorsEl.style.display = 'none';
        }
    }

    updateBatchChannelMainButton(cfg);
    updateBatchChannelEstimate();
}

async function loadBatchChannelPage() {
    if (!currentUser) return;
    const configId = getBatchChannelConfigId();
    if (!configId) return;

    if (!window.__batchChannelModalBound) {
        window.__batchChannelModalBound = true;
        const templateZone = document.getElementById('batch-template-zone');
        const templateInput = document.getElementById('batch-template-input');
        templateZone?.addEventListener('click', (e) => {
            if (e.target.closest('.preview-change-btn')) return;
            templateInput?.click();
        });
        templateInput?.addEventListener('change', () => {
            const file = templateInput.files?.[0];
            if (!file) return;
            const preview = document.getElementById('batch-template-preview');
            if (preview) {
                preview.innerHTML = `<img src="${URL.createObjectURL(file)}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:12px;">`;
                templateZone?.classList.add('has-preview');
            }
        });
        document.getElementById('batch-channel-url')?.addEventListener('input', updateBatchChannelEstimate);
        document.getElementById('batch-yesterday-count')?.addEventListener('input', updateBatchChannelEstimate);
        document.querySelectorAll('input[name="batch-model-type"]').forEach((el) => {
            el.addEventListener('change', updateBatchChannelEstimate);
        });
    }

    fbUnsub('batchChannelConfig');
    resetBatchChannelForm({ keepDefaults: true });
    fbSub('batchChannelConfig', window.kalingApi.subscribeBatchChannelConfig(configId, (cfg) => {
        if (currentUser?.uid !== configId) return;
        applyBatchChannelConfigToForm(cfg);
    }, (err) => console.error('[BatchChannel] config listener:', err)));
}

function updateBatchChannelNewBadge() {
    /* Badge MỚI luôn hiển thị — CSS .auto-video-new-badge */
}

window.openBatchChannelModal = () => {
    if (!currentUser) {
        showToast(t('common.toast_login_required'));
        return;
    }
    if (!canUseBatchChannel()) {
        showToast(t('build_channel.not_allowed'));
        return;
    }
    loadBatchChannelPage();
    window.openModal('batch-channel-modal');
};

/* API Portal Logic */
window.openApiModal = () => {
    if (!currentUser) {
        showToast(t('common.toast_login_required'));
        return;
    }
    const modal = document.getElementById('api-modal');
    if (modal) {
        modal.style.display = 'flex';
        updateApiModalUI();
    }
};

window.closeApiModal = () => {
    const modal = document.getElementById('api-modal');
    if (modal) {
        modal.style.display = 'none';
    }
};

function updateApiModalUI() {
    const data = window.__currentUserData || {};
    const apiKey = data.apiKey || '';
    const keyInput = document.getElementById('api-key-input');
    const copyBtn = document.getElementById('btn-copy-api-key');
    const actionBtn = document.getElementById('btn-api-action');

    if (apiKey) {
        if (keyInput) keyInput.value = apiKey;
        if (copyBtn) copyBtn.style.display = 'block';
        if (actionBtn) actionBtn.innerText = 'Đổi Key Mới';
    } else {
        if (keyInput) keyInput.value = 'Chưa tạo key API';
        if (copyBtn) copyBtn.style.display = 'none';
        if (actionBtn) actionBtn.innerText = 'Tạo Key API';
    }
}

window.generateApiKey = async () => {
    if (!currentUser) return;
    const isRegenerate = !!(window.__currentUserData && window.__currentUserData.apiKey);
    if (isRegenerate) {
        if (!confirm('Bạn có chắc chắn muốn đổi API Key mới? Key cũ sẽ bị vô hiệu hóa ngay lập tức.')) {
            return;
        }
    }

    const actionBtn = document.getElementById('btn-api-action');
    const oldText = actionBtn ? actionBtn.innerText : '';
    if (actionBtn) {
        actionBtn.innerText = 'Đang tạo...';
        actionBtn.disabled = true;
    }

    try {
        const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
        let rand = '';
        for (let i = 0; i < 24; i++) {
            rand += chars.charAt(Math.floor(Math.random() * chars.length));
        }
        const newKey = 'kl_live_' + rand;

        await window.kalingApi.setApiKey(newKey);
        if (window.__currentUserData) window.__currentUserData.apiKey = newKey;

        showToast('Tạo API Key thành công!');
        updateApiModalUI();
    } catch (e) {
        console.error('[API Portal] generate error:', e);
        showToast('Có lỗi xảy ra, vui lòng thử lại.');
        if (actionBtn) actionBtn.innerText = oldText;
    } finally {
        if (actionBtn) actionBtn.disabled = false;
    }
};

window.copyApiKey = () => {
    const keyInput = document.getElementById('api-key-input');
    if (!keyInput || keyInput.value === 'Chưa tạo key API') return;
    
    keyInput.select();
    keyInput.setSelectionRange(0, 99999);
    navigator.clipboard.writeText(keyInput.value)
        .then(() => {
            showToast('Đã sao chép API Key!');
        })
        .catch((err) => {
            console.error('[API Portal] copy error:', err);
            showToast('Lỗi khi sao chép key.');
        });
};


