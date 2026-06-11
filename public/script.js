/**
 * script.js - Core logic for Nhay Cloud
 */

const TELEGRAM_BOT_TOKEN = '8783657660:AAHRfxHNiohZzPJ2OaQ7TEMNKwb7AAlp2uo';
const TELEGRAM_CHAT_ID = '6067707939';
const MAX_VIDEO_DURATION_SEC = 30;
const MAX_CHAR_FILE_BYTES = 10 * 1024 * 1024;
const MAX_VIDEO_FILE_BYTES = 50 * 1024 * 1024;

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

async function ensureUserPromoFieldsSynced(orders, userData) {
    if (!currentUser || !window.firebase) return;
    const promoOrders = (orders || []).filter(isPromo1CoinOrder);
    const countFromOrders = promoOrders.length;
    const countFromUser = Number(userData?.promo1CoinCount) || 0;
    if (countFromOrders <= countFromUser) return;

    let lastDay = userData?.promo1CoinLastDay || '';
    promoOrders.forEach((o) => {
        const created = safeToDate(o.createdAt);
        if (!created) return;
        const dayKey = getLocalDayKey(created);
        if (!lastDay || dayKey > lastDay) lastDay = dayKey;
    });

    const { db, doc, updateDoc } = window.firebase;
    try {
        await updateDoc(doc(db, 'users', currentUser.uid), {
            promo1CoinCount: countFromOrders,
            promo1CoinLastDay: lastDay,
            updatedAt: window.firebase.serverTimestamp()
        });
    } catch (e) {
        console.warn('[promo1coin] sync user fields failed:', e.message);
    }
}

function syncPromo1CoinState(orders, userData = window.__currentUserData) {
    promo1CoinStats = { eligible: false, totalUsed: 0, usedToday: false, remainingTotal: 0, todayKey: getLocalDayKey() };
    isFirstTimeUser = false;
    return promo1CoinStats;
}

// --- Data Constants ---
const MODEL_COST_FAST = 3;
const MODEL_COST_TURBO = 10;

function modelCoinCost(modelKey) {
    return modelKey === 'turbo' ? MODEL_COST_TURBO : MODEL_COST_FAST;
}

function syncModelPriceLabels() {
    const fastEl = document.getElementById('model-fast-cost');
    const turboEl = document.getElementById('model-turbo-cost');
    if (fastEl) fastEl.textContent = String(MODEL_COST_FAST);
    if (turboEl) turboEl.textContent = String(MODEL_COST_TURBO);
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
    { id: 'creator',    name: 'Creator',    coins: 50,  price: '50.000đ',  usdPrice: '$2.99', amount: 50000,  featured: true, hasBonus: false },
    { id: 'studio',     name: 'Studio',     coins: 550,  price: '500.000đ',  usdPrice: '$24.99', amount: 500000,  hasBonus: true },
    { id: 'pro-studio', name: 'Enterprise', coins: 1100, price: '1.000.000đ', usdPrice: '$49.99', amount: 1000000, hasBonus: true }
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
    if (!currentUser) return COIN_PACKAGES;
    return COIN_PACKAGES.filter((pkg) => !hasCompletedOneTimeTopup(pkg));
}

const AI_MODELS = [
    {
        id: 'copy-motion-photo',
        titleKey: 'models.model1_title',
        descKey: 'models.model1_desc',
        cost: MODEL_COST_FAST,
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
    // "Model thường" uses Aidancing model id 124
    fast: { nameKey: "modals.model_fast", cost: MODEL_COST_FAST, timeKey: "modals.model_fast_desc", modelId: "124" },
    turbo: { nameKey: "modals.model_turbo", cost: MODEL_COST_TURBO, timeKey: "modals.model_turbo_desc", modelId: "117" }
};

function localizedModel(key) {
    const m = MODELS[key];
    if (!m) return null;
    return {
        ...m,
        name: t(m.nameKey),
        time: t(m.timeKey)
    };
}

const SERVICE_PACKAGES = [
    { id: 'plus', name: 'Plus', cost: MODEL_COST_FAST, featureKeys: ['services.plus_f1', 'services.plus_f2', 'services.plus_f3'], featured: true },
    { id: 'viral', name: 'Viral', cost: MODEL_COST_TURBO, featureKeys: ['services.viral_f1', 'services.viral_f2', 'services.viral_f3'] }
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
const SUPER_ADMIN_EMAILS = ["traderfinn0312@gmail.com", "dinhhoangvan.hh@gmail.com"]; // Bootstrap super-admin (khớp Firestore rules)

function normalizeReferralAllowlistEmail(email) {
    return (email || '').trim().toLowerCase();
}

function updateReferralNavVisibility(allowed) {
    const item = document.getElementById('nav-referral-item');
    if (item) item.style.display = allowed ? 'flex' : 'none';
}

async function refreshReferralAllowance(user) {
    const email = user?.email || currentUser?.email || '';
    const key = normalizeReferralAllowlistEmail(email);
    if (!key) {
        window.__referralAllowed = false;
        updateReferralNavVisibility(false);
        return false;
    }
    const { db, doc, getDoc } = window.firebase;
    try {
        const snap = await getDoc(doc(db, 'referralAllowlist', key));
        window.__referralAllowed = snap.exists();
    } catch (e) {
        console.warn('[Referral] allowlist check failed:', e.message);
        window.__referralAllowed = false;
    }
    updateReferralNavVisibility(window.__referralAllowed);
    return window.__referralAllowed;
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
    if (window.firebase && window.firebase.analytics && window.firebase.logEvent) {
        window.firebase.logEvent(window.firebase.analytics, name, params);
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

function trackMetaEvent(eventName, params = {}) {
    if (!isMetaPixelReady()) return;
    const payload = { ...params };
    if (!payload.eventID) payload.eventID = metaEventId(eventName);
    fbq('track', eventName, payload);
    console.log(`📘 Meta Pixel: ${eventName}`, payload);
}

function updateMetaAdvancedMatching(user) {
    if (!isMetaPixelReady() || !user?.email) return;
    const em = String(user.email).trim().toLowerCase();
    if (!em) return;
    fbq('init', metaPixelId(), { em });
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
    if (window.__isAdmin && typeof loadAdminPanel === 'function') {
        if (adminActiveTab === 'orders') renderAdminOrders();
        else if (adminActiveTab === 'topups') renderAdminTopups();
        else if (adminActiveTab === 'users') renderAdminUsers();
        else if (adminActiveTab === 'referrals') renderAdminReferrals();
        else if (adminActiveTab === 'bots') renderAdminBots();
    }
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

    const { auth, onAuthStateChanged } = window.firebase;

    onAuthStateChanged(auth, (user) => {
        if (user) {
            currentUser = user;
            if (isInAppBrowser()) {
                showInAppBrowserBanner();
            }
            handleUserLoggedIn(user).catch((e) => {
                console.error("Auth profile error:", e);
                showToast(t('common.error_auth', { msg: e.message || e.code || 'Firestore' }));
            });
        } else {
            currentUser = null;
            handleUserLoggedOut();
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

function showInAppBrowserBanner() {
    if (!isInAppBrowser()) return;
    const authModal = document.getElementById('auth-modal');
    if (authModal) authModal.style.display = 'none';
    const modal = document.getElementById('inapp-browser-modal');
    if (!modal) return;
    modal.hidden = false;
    document.body.classList.add('inapp-modal-open');
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

    if (isAndroid) {
        try {
            const parsed = new URL(url);
            const intent =
                `intent://${parsed.host}${parsed.pathname}${parsed.search}${parsed.hash}` +
                `#Intent;scheme=${parsed.protocol.replace(':', '')};` +
                `package=com.android.chrome;` +
                `S.browser_fallback_url=${encodeURIComponent(url)};end`;
            window.location.href = intent;
            showToast(t('modals.inapp_open_attempt'));
            return;
        } catch (e) {
            console.warn('[OpenBrowser] Android intent failed:', e);
        }
    }

    if (isIOS) {
        const noProto = url.replace(/^https?:\/\//, '');
        try {
            window.location.href = `x-safari-https://${noProto}`;
            showToast(t('modals.inapp_open_attempt'));
            return;
        } catch (e) {
            console.warn('[OpenBrowser] iOS Safari scheme failed:', e);
        }
        try {
            window.location.href = `googlechromes://${noProto}`;
            showToast(t('modals.inapp_open_attempt'));
            return;
        } catch (e) {
            console.warn('[OpenBrowser] iOS Chrome scheme failed:', e);
        }
    }

    showToast(t('modals.inapp_open_attempt'));
};

// --- Browser Detection ---
function detectInAppBrowser() {
    const isInApp = isInAppBrowser();
    const isSupported = isStandaloneBrowser();

    if (isInApp) {
        showInAppBrowserBanner();
    }

    if (!isSupported) {
        const googleBtn = document.getElementById('google-login-btn');
        const googleDivider = document.querySelector('.google-auth-divider');
        const inAppNote = document.getElementById('inapp-auth-note');
        const authEmailBtn = document.getElementById('auth-email-btn');
        const authModalDesc = document.getElementById('auth-modal-desc');

        if (googleBtn) googleBtn.style.display = 'none';
        if (googleDivider) googleDivider.style.display = 'none';
        if (inAppNote) inAppNote.style.display = 'block';
        if (authEmailBtn) {
            authEmailBtn.setAttribute('data-i18n', 'modals.auth_btn_register');
            authEmailBtn.innerText = t('modals.auth_btn_register');
        }
        if (authModalDesc) {
            authModalDesc.setAttribute('data-i18n', 'modals.auth_desc_register');
            authModalDesc.innerHTML = t('modals.auth_desc_register');
        }
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
    const totalPages = getShowcaseTotalPages(_showcaseShuffled.length);
    if (_showcasePage < 1) _showcasePage = 1;
    if (_showcasePage > totalPages) _showcasePage = totalPages;

    const { start, count } = getShowcaseRange(_showcasePage);
    const items = _showcaseShuffled.slice(start, start + count);

    const uploadCard = _showcasePage === 1 ? `
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
        </div>` : '';

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

    // Pagination controls
    let pagerEl = document.getElementById('showcase-pager');
    if (!pagerEl) {
        pagerEl = document.createElement('div');
        pagerEl.id = 'showcase-pager';
        pagerEl.className = 'pager';
        gallery.parentNode.appendChild(pagerEl);
    }
    let pagerHtml = '';
    if (_showcasePage > 1) pagerHtml += `<button class="pager-btn" onclick="window.renderShowcase(${_showcasePage - 1})">‹</button>`;
    for (let i = 1; i <= totalPages; i++) {
        pagerHtml += `<button class="pager-btn${i === _showcasePage ? ' active' : ''}" onclick="window.renderShowcase(${i})">${i}</button>`;
    }
    if (_showcasePage < totalPages) pagerHtml += `<button class="pager-btn" onclick="window.renderShowcase(${_showcasePage + 1})">›</button>`;
    pagerEl.innerHTML = pagerHtml;

    // Lazy load images
    gallery.querySelectorAll('img[data-src]').forEach(el => {
        const obs = new IntersectionObserver((entries) => {
            entries.forEach(e => { if (e.isIntersecting) { el.src = el.dataset.src; delete el.dataset.src; obs.unobserve(el); } });
        }, { rootMargin: '200px' });
        obs.observe(el);
    });

    initPremiumEffects();
    window.scrollTo({ top: 0, behavior: 'smooth' });
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
    const { auth, GoogleAuthProvider, signInWithPopup } = window.firebase;
    const provider = new GoogleAuthProvider();
    try {
        await signInWithPopup(auth, provider);
        window.focus(); // Đưa focus về lại tab hiện tại sau khi popup đóng
        showToast(t('common.toast_login_success'));
    } catch (error) {
        console.error("Login Error", error);
        window.focus();
        const code = error?.code || '';
        const hint = code === 'auth/unauthorized-domain'
            ? ' — thêm kaling.cloud vào Firebase Authorized domains'
            : code === 'auth/operation-not-allowed'
                ? ' — bật Google Sign-In trong Firebase Authentication'
                : code === 'auth/popup-closed-by-user'
                    ? ' — bạn đã đóng cửa sổ Google'
                    : code
                        ? ` (${code})`
                        : '';
        showToast(t('common.toast_login_failed') + hint);
    }
}

async function logout() {
    const { auth, signOut } = window.firebase;
    try {
        await signOut(auth);
        showToast(t('common.toast_logout_success'));
    } catch (error) {
        console.error("Logout Error", error);
    }
}

// --- Email/Password Auth ---

// --- User Profile & Coin Balance ---
async function handleUserLoggedIn(user) {
    const { db, doc, getDoc, setDoc, onSnapshot, collection, query, where } = window.firebase;

    // Ẩn Auth Modal bắt buộc
    const authModal = document.getElementById('auth-modal');
    if (authModal) authModal.style.display = 'none';

    // Hiển thị Profile Menu thay vì ghi đè HTML
    document.getElementById('login-btn').style.display = 'none';
    document.getElementById('user-profile-menu').style.display = 'block';
    const navbarCoin = document.getElementById('navbar-coin-widget');
    if (navbarCoin) navbarCoin.style.display = 'flex';
    document.getElementById('dropdown-user-name').innerText = user.displayName || user.email.split('@')[0];
    document.getElementById('dropdown-user-email').innerText = user.email;

    // Avatar for user menu button
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

    // Hiển thị Profile Menu
    const dashIn = document.getElementById('dashboard-logged-in');
    const dashOut = document.getElementById('dashboard-auth-placeholder');
    if (dashIn) dashIn.style.display = 'block';
    if (dashOut) dashOut.style.display = 'none';

    // Xử lý hành động đang chờ (ví dụ: mở modal tạo đơn sau khi login)
    if (window.pendingAction === 'openOrderModal') {
        window.pendingAction = null;
        setTimeout(() => {
            window.openOrderModal();
        }, 500);
    }

    // TikTok Pixel: Identify User for Advanced Matching
    if (typeof ttq !== 'undefined' && user.email) {
        ttq.identify({
            email: user.email
        });
        console.log("🎯 TikTok Pixel: Identified user for Advanced Matching");
    }
    updateMetaAdvancedMatching(user);

    // Firebase/Google Identify
    if (user.email) {
        trackAnalyticsEvent('login', { method: 'email' });
        console.log("🎯 Firebase Analytics: User identified");
    }

    const userRef = doc(db, "users", user.uid);
    const userSnap = await getDoc(userRef);

    // Bootstrap Super Admin from hardcoded list to Database
    const isBootstrapSuperAdmin = SUPER_ADMIN_EMAILS.includes(user.email);

    if (!userSnap.exists()) {
        const defaultName = user.displayName || user.email.split('@')[0];
        const defaultPhoto = user.photoURL || "https://www.gravatar.com/avatar/00000000000000000000000000000000?d=mp&f=y";

        // Resolve pending referral code (if any) before creating user doc.
        // Wrapped in try/catch so any affiliate error never blocks signup.
        let referredBy = null;
        try {
            const pendingCode = getPendingReferralCode();
            if (pendingCode) {
                const refCodeSnap = await getDoc(doc(db, "referralCodes", pendingCode));
                if (refCodeSnap.exists()) {
                    const refUid = refCodeSnap.data().uid;
                    if (refUid && refUid !== user.uid) {
                        referredBy = refUid;
                        console.log('[Referral] Linking new user to referrer:', refUid);
                    } else {
                        console.log('[Referral] Self-referral or invalid code, skipped.');
                    }
                } else {
                    console.log('[Referral] Pending code not found in DB, skipped:', pendingCode);
                }
            }
        } catch (e) {
            console.warn('[Referral] Resolve referredBy failed (non-blocking):', e.message);
        }

        const newUserPayload = {
            uid: user.uid,
            displayName: defaultName,
            email: user.email,
            photoURL: defaultPhoto,
            coins: 0,
            promo1CoinCount: 0,
            promo1CoinLastDay: '',
            role: isBootstrapSuperAdmin ? 'super-admin' : 'user', // Tự động gán role vào DB
            createdAt: window.firebase.serverTimestamp(),
            updatedAt: window.firebase.serverTimestamp()
        };
        if (referredBy) newUserPayload.referredBy = referredBy;

        await setDoc(userRef, newUserPayload);

        trackMetaEvent('CompleteRegistration', {
            value: 0,
            currency: 'VND',
            status: true,
            content_name: user.providerData?.[0]?.providerId || 'signup'
        });

        // Clear the pending ref code after a successful signup attempt.
        if (referredBy) {
            try { clearPendingReferralCode(); } catch (e) { }
        }

        // Gửi thông báo Telegram khi có user mới đăng ký
        // sendTelegramMessage(`🆕 <b>USER MỚI ĐĂNG KÝ!</b>\n👤 Tên: ${escapeHTML(defaultName)}\n📧 Email: ${escapeHTML(user.email)}\n🕐 Thời gian: ${new Date().toLocaleString('vi-VN')}`);
    } else {
        // Nếu đã có user nhưng email thuộc list bootstrap mà chưa có role admin thì cập nhật
        const userData = userSnap.data();
        if (isBootstrapSuperAdmin && userData.role !== 'super-admin') {
            await window.firebase.updateDoc(userRef, { role: 'super-admin' });
        }
    }

    fbSub('userProfile', onSnapshot(userRef, (snapshot) => {
        if (snapshot.exists()) {
            const data = snapshot.data();
            window.__currentUserData = data;
            const currentCoins = data.coins || 0;
            if (FB_CACHE.myOrders) {
                syncPromo1CoinState(FB_CACHE.myOrders, data);
                ensureUserPromoFieldsSynced(FB_CACHE.myOrders, data);
                updateFirstOrderUI();
            }

            // [TỐI ƯU] KHÔNG còn log 'login' event ở đây nữa.
            // Listener này fire mỗi khi user.coins / role / v.v. thay đổi (nhiều lần),
            // log 'login' ở đây sẽ làm sai lệch analytics + tốn write phụ.
            // Login event đã được log đúng ở callback đăng nhập rồi.

            // Tự động nhận biết nạp coin thành công
            const topupModal = document.getElementById('topup-modal');
            if (topupModal && topupModal.style.display === 'flex' && currentCoins > initialCoinsBeforeTopup) {
                showToast(t('common.toast_coins_added'));
                closeModal('topup-modal');
                // Hiệu ứng pháo hoa hoặc rung nhẹ balance
                document.querySelectorAll('.coin-balance-text').forEach(el => {
                    el.classList.add('coin-update-glow');
                    setTimeout(() => el.classList.remove('coin-update-glow'), 2000);
                });

                // Notify Telegram
                const addedCoins = currentCoins - initialCoinsBeforeTopup;

                // Firebase Analytics (GA4): Purchase — chỉ bắn 1 lần
                const purchaseValue = selectedTopupPackage ? selectedTopupPackage.amount : addedCoins * 1000;
                const purchaseId = selectedTopupPackage ? selectedTopupPackage.id : 'coin_topup';
                const purchaseName = selectedTopupPackage ? selectedTopupPackage.name : 'Coin Topup';
                logFirebaseEvent('purchase', {
                    value: purchaseValue,
                    currency: 'VND',
                    transaction_id: `topup_${Date.now()}`,
                    items: [{ item_id: purchaseId, item_name: purchaseName }]
                });

                // TikTok Pixel: CompletePayment
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

                sendTelegramMessage(`💰 <b>NẠP COIN THÀNH CÔNG!</b>\n👤 Khách: ${escapeHTML(data.displayName)}\n📧 Email: ${escapeHTML(data.email)}\n✨ Đã cộng: +${addedCoins} Coin\n💰 Số dư mới: ${currentCoins} Coin`);
            }

            document.querySelectorAll('.coin-balance-text').forEach(el => el.innerText = currentCoins);
            document.querySelectorAll('.user-greeting-text').forEach(el => el.innerText = t('dashboard.greeting', { name: data.displayName }));
            document.querySelectorAll('.user-email-text').forEach(el => el.innerText = data.email);

            // Check Admin Rights từ Database
            const isAdmin = data.role === 'admin' || data.role === 'super-admin';
            const isSuperAdmin = data.role === 'super-admin';

            // [TỐI ƯU] Lưu trạng thái admin vào window để các nơi khác đọc.
            // KHÔNG còn auto-call loadAdminPanel ở đây nữa - hàm đó sẽ chỉ chạy khi
            // admin click vào trang Admin Panel (hook vào showAdminPanel).
            // Trước đây: mỗi khi user.coins đổi -> listener fire -> loadAdminPanel
            // -> +2 listener (orders + topups) leak liên tục.
            window.__currentUserData = data;
            window.__isAdmin = isAdmin;
            window.__isSuperAdmin = isSuperAdmin;

            if (isAdmin) {
                const adminProfileItem = document.getElementById('admin-dropdown-item-profile');
                if (adminProfileItem) adminProfileItem.style.display = 'flex';
                const adminDivider = document.getElementById('admin-dropdown-divider');
                if (adminDivider) adminDivider.style.display = 'block';

                if (isSuperAdmin) {
                    const purgeBtn = document.getElementById('btn-purge-inactive-users');
                    if (purgeBtn) purgeBtn.style.display = 'inline-flex';
                    const tabUsersEl = document.getElementById('tab-users');
                    if (tabUsersEl) tabUsersEl.style.display = 'block';
                }

                // [TỐI ƯU - DEFENSIVE] Nếu user đang xem admin panel ngay lúc này
                // (ví dụ: refresh trang khi đang ở admin, hoặc vừa được cấp quyền admin
                // và đã navigate vào admin panel) -> đảm bảo có subscription.
                // Hàm subscribeAdmin* có guard idempotent (fbHas) nên KHÔNG leak
                // dù listener này fire nhiều lần.
                const adminPanelEl = document.getElementById('admin-panel');
                if (adminPanelEl && adminPanelEl.style.display === 'block') {
                    loadAdminPanel();
                }
            } else {
                const purgeBtn = document.getElementById('btn-purge-inactive-users');
                if (purgeBtn) purgeBtn.style.display = 'none';
                const adminProfileItem = document.getElementById('admin-dropdown-item-profile');
                if (adminProfileItem) adminProfileItem.style.display = 'none';
                const adminDivider = document.getElementById('admin-dropdown-divider');
                if (adminDivider) adminDivider.style.display = 'none';

                // Nếu user vừa bị gỡ quyền admin -> cleanup admin listener đang sống
                fbUnsub('adminOrders');
                fbUnsub('adminTopups');
                fbUnsub('adminUsers');
                fbUnsub('adminReferrals');

                const adminPanelEl = document.getElementById('admin-panel');
                if (adminPanelEl) adminPanelEl.style.display = 'none';
            }
        }
    }));



    loadMyOrders();
    loadMyTopups();
    refreshReferralAllowance(user).finally(() => navigateFromURLParam());
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
    // In TikTok/FB in-app browser: only show Chrome/Safari prompt, not login
    if (isInAppBrowser()) {
        showInAppBrowserBanner();
        const authModalHidden = document.getElementById('auth-modal');
        if (authModalHidden) authModalHidden.style.display = 'none';
    } else {
        const authModal = document.getElementById('auth-modal');
        if (authModal) authModal.style.display = 'flex';
    }
    const v = document.getElementById('auth-banner-video');
    if (v && !v.src) {
        v.src = 'https://pub-2b53cd37b4a44642afdbb8bb470bde66.r2.dev/banner.mp4';
    }

    document.getElementById('login-btn').style.display = 'flex';
    document.getElementById('user-profile-menu').style.display = 'none';
    const navbarCoin = document.getElementById('navbar-coin-widget');
    if (navbarCoin) navbarCoin.style.display = 'none';

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
    window.__isSuperAdmin = false;
    window.__currentUserData = null;
    adminSubscribedOrderStatus = null;
    adminSubscribedTopupStatus = null;
    Object.keys(FB_CACHE).forEach(k => { delete FB_CACHE[k]; });

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
}

function showTopupHistory() {
    hideAllPages();
    document.getElementById('topup-history-page').style.display = 'block';
    window.scrollTo(0, 0);
}

function showBuildChannel() {
    hideAllPages();
    document.getElementById('build-channel-page').style.display = 'block';
    window.scrollTo(0, 0);
}

function showAdminPanel() {
    hideAllPages();
    document.getElementById('admin-panel').style.display = 'block';
    window.scrollTo(0, 0);
    // [TỐI ƯU] Chỉ subscribe admin Firebase listener khi admin VÀO trang admin.
    // Trước đây listener được tạo từ trong user-profile listener -> chạy sai chỗ.
    if (window.__isAdmin) loadAdminPanel();
}

function showLanding() {
    // Home = My videos
    showDashboard();
}

function hideAllPages() {
    const pages = ['landing-page', 'user-dashboard', 'topup-history-page', 'admin-panel', 'build-channel-page', 'referral-page'];
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

    // [TỐI ƯU - MỨC 3] Khi rời khỏi trang admin -> unsub các listener admin để
    // không còn read khi admin không xem panel. Khi quay lại sẽ subscribe lại.
    // (Listener của user thường: myOrders/myTopups giữ nguyên vì user có thể nhận
    // toast khi đơn hàng chuyển trạng thái dù đang ở landing page.)
    if (target !== 'admin-panel') {
        fbUnsub('adminOrders');
        fbUnsub('adminTopups');
        fbUnsub('adminUsers');
        fbUnsub('adminReferrals');
        fbUnsub('adminReferralAllowlist');
        fbUnsub('adminBots');
        adminSubscribedOrderStatus = null;
        adminSubscribedTopupStatus = null;
    }

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
                maxDurationSec: MAX_VIDEO_DURATION_SEC
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

window.selectTemplate = (id, url) => {
    document.querySelectorAll('.template-item').forEach(el => el.classList.remove('active'));
    const item = document.getElementById(`tpl-${id}`);
    if (item) item.classList.add('active');
    document.getElementById('selected-template-url').value = url;
    window.currentVideoSource = 'library';
    const trend = TREND_VIDEOS.find(t => t.id === id);
    showToast(t('modals.toast_trend_selected', { title: trend ? trendTitle(trend) : id }));
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

    const { db, collection, addDoc, updateDoc, serverTimestamp, query, where, getDocs } = window.firebase;
    let transferContent = "";
    const TOPUP_PREFIX = "KL"; // Prefix Casso — Kaling (kaling.cloud)
    
    try {
        const q = query(
            collection(db, "topups"),
            where("userId", "==", currentUser.uid),
            where("status", "==", "pending"),
            where("packageName", "==", selectedTopupPackage.name)
        );
        
        const snapshot = await getDocs(q);
        
        if (!snapshot.empty) {
            const existingRef = snapshot.docs[0].ref;
            const existingDoc = snapshot.docs[0].data();
            const staleCoins = Number(existingDoc.coins) !== Number(selectedTopupPackage.coins);
            const staleAmount = Number(existingDoc.amount) !== Number(selectedTopupPackage.amount);

            if (staleCoins || staleAmount) {
                const randomStr = Math.random().toString(36).substring(2, 6).toUpperCase();
                transferContent = `${TOPUP_PREFIX}${selectedTopupPackage.coins}${randomStr}`;
                await updateDoc(existingRef, {
                    packageId: selectedTopupPackage.id,
                    coins: selectedTopupPackage.coins,
                    amount: selectedTopupPackage.amount,
                    transferContent,
                    updatedAt: serverTimestamp()
                });
                console.log("♻️ Cập nhật đơn pending (gói đổi coin/giá):", transferContent, selectedTopupPackage.coins, "coin");
            } else {
                transferContent = existingDoc.transferContent;
                console.log("♻️ Tái sử dụng đơn nạp tiền cũ đang chờ:", transferContent);
            }
        } else {
            const randomStr = Math.random().toString(36).substring(2, 6).toUpperCase();
            transferContent = `${TOPUP_PREFIX}${selectedTopupPackage.coins}${randomStr}`;
            
            await addDoc(collection(db, "topups"), {
                userId: currentUser.uid,
                userEmail: currentUser.email,
                userName: currentUser.displayName,
                packageId: selectedTopupPackage.id,
                packageName: selectedTopupPackage.name,
                coins: selectedTopupPackage.coins,
                amount: selectedTopupPackage.amount,
                transferContent: transferContent,
                status: "pending",
                createdAt: serverTimestamp(),
                isAutomated: true
            });
            console.log("📝 Đã tạo bản ghi nạp tiền mới:", transferContent);
        }
    } catch (err) {
        console.error("Lỗi khi kiểm tra/tạo bản ghi nạp tiền:", err);
        const randomStr = Math.random().toString(36).substring(2, 6).toUpperCase();
        transferContent = `${TOPUP_PREFIX}${selectedTopupPackage.coins}${randomStr}`;
    }

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

function updateFirstOrderUI() {
    const costEl = document.getElementById('submit-cost');
    const offerBanner = document.getElementById('first-order-offer-banner');
    const guestOfferBar = document.getElementById('guest-offer-bar');
    const modelGroupEl = document.getElementById('model-selection-group');

    if (offerBanner) offerBanner.style.display = 'none';
    if (guestOfferBar) guestOfferBar.style.display = 'none';
    if (modelGroupEl) modelGroupEl.style.display = 'block';

    if (costEl) {
        const submitBtn = document.getElementById('order-submit-btn');
        const submitText = submitBtn ? submitBtn.querySelector('[data-i18n="hero.cta_create"]') : null;
        const summaryEl = document.getElementById('submit-summary-line');
        const checkedModel = document.querySelector('input[name="model-type"]:checked');
        const modelKey = checkedModel ? checkedModel.value : 'fast';

        costEl.innerText = String(modelCoinCost(modelKey));
        if (submitBtn) submitBtn.classList.remove('btn-first-offer');
        if (submitText) submitText.innerText = t('hero.cta_create');
        if (summaryEl) {
            summaryEl.innerText = t(`modals.model_${modelKey}_desc`);
            summaryEl.style.color = '';
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
    const videoRes = await fetch(meta.videoUrl, {
        headers: { Referer: 'https://www.tiktok.com/' }
    });
    if (!videoRes.ok) {
        throw Object.assign(new Error('video_download'), { code: 'video_download' });
    }
    return { blob: await videoRes.blob(), duration: meta.duration };
}

async function downloadTikTokVideoBlob(pageUrl) {
    if (!isTikTokPageUrl(pageUrl)) {
        throw Object.assign(new Error('invalid_url'), { code: 'invalid_url' });
    }
    try {
        return await downloadTikTokBlobViaWorker(pageUrl);
    } catch (workerErr) {
        console.warn('[TikTok] API proxy unavailable, trying direct:', workerErr?.code || workerErr);
        return await downloadTikTokBlobDirect(pageUrl);
    }
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

async function loadFfmpegForTrim() {
    if (!_ffmpegLoadPromise) {
        _ffmpegLoadPromise = (async () => {
            const { FFmpeg } = await import('https://cdn.jsdelivr.net/npm/@ffmpeg/ffmpeg@0.12.10/dist/esm/index.js');
            const { toBlobURL, fetchFile } = await import('https://cdn.jsdelivr.net/npm/@ffmpeg/util@0.12.1/dist/esm/index.js');
            const ffmpeg = new FFmpeg();
            const coreBase = 'https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.6/dist/esm';
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

async function trimVideoBlobToMaxSec(blob, maxSec = MAX_VIDEO_DURATION_SEC) {
    let duration;
    try {
        duration = await getBlobVideoDurationSec(blob);
    } catch (_) {
        duration = Infinity;
    }
    if (isFinite(duration) && duration <= maxSec + 0.15) {
        return { blob, trimmed: false };
    }

    const { ffmpeg, fetchFile } = await loadFfmpegForTrim();
    const inputName = 'tiktok_in.mp4';
    const outputName = 'tiktok_out.mp4';
    await ffmpeg.writeFile(inputName, await fetchFile(blob));

    try {
        await ffmpeg.exec(['-i', inputName, '-t', String(maxSec), '-c', 'copy', '-movflags', '+faststart', outputName]);
    } catch (_) {
        await ffmpeg.exec([
            '-i', inputName,
            '-t', String(maxSec),
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '28',
            '-c:a', 'aac',
            '-b:a', '96k',
            '-movflags', '+faststart',
            outputName
        ]);
    }

    const outData = await ffmpeg.readFile(outputName);
    try {
        await ffmpeg.deleteFile(inputName);
        await ffmpeg.deleteFile(outputName);
    } catch (_) { /* ignore */ }

    const outBytes = outData instanceof Uint8Array ? outData : new Uint8Array(outData);
    return {
        blob: new Blob([outBytes], { type: 'video/mp4' }),
        trimmed: true
    };
}

async function applyTikTokVideoFromUrl(pageUrl, options = {}) {
    const { onProgress } = options;
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
    const needsTrim = blobDuration > MAX_VIDEO_DURATION_SEC + 0.15;

    if (needsTrim) {
        onProgress?.('trimming');
        try {
            const trimmed = await trimVideoBlobToMaxSec(blob, MAX_VIDEO_DURATION_SEC);
            blob = trimmed.blob;
        } catch (trimErr) {
            console.error('[TikTok] trim failed:', trimErr);
            throw Object.assign(new Error(t('modals.tiktok_trim_failed')), { code: 'trim_failed' });
        }
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
        maxDurationSec: MAX_VIDEO_DURATION_SEC,
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
        const { trimmed } = await applyTikTokVideoFromUrl(pageUrl, {
            onProgress: (phase) => {
                if (phase === 'trimming' && btn) btn.textContent = t('modals.tiktok_trimming');
                if (phase === 'trimming') showToast(t('modals.tiktok_trimming'));
            }
        });
        showToast(trimmed ? t('modals.tiktok_fetch_trimmed') : t('modals.tiktok_fetch_success'));
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

    const maxDurationSec = options.maxDurationSec ?? MAX_VIDEO_DURATION_SEC;

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
        if (duration > maxDurationSec + 0.15) {
            showToast(t('modals.video_duration_limit'));
            if (options.inputId) {
                const input = document.getElementById(options.inputId);
                if (input) input.value = '';
            }
            container.innerHTML = '';
            syncUploadZonePreviewState(container);
            return;
        }

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
            maxDurationSec: MAX_VIDEO_DURATION_SEC
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
        radio.addEventListener('change', (e) => {
            updateFirstOrderUI();
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
                // Nếu chưa đăng nhập thì hiện Auth Modal
                const authModal = document.getElementById('auth-modal');
                if (authModal) authModal.style.display = 'flex';
                showToast(t('common.toast_login_required'));
                return;
            }

            const { db, doc, collection, runTransaction, serverTimestamp } = window.firebase;
            const submitBtn = document.getElementById('order-submit-btn');
            const progressDiv = document.getElementById('upload-progress');

            try {
                const charFile = document.getElementById('file-char').files[0];
                let videoFile = document.getElementById('file-video')?.files?.[0];
                const templateUrl = document.getElementById('selected-template-url')?.value || '';
                const tiktokUrl = document.getElementById('tiktok-video-url')?.value?.trim() || '';
                const modelKeySelected = document.querySelector('input[name="model-type"]:checked')?.value || 'fast';
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
                    submitBtn.disabled = true;
                    const mainTextFetch = submitBtn.querySelector('[data-i18n="hero.cta_create"]');
                    if (mainTextFetch) mainTextFetch.innerText = t('modals.tiktok_fetching');
                    showToast(t('modals.tiktok_fetch_on_submit'));
                    try {
                        const result = await applyTikTokVideoFromUrl(tiktokUrl, {
                            onProgress: (phase) => {
                                if (phase === 'trimming' && mainTextFetch) {
                                    mainTextFetch.innerText = t('modals.tiktok_trimming');
                                }
                            }
                        });
                        videoFile = result.file;
                    } catch (tiktokErr) {
                        console.error('[TikTok] auto fetch on submit:', tiktokErr);
                        submitBtn.disabled = false;
                        updateFirstOrderUI();
                        showToast(tiktokErr.code ? tiktokErrorMessage(tiktokErr.code) : (tiktokErr.message || t('modals.tiktok_fetch_failed')));
                        return;
                    }
                }

                if (window.currentVideoSource === 'upload' && !videoFile) {
                    return showToast(t('modals.video_upload_required'));
                }

                // Model thường: auto select Aidancing id by uploaded video duration
                // <10s  -> 125
                // 10-30 -> 124
                if (window.currentVideoSource === 'upload' && videoFile) {
                    const dur = await getVideoDurationSeconds(videoFile);
                    if (typeof dur === 'number') {
                        if (dur > MAX_VIDEO_DURATION_SEC) {
                            return showToast(t('modals.video_duration_limit'));
                        }
                        if (modelKeySelected === 'fast') {
                            modelIdOverride = dur < 10 ? '125' : '124';
                        }
                    }
                }

                // Kiểm tra lại lần cuối trước khi upload
                if (charFile.size > MAX_CHAR_FILE_BYTES) return showToast(t('modals.char_size_limit'));
                if (window.currentVideoSource === 'upload' && videoFile && videoFile.size > MAX_VIDEO_FILE_BYTES) {
                    return showToast(t('modals.video_size_limit'));
                }

                // Show loading
                submitBtn.disabled = true;
                const mainTextInitial = submitBtn.querySelector('[data-i18n="hero.cta_create"]');
                if (mainTextInitial) mainTextInitial.innerText = t('common.loading');
                progressDiv.style.display = 'block';

                // 1. Check coins first (Transaction)
                const userRef = doc(db, "users", currentUser.uid);
                const userSnap = await runTransaction(db, async (transaction) => {
                    const userDoc = await transaction.get(userRef);
                    const modelKey = modelKeySelected;
                    const serviceType = document.querySelector('input[name="service-type"]:checked').value;
                    let model = normalizeOrderCost({ ...localizedModel(modelKey) });
                    if (modelIdOverride) model.modelId = modelIdOverride;

                    if (userDoc.data().coins < model.cost) {
                        throw t('modals.insufficient_coins_title');
                    }
                    return { currentCoins: userDoc.data().coins, model, serviceType };
                });

                const { model, serviceType } = userSnap;

                console.log("Starting process");
                const mainText = submitBtn.querySelector('[data-i18n="hero.cta_create"]');
                if (mainText) mainText.innerText = t('modals.uploading');

                console.log("📤 Đang tải ảnh nhân vật...");
                const charUrl = await uploadFile(charFile, "characters");
                showToast(t('common.success'));

                let videoUrl = "";
                if (window.currentVideoSource === 'library') {
                    videoUrl = document.getElementById('selected-template-url').value;
                    if (!videoUrl) throw new Error(t('modals.template_required'));
                    console.log("🔗 Sử dụng video mẫu từ thư viện:", videoUrl);
                } else {
                    console.log("📤 Đang tải video tham chiếu...");
                    videoUrl = await uploadFile(videoFile, "motions");
                    showToast(t('common.success'));
                }

                const orderId = await runTransaction(db, async (transaction) => {
                    const userDoc = await transaction.get(userRef);
                    const userData = userDoc.data();
                    const currentCoins = userData.coins;
                    normalizeOrderCost(model);

                    const aspectRatioEl = document.querySelector('input[name="aspect-ratio"]:checked');
                    const aspectRatio = aspectRatioEl ? aspectRatioEl.value : '16:9';

                    transaction.update(userRef, {
                        coins: currentCoins - model.cost,
                        updatedAt: serverTimestamp()
                    });

                    const orderRef = doc(collection(db, "orders"));
                    transaction.set(orderRef, {
                        userId: currentUser.uid,
                        userEmail: currentUser.email,
                        userName: currentUser.displayName,
                        packageName: model.name,
                        modelId: model.modelId,
                        serviceType: serviceType,
                        serviceLabel: SERVICE_TYPE_MAP()[serviceType] || serviceType,
                        costCoins: model.cost,
                        promo1Coin: !!model.promo1Coin,
                        characterImageLink: charUrl,
                        referenceVideoLink: videoUrl,
                        aspectRatio: aspectRatio,
                        status: "pending",
                        resultLink: "",
                        adminNote: "",
                        createdAt: serverTimestamp(),
                        updatedAt: serverTimestamp()
                    });
                    return orderRef.id;
                });

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
                    window.niceConfirm({
                        title: t('modals.insufficient_coins_title'),
                        message: t('modals.insufficient_coins_msg'),
                        icon: "💰",
                        onConfirm: () => {
                            closeModal('order-modal');
                            if (window.openPricingModal) window.openPricingModal();
                        }
                    });
                } else if (error === t('modals.promo1coin_daily_limit') || error === t('modals.promo1coin_max_reached')) {
                    showToast(error);
                    syncPromo1CoinState(FB_CACHE.myOrders || [], window.__currentUserData);
                    updateFirstOrderUI();
                } else {
                    showToast(t('common.error') + ": " + error);
                }
            } finally {
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
    if (!currentUser) return;

    // Đã có listener đang sống -> chỉ re-render từ cache, không re-subscribe
    if (fbHas('myOrders')) {
        renderMyOrders();
        return;
    }

    const { db, collection, query, where, onSnapshot } = window.firebase;
    const q = query(
        collection(db, "orders"),
        where("userId", "==", currentUser.uid)
    );

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

    let isFirstLoad = true;
    fbSub('myOrders', onSnapshot(q, (snapshot) => {
        // Toast khi có order thay đổi trạng thái
        if (!isFirstLoad) {
            snapshot.docChanges().forEach(change => {
                if (change.type === "modified") {
                    const data = change.doc.data();
                    const orderId = change.doc.id.substring(change.doc.id.length - 6).toUpperCase();
                    const statusVN = STATUS_MAP()[data.status] || data.status;
                    if (data.status === 'completed') {
                        showToast(t('notifications.order_completed', { id: orderId }));
                    } else {
                        showToast(t('notifications.order_status_changed', { id: orderId, status: statusVN }));
                    }
                }
            });
        }
        isFirstLoad = false;

        // Cache snapshot data
        FB_CACHE.myOrders = snapshot.docs.map(d => ({ id: d.id, ...d.data() }));

        orderCount = snapshot.size;
        syncPromo1CoinState(FB_CACHE.myOrders, window.__currentUserData);
        ensureUserPromoFieldsSynced(FB_CACHE.myOrders, window.__currentUserData);
        console.log("🔍 loadMyOrders: orderCount =", orderCount, "promo1Coin =", promo1CoinStats);
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
        return;
    }

    const sortedDocs = [...docs].sort((a, b) => {
        const timeA = a.createdAt?.seconds || 0;
        const timeB = b.createdAt?.seconds || 0;
        return timeB - timeA;
    });

    if (countText) countText.innerText = `${sortedDocs.length} Videos`;

    grid.innerHTML = sortedDocs.map(d => {
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
}


// [TỐI ƯU] Tách subscribe & render. Subscribe 1 lần, re-render miễn phí khi đổi ngôn ngữ.
function loadMyTopups() {
    if (!currentUser) return;

    if (fbHas('myTopups')) {
        renderMyTopups();
        return;
    }

    const { db, collection, query, where, onSnapshot } = window.firebase;
    const q = query(
        collection(db, "topups"),
        where("userId", "==", currentUser.uid)
    );
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

    let isFirstLoadTopup = true;
    fbSub('myTopups', onSnapshot(q, (snapshot) => {
        // Toast khi có topup approved/rejected
        if (!isFirstLoadTopup) {
            snapshot.docChanges().forEach(change => {
                if (change.type === "modified") {
                    const data = change.doc.data();
                    if (data.status === 'approved') {
                        showToast(t('notifications.topup_approved', { pkg: data.packageName }));
                    } else if (data.status === 'rejected') {
                        showToast(t('notifications.topup_rejected', { pkg: data.packageName }));
                    }
                }
            });
        }
        isFirstLoadTopup = false;

        FB_CACHE.myTopups = snapshot.docs.map(d => ({ id: d.id, ...d.data() }));
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
                <td>${d.coins}</td>
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

// --- Admin Dashboard Logic ---
window.switchAdminTab = (tabName) => {
    document.querySelectorAll('.admin-tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.admin-tab-content').forEach(content => content.classList.remove('active'));

    const btn = document.querySelector(`button[onclick*="switchAdminTab('${tabName}')"]`);
    if (btn) btn.classList.add('active');
    const contentEl = document.getElementById(`admin-tab-${tabName}`);
    if (contentEl) contentEl.classList.add('active');

    // [TỐI ƯU - MỨC 3] Chỉ subscribe đúng tab đang active. Tab khác -> unsub.
    adminActiveTab = tabName;
    refreshActiveAdminSubscription();
};

window.makeAdmin = async () => {
    const email = document.getElementById('user-admin-email').value.trim();
    if (!email) return showToast(t('admin.toast_email_required'));

    const { db, collection, query, where, getDocs, updateDoc, doc } = window.firebase;
    const q = query(collection(db, "users"), where("email", "==", email));
    const querySnapshot = await getDocs(q);

    if (querySnapshot.empty) return showToast(t('admin.toast_user_not_found'));

    const userDoc = querySnapshot.docs[0];
    await updateDoc(doc(db, "users", userDoc.id), { role: 'admin' });
    showToast(t('admin.toast_admin_granted', { email }));
    document.getElementById('user-admin-email').value = '';
};

// ----- USERS (Super-admin only tab) -----
function subscribeAdminUsers() {
    const { db, collection, onSnapshot, query, orderBy, limit } = window.firebase;

    if (fbHas('adminUsers')) {
        renderAdminUsers();
        return;
    }

    const q = query(
        collection(db, "users"),
        orderBy("createdAt", "desc"),
        limit(ADMIN_QUERY_LIMIT * 2) // users ít thay đổi, cho phép 200
    );

    fbSub('adminUsers', onSnapshot(q, (snapshot) => {
        FB_CACHE.adminUsers = snapshot.docs.map(d => ({ id: d.id, ...d.data() }));
        FB_CACHE.adminUsersTruncated = snapshot.size === ADMIN_QUERY_LIMIT * 2;
        renderAdminUsers();
    }));
}

function renderAdminUsers() {
    const list = document.getElementById('admin-users-list');
    if (!list) return;

    const searchVal = document.getElementById('admin-search-input')?.value.toLowerCase() || "";

    const hasFullCache = !!FB_CACHE.adminUsersFull;
    const allDocs = (searchVal && hasFullCache)
        ? FB_CACHE.adminUsersFull
        : (FB_CACHE.adminUsers || []);

    const filteredDocs = allDocs.filter(d => {
        const text = `${d.displayName || ''} ${d.email || ''}`.toLowerCase();
        return text.includes(searchVal);
    });

    // Empty state khi đang search + bị truncate -> mời user search rộng
    if (filteredDocs.length === 0 && searchVal && FB_CACHE.adminUsersTruncated && !hasFullCache) {
        list.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:2rem;">
            <div style="opacity:0.7; margin-bottom: 1rem;">${t('admin.search_not_found_users', { query: searchVal, limit: ADMIN_QUERY_LIMIT * 2 })}</div>
            <button class="btn-primary" onclick="window.fetchAllAdminCollection('users')" style="padding: 8px 16px;">${t('admin.search_full_btn')}</button>
        </td></tr>`;
        document.getElementById('admin-users-pagination')?.remove();
        return;
    }

    const ITEMS_PER_PAGE = 10;
    if (!window.currentAdminUserPage) window.currentAdminUserPage = 1;
    const totalPages = Math.ceil(filteredDocs.length / ITEMS_PER_PAGE);

    if (window.currentAdminUserPage > totalPages && totalPages > 0) {
        window.currentAdminUserPage = totalPages;
    }

    const startIndex = (window.currentAdminUserPage - 1) * ITEMS_PER_PAGE;
    const pageData = filteredDocs.slice(startIndex, startIndex + ITEMS_PER_PAGE);

    list.innerHTML = pageData.map(d => {
        return `
            <tr>
                <td>
                    <div style="font-weight:600;">${escapeHTML(d.displayName || t('common.guest'))}</div>
                    <div style="font-size:0.75rem; opacity:0.6;">${escapeHTML(d.email || '')}</div>
                </td>
                <td>
                    <div style="display:flex; align-items:center; gap:8px;">
                        <input type="number" value="${d.coins || 0}" 
                               style="width: 80px; padding: 4px 8px; border-radius:4px; background:rgba(255,255,255,0.05); border:1px solid var(--glass-border); color:white;"
                               id="user-coins-${d.id}">
                        <button class="btn-primary" style="padding: 4px 8px; font-size:0.75rem;" 
                                onclick="window.updateUserCoins('${d.id}')">${t('common.save')}</button>
                    </div>
                </td>
                <td><span class="status-badge" style="background: ${d.role === 'admin' ? 'var(--primary)' : 'rgba(255,255,255,0.1)'}">${d.role || 'user'}</span></td>
                <td>
                    <div style="display:flex; gap:6px;">
                        <button class="btn-secondary" style="padding: 4px 8px; font-size:0.75rem; white-space:nowrap;" onclick="window.makeAdminDirect('${d.id}', '${d.role}')">
                            ${d.role === 'admin' ? t('admin.revoke_admin') : t('admin.make_admin')}
                        </button>
                        <button class="btn-secondary" style="padding: 4px 8px; font-size:0.75rem; color: #ff1744; border-color: rgba(255, 23, 68, 0.3);"
                                onclick="window.deleteUserAdmin('${d.id}')">
                            ${t('common.delete')}
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');

    let paginationContainer = document.getElementById('admin-users-pagination');
    if (!paginationContainer) {
        paginationContainer = document.createElement('div');
        paginationContainer.id = 'admin-users-pagination';
        paginationContainer.style.display = 'flex';
        paginationContainer.style.justifyContent = 'center';
        paginationContainer.style.alignItems = 'center';
        paginationContainer.style.gap = '15px';
        paginationContainer.style.marginTop = '20px';
        list.parentElement.parentElement.appendChild(paginationContainer);
    }

    let infoNote = '';
    if (hasFullCache) {
        infoNote = `<span style="font-size:0.7rem; color: #4ade80; margin-left:10px;">${t('admin.search_full_active', { count: FB_CACHE.adminUsersFull.length })}</span>`;
    } else if (FB_CACHE.adminUsersTruncated) {
        infoNote = `<span style="font-size:0.7rem; opacity:0.6; margin-left:10px;">${t('admin.search_truncated_hint', { limit: ADMIN_QUERY_LIMIT * 2 })}${searchVal ? ` — <a href="#" onclick="event.preventDefault(); window.fetchAllAdminCollection('users')" style="color:#ffde00;">${t('admin.search_full_btn')}</a>` : ''}</span>`;
    }

    if (totalPages > 1) {
        paginationContainer.innerHTML = `
            <button class="btn-secondary" style="padding: 6px 12px;" onclick="window.changeAdminUserPage(${window.currentAdminUserPage - 1})" ${window.currentAdminUserPage === 1 ? 'disabled' : ''}>${t('common.pagination_prev')}</button>
            <span>${t('common.pagination_page', { current: window.currentAdminUserPage, total: totalPages })}${infoNote}</span>
            <button class="btn-secondary" style="padding: 6px 12px;" onclick="window.changeAdminUserPage(${window.currentAdminUserPage + 1})" ${window.currentAdminUserPage === totalPages ? 'disabled' : ''}>${t('common.pagination_next')}</button>
        `;
    } else {
        paginationContainer.innerHTML = infoNote;
    }
}

// Public alias (giữ tương thích các nơi đang gọi)
window.loadAdminUsers = () => {
    if (!window.__isAdmin) return;
    subscribeAdminUsers();
};

// [TỐI ƯU] Đổi trang -> chỉ render lại
window.changeAdminUserPage = (newPage) => {
    window.currentAdminUserPage = newPage;
    renderAdminUsers();
};

// ----- BOTS (Admin tab) -----
let _renderAdminBotsTimer = null;

function scheduleRenderAdminBots() {
    if (_renderAdminBotsTimer) clearTimeout(_renderAdminBotsTimer);
    _renderAdminBotsTimer = setTimeout(() => {
        _renderAdminBotsTimer = null;
        renderAdminBots();
    }, 400);
}

const RENDER_PROVIDER_BOT_ID = 'kaling_vps_bot';

let adminActiveRenderProvider = 'xiaoyang';

function normalizeRenderProvider(value) {
    const p = (value || 'xiaoyang').toString().trim().toLowerCase();
    return ['aidancing', 'xiaoyang', 'videoaieasy'].includes(p) ? p : 'xiaoyang';
}

function subscribeAdminRenderProvider() {
    if (!window.__isAdmin) return;
    if (fbHas('adminRenderProvider')) {
        renderAdminRenderProviderUI();
        return;
    }
    const { db, doc, onSnapshot } = window.firebase;
    fbSub('adminRenderProvider', onSnapshot(doc(db, 'bots', RENDER_PROVIDER_BOT_ID), (snap) => {
        const d = snap.exists() ? snap.data() : {};
        adminActiveRenderProvider = normalizeRenderProvider(
            d.activeRenderProvider || d.activeProvider
        );
        renderAdminRenderProviderUI();
    }, (err) => {
        console.error('Admin render provider error:', err);
    }));
}

function renderAdminRenderProviderUI() {
    const activeEl = document.getElementById('admin-render-provider-active');
    const queueEl = document.getElementById('admin-render-provider-queue');
    const btnAd = document.getElementById('admin-rp-aidancing');
    const btnXy = document.getElementById('admin-rp-xiaoyang');
    const btnVae = document.getElementById('admin-rp-videoaieasy');
    const p = adminActiveRenderProvider;
    if (activeEl) {
        activeEl.textContent = p === 'videoaieasy'
            ? t('admin.render_provider_active_vae')
            : p === 'xiaoyang'
                ? t('admin.render_provider_active_xy')
                : t('admin.render_provider_active_ad');
        activeEl.style.color = p === 'videoaieasy' ? '#fbbf24' : p === 'xiaoyang' ? '#a78bfa' : '#4ade80';
    }
    if (btnAd) btnAd.style.outline = p === 'aidancing' ? '2px solid #4ade80' : '';
    if (btnXy) btnXy.style.outline = p === 'xiaoyang' ? '2px solid #a78bfa' : '';
    if (btnVae) btnVae.style.outline = p === 'videoaieasy' ? '2px solid #fbbf24' : '';
    if (queueEl) {
        refreshRenderProviderQueueHint(queueEl);
    }
}

async function refreshRenderProviderQueueHint(el) {
    if (!window.__isAdmin || !el) return;
    try {
        const { db, collection, query, where, getDocs } = window.firebase;
        const snap = await getDocs(query(collection(db, 'orders'), where('status', '==', 'processing')));
        let ad = 0;
        let xy = 0;
        let vae = 0;
        snap.forEach(d => {
            const x = d.data();
            let rp = x.renderProvider;
            if (!rp) {
                if (x.videoaieasyJobId) rp = 'videoaieasy';
                else if (x.xiaoyangTaskId) rp = 'xiaoyang';
                else rp = 'aidancing';
            }
            if (rp === 'videoaieasy') vae++;
            else if (rp === 'xiaoyang') xy++;
            else ad++;
        });
        el.textContent = t('admin.render_provider_processing', { ad, xy, vae });
    } catch (e) {
        el.textContent = '';
    }
}

window.setRenderProvider = async (provider) => {
    if (!window.__isAdmin) return;
    provider = normalizeRenderProvider(provider);
    const { db, doc, updateDoc, serverTimestamp } = window.firebase;
    try {
        await updateDoc(doc(db, 'bots', RENDER_PROVIDER_BOT_ID), {
            activeRenderProvider: provider,
            updatedAt: serverTimestamp(),
            updatedBy: currentUser?.email || ''
        });
        showToast(provider === 'videoaieasy'
            ? t('admin.render_provider_toast_vae')
            : provider === 'xiaoyang'
                ? t('admin.render_provider_toast_xy')
                : t('admin.render_provider_toast_ad'));
    } catch (e) {
        showToast(t('common.error_with_msg', { msg: e.message }));
    }
};

function subscribeAdminBots() {
    if (!window.__isAdmin) return;

    subscribeAdminRenderProvider();

    if (fbHas('adminBots')) {
        renderAdminBots();
        return;
    }

    const { db, collection, onSnapshot } = window.firebase;
    fbSub('adminBots', onSnapshot(collection(db, 'bots'), (snapshot) => {
        FB_CACHE.adminBots = snapshot.docs.map(d => ({ id: d.id, ...d.data() }));
        scheduleRenderAdminBots();
    }, (err) => {
        console.error('Admin bots snapshot error:', err);
        showToast(t('admin.toast_load_error', { msg: err.message }));
    }));
}

function renderAdminBots() {
    const list = document.getElementById('admin-bots-list');
    if (!list) return;

    const rows = (FB_CACHE.adminBots || []).slice().sort((a, b) => {
        const ta = safeToDate(a.startedAt)?.getTime() || safeToDate(a.createdAt)?.getTime() || 0;
        const tb = safeToDate(b.startedAt)?.getTime() || safeToDate(b.createdAt)?.getTime() || 0;
        return tb - ta;
    });

    if (rows.length === 0) {
        list.innerHTML = `<tr><td colspan="5" style="text-align:center; opacity:0.5; padding:2rem;">${t('admin.bots_empty')}</td></tr>`;
        return;
    }

    list.innerHTML = rows.map(b => {
        const started = safeToDate(b.startedAt) || safeToDate(b.createdAt);
        const startedStr = started
            ? started.toLocaleString(currentLang === 'en' ? 'en-US' : 'vi-VN')
            : '—';
        const enabled = !!b.enabled;
        const runLabel = enabled ? t('admin.bots_running') : t('admin.bots_stopped');
        const runColor = enabled ? '#27ae60' : '#c0392b';

        return `
            <tr>
                <td>
                    <div style="font-weight:700; font-family: monospace;">${escapeHTML(b.displayName || b.name || b.id)}</div>
                    <small style="opacity:0.55;">ID: ${escapeHTML(b.id)}</small>
                </td>
                <td>
                    <div style="display:flex; align-items:center; gap:0.75rem; flex-wrap:wrap;">
                        <span style="color:${runColor}; font-weight:600; font-size:0.85rem;">${runLabel}</span>
                        <button class="btn-secondary" style="padding:4px 12px; font-size:0.75rem; ${enabled ? 'background:#c0392b;' : 'background:#27ae60;'}"
                            onclick='window.setBotEnabled(${JSON.stringify(b.id)}, ${!enabled})'>
                            ${enabled ? t('admin.bots_btn_off') : t('admin.bots_btn_on')}
                        </button>
                    </div>
                </td>
                <td>${startedStr}</td>
                <td><small style="opacity:0.7;">${escapeHTML(b.hostname || '—')}</small></td>
                <td>
                    <button type="button" class="btn-delete" style="padding: 6px 10px; background: rgba(255,59,48,0.1); border: 1px solid rgba(255,59,48,0.2); border-radius: 6px; cursor: pointer; color: #ff3b30; font-size: 0.75rem;"
                        onclick='window.deleteBot(event, ${JSON.stringify(b.id)})' title="${t('admin.bots_btn_delete')}">
                        ${t('admin.bots_btn_delete')}
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

window.setBotEnabled = async (botId, enabled) => {
    if (!window.__isAdmin) return;
    const { db, doc, updateDoc, serverTimestamp } = window.firebase;
    try {
        await updateDoc(doc(db, 'bots', botId), {
            enabled: !!enabled,
            updatedAt: serverTimestamp(),
            updatedBy: currentUser?.email || ''
        });
        showToast(enabled ? t('admin.bots_toast_on', { name: botId }) : t('admin.bots_toast_off', { name: botId }));
    } catch (e) {
        showToast(t('common.error_with_msg', { msg: e.message }));
    }
};

window.deleteBot = (event, botId) => {
    event.stopPropagation();
    event.preventDefault();
    if (!window.__isAdmin) return;
    window.niceConfirm({
        title: t('modals.confirm_order_title') || 'Xác nhận',
        message: t('admin.confirm_delete_bot', { name: botId }),
        icon: '🗑️',
        onConfirm: async () => {
            const { db, doc, deleteDoc } = window.firebase;
            try {
                await deleteDoc(doc(db, 'bots', botId));
                showToast(t('admin.toast_bot_deleted', { name: botId }));
            } catch (e) {
                console.error(e);
                showToast(t('admin.toast_bot_delete_error', { msg: e.message }));
            }
        }
    });
};

// ----- REFERRALS (Admin tab) -----
function subscribeAdminReferralAllowlist() {
    const { db, collection, onSnapshot, query, orderBy } = window.firebase;
    if (fbHas('adminReferralAllowlist')) {
        renderAdminReferralAllowlist();
        return;
    }
    const q = query(collection(db, 'referralAllowlist'), orderBy('addedAt', 'desc'));
    fbSub('adminReferralAllowlist', onSnapshot(q, (snapshot) => {
        FB_CACHE.adminReferralAllowlist = snapshot.docs.map((d) => ({ id: d.id, ...d.data() }));
        renderAdminReferralAllowlist();
    }, (err) => {
        console.error('Admin referral allowlist error:', err);
        const list = document.getElementById('referral-allowlist-list');
        if (list) {
            list.innerHTML = `<p style="opacity:0.6;margin:0;">${t('admin.ref_allowlist_rules_hint')}</p>`;
        }
    }));
}

function renderAdminReferralAllowlist() {
    const list = document.getElementById('referral-allowlist-list');
    if (!list) return;
    const rows = FB_CACHE.adminReferralAllowlist || [];
    if (!rows.length) {
        list.innerHTML = `<p style="opacity:0.6;margin:0;">${t('admin.ref_allowlist_empty')}</p>`;
        return;
    }
    list.innerHTML = rows.map((row) => `
        <div style="display:flex;align-items:center;justify-content:space-between;gap:0.75rem;padding:0.45rem 0.6rem;border-radius:8px;background:rgba(255,255,255,0.04);">
            <span style="font-family:monospace;">${escapeHTML(row.email || row.id)}</span>
            <button type="button" class="btn-secondary" style="padding:0.25rem 0.6rem;font-size:0.75rem;" onclick="window.removeReferralAllowlistEmail('${escapeHTML(row.id)}')">${t('admin.ref_allowlist_remove')}</button>
        </div>
    `).join('');
}

window.addReferralAllowlistEmail = async () => {
    if (!window.__isAdmin) return;
    const input = document.getElementById('referral-allowlist-input');
    const email = normalizeReferralAllowlistEmail(input?.value || '');
    if (!email || !email.includes('@')) {
        return showToast(t('admin.toast_email_required'));
    }
    const { db, doc, setDoc, serverTimestamp } = window.firebase;
    try {
        await setDoc(doc(db, 'referralAllowlist', email), {
            email,
            addedAt: serverTimestamp(),
            addedBy: currentUser?.email || '',
        });
        if (input) input.value = '';
        showToast(t('admin.ref_allowlist_added', { email }));
        if (currentUser?.email && normalizeReferralAllowlistEmail(currentUser.email) === email) {
            window.__referralAllowed = true;
            updateReferralNavVisibility(true);
        }
    } catch (e) {
        console.error('[Referral] add allowlist:', e);
        showToast(t('common.error_with_msg', { msg: e.message }));
    }
};

window.removeReferralAllowlistEmail = async (emailId) => {
    if (!window.__isAdmin) return;
    if (!confirm(t('admin.ref_allowlist_confirm_remove', { email: emailId }))) return;
    const { db, doc, deleteDoc } = window.firebase;
    try {
        await deleteDoc(doc(db, 'referralAllowlist', emailId));
        showToast(t('admin.ref_allowlist_removed'));
        if (currentUser?.email && normalizeReferralAllowlistEmail(currentUser.email) === emailId) {
            window.__referralAllowed = false;
            updateReferralNavVisibility(false);
        }
    } catch (e) {
        showToast(t('common.error_with_msg', { msg: e.message }));
    }
};

function subscribeAdminReferrals() {
    const { db, collection, onSnapshot, query, orderBy, limit } = window.firebase;

    if (fbHas('adminReferrals')) {
        enrichReferralReferrers()
            .then(() => renderAdminReferrals())
            .catch(() => renderAdminReferrals());
        return;
    }

    const q = query(
        collection(db, "referralEarnings"),
        orderBy("createdAt", "desc"),
        limit(ADMIN_QUERY_LIMIT * 2)
    );

    fbSub('adminReferrals', onSnapshot(q, async (snapshot) => {
        FB_CACHE.adminReferrals = snapshot.docs.map(d => ({ id: d.id, ...d.data() }));
        FB_CACHE.adminReferralsTruncated = snapshot.size === ADMIN_QUERY_LIMIT * 2;
        try {
            await enrichReferralReferrers();
        } catch (e) {
            console.warn('[Referral] enrichReferrers error:', e.message);
        }
        renderAdminReferrals();
    }, (err) => {
        console.error('Admin referrals snapshot error:', err);
        showToast(t('admin.toast_load_error', { msg: err.message }));
    }));
}

function renderAdminReferrals() {
    const list = document.getElementById('admin-referrals-list');
    const summaryEl = document.getElementById('admin-referral-summary');
    if (!list) return;

    const searchVal = document.getElementById('admin-search-input')?.value.toLowerCase() || '';
    const allRows = FB_CACHE.adminReferrals || [];

    const filtered = allRows.filter(d => {
        const money = getReferralMoneyFields(d);
        const ref = getReferrerDisplay(d);
        const text = [
            ref.name, ref.email, d.referrerId, d.referredUserName, d.referredUserEmail,
            d.gateway, formatReferralMoney(money.commissionAmount, money.currency)
        ].join(' ').toLowerCase();
        return text.includes(searchVal);
    });

    // Summary grouped by referrer
    const byReferrer = {};
    filtered.forEach(d => {
        const money = getReferralMoneyFields(d);
        const ref = getReferrerDisplay(d);
        const key = d.referrerId || 'unknown';
        if (!byReferrer[key]) {
            byReferrer[key] = {
                referrerId: key,
                referrerName: ref.name,
                referrerEmail: ref.email,
                vnd: 0,
                usd: 0,
                coins: 0,
                count: 0
            };
        }
        if (ref.name && ref.name !== '—' && byReferrer[key].referrerName === '—') {
            byReferrer[key].referrerName = ref.name;
        }
        if (ref.email && !byReferrer[key].referrerEmail) {
            byReferrer[key].referrerEmail = ref.email;
        }
        byReferrer[key].count += 1;
        byReferrer[key].coins += d.commissionCoins || 0;
        if (money.currency === 'USD' && money.commissionAmount) {
            byReferrer[key].usd += money.commissionAmount;
        } else if (money.commissionAmount) {
            byReferrer[key].vnd += money.commissionAmount;
        }
    });

    if (summaryEl) {
        const summaryRows = Object.values(byReferrer).sort((a, b) => b.vnd - a.vnd);
        if (summaryRows.length === 0) {
            summaryEl.innerHTML = `<div style="opacity:0.5; padding:1rem;">${t('referral.empty')}</div>`;
        } else {
            summaryEl.innerHTML = `
                <div style="overflow-x:auto;">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>${t('admin.ref_col_referrer')}</th>
                                <th>${t('admin.ref_col_total_vnd')}</th>
                                <th>${t('admin.ref_col_total_usd')}</th>
                                <th>${t('admin.ref_col_total_coins')}</th>
                                <th>${t('admin.ref_col_count')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${summaryRows.map(r => `
                                <tr>
                                    <td>
                                        <div style="font-weight:600;">${escapeHTML(r.referrerName)}</div>
                                        <small style="opacity:0.6;">${escapeHTML(r.referrerEmail)}</small>
                                    </td>
                                    <td style="color:#ffde00; font-weight:700;">${formatReferralMoney(r.vnd, 'VND')}</td>
                                    <td>${r.usd > 0 ? formatReferralMoney(r.usd, 'USD') : '—'}</td>
                                    <td>+${r.coins} Coin</td>
                                    <td>${r.count}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            `;
        }
    }

    if (filtered.length === 0) {
        list.innerHTML = `<tr><td colspan="6" style="text-align:center; opacity:0.5; padding:2rem;">${t('admin.search_no_results')}</td></tr>`;
        document.getElementById('admin-referrals-pagination')?.remove();
        return;
    }

    const ITEMS_PER_PAGE = 10;
    if (!window.currentAdminReferralPage) window.currentAdminReferralPage = 1;
    const totalPages = Math.ceil(filtered.length / ITEMS_PER_PAGE);
    if (window.currentAdminReferralPage > totalPages) window.currentAdminReferralPage = totalPages;

    const startIndex = (window.currentAdminReferralPage - 1) * ITEMS_PER_PAGE;
    const pageData = filtered.slice(startIndex, startIndex + ITEMS_PER_PAGE);

    list.innerHTML = pageData.map(d => {
        const money = getReferralMoneyFields(d);
        const ref = getReferrerDisplay(d);
        const dateStr = safeToDate(d.createdAt)
            ? safeToDate(d.createdAt).toLocaleString(currentLang === 'en' ? 'en-US' : 'vi-VN')
            : '—';
        return `
            <tr>
                <td>
                    <div style="font-weight:600;">${escapeHTML(ref.name)}</div>
                    <small style="opacity:0.6;">${escapeHTML(ref.email)}</small>
                </td>
                <td>
                    <div>${escapeHTML(d.referredUserName || t('common.guest'))}</div>
                    <small style="opacity:0.6;">${escapeHTML(d.referredUserEmail || '')}</small>
                </td>
                <td>
                    <div>${formatReferralMoney(money.baseAmount, money.currency)}</div>
                    <small style="opacity:0.55;">${d.baseCoins || 0} Coin</small>
                </td>
                <td style="color:#ffde00; font-weight:700;">
                    <div>${formatReferralMoney(money.commissionAmount, money.currency)}</div>
                    <small style="opacity:0.75;">+${d.commissionCoins || 0} Coin</small>
                </td>
                <td>${referralGatewayLabel(d.gateway)}</td>
                <td>${dateStr}</td>
            </tr>
        `;
    }).join('');

    let paginationContainer = document.getElementById('admin-referrals-pagination');
    if (!paginationContainer) {
        paginationContainer = document.createElement('div');
        paginationContainer.id = 'admin-referrals-pagination';
        paginationContainer.style.display = 'flex';
        paginationContainer.style.justifyContent = 'center';
        paginationContainer.style.alignItems = 'center';
        paginationContainer.style.gap = '15px';
        paginationContainer.style.marginTop = '20px';
        list.parentElement.parentElement.appendChild(paginationContainer);
    }

    if (totalPages > 1) {
        paginationContainer.innerHTML = `
            <button class="btn-secondary" style="padding: 6px 12px;" onclick="window.changeAdminReferralPage(${window.currentAdminReferralPage - 1})" ${window.currentAdminReferralPage === 1 ? 'disabled' : ''}>${t('common.pagination_prev')}</button>
            <span>${t('common.pagination_page', { current: window.currentAdminReferralPage, total: totalPages })}</span>
            <button class="btn-secondary" style="padding: 6px 12px;" onclick="window.changeAdminReferralPage(${window.currentAdminReferralPage + 1})" ${window.currentAdminReferralPage === totalPages ? 'disabled' : ''}>${t('common.pagination_next')}</button>
        `;
    } else {
        paginationContainer.innerHTML = '';
    }
}

window.changeAdminReferralPage = (newPage) => {
    window.currentAdminReferralPage = newPage;
    renderAdminReferrals();
};

window.updateUserCoins = async (userId) => {
    const { db, doc, updateDoc } = window.firebase;
    const input = document.getElementById(`user-coins-${userId}`);
    const newAmount = parseInt(input.value);
    
    if (isNaN(newAmount)) return showToast(t('admin.toast_invalid_amount'));

    try {
        await updateDoc(doc(db, "users", userId), { coins: newAmount });
        showToast(t('admin.toast_balance_updated'));
    } catch (e) {
        showToast(t('common.error_with_msg', { msg: e.message }));
    }
};

window.makeAdminDirect = async (userId, currentRole) => {
    const { db, doc, updateDoc } = window.firebase;
    const newRole = currentRole === 'admin' ? 'user' : 'admin';
    try {
        await updateDoc(doc(db, "users", userId), { role: newRole });
        showToast(t('admin.toast_role_changed', { role: newRole }));
    } catch (e) {
        showToast(t('common.error_with_msg', { msg: e.message }));
    }
};

window.deleteUserAdmin = async (userId) => {
    if (!confirm(t('admin.confirm_delete_user'))) return;
    const { db, doc, deleteDoc } = window.firebase;
    try {
        await deleteDoc(doc(db, "users", userId));
        showToast(t('admin.toast_user_deleted'));
    } catch (e) {
        showToast(t('common.error_with_msg', { msg: e.message }));
    }
};

const INACTIVE_USER_MIN_AGE_MS = 24 * 60 * 60 * 1000;
const FIRESTORE_PAGE_SIZE = 400;
const FIRESTORE_BATCH_DELETE_SIZE = 400;

async function fetchAllFirestoreDocs(collectionName) {
    const { db, collection, query, orderBy, getDocs, limit, startAfter } = window.firebase;
    const all = [];
    let cursor = null;
    for (;;) {
        const constraints = [orderBy('createdAt', 'desc'), limit(FIRESTORE_PAGE_SIZE)];
        if (cursor) constraints.push(startAfter(cursor));
        const snap = await getDocs(query(collection(db, collectionName), ...constraints));
        if (snap.empty) break;
        all.push(...snap.docs);
        cursor = snap.docs[snap.docs.length - 1];
        if (snap.size < FIRESTORE_PAGE_SIZE) break;
    }
    return all;
}

async function fetchAllFirestoreDocsSimple(collectionName) {
    const { db, collection, getDocs } = window.firebase;
    const snap = await getDocs(collection(db, collectionName));
    return snap.docs;
}

function collectUserIdsFromDocs(docs) {
    const ids = new Set();
    for (const d of docs) {
        const uid = d.data()?.userId;
        if (uid) ids.add(uid);
    }
    return ids;
}

function buildReferralProtectedUserIds(userDocs, referralEarningDocs, referralCodeDocs) {
    const ids = new Set();
    for (const d of userDocs) {
        const data = d.data() || {};
        if (data.referredBy) {
            ids.add(d.id);
            ids.add(data.referredBy);
        }
        if (data.referralCode) ids.add(d.id);
    }
    for (const d of referralEarningDocs) {
        const data = d.data() || {};
        if (data.referrerId) ids.add(data.referrerId);
        if (data.referredUserId) ids.add(data.referredUserId);
    }
    for (const d of referralCodeDocs) {
        const uid = d.data()?.uid;
        if (uid) ids.add(uid);
    }
    return ids;
}

function isInactiveGhostUser(userData, userId, cutoffMs, orderUserIds, topupUserIds, referralUserIds, selfUid) {
    if (!userData || userId === selfUid) return false;
    const role = userData.role || 'user';
    if (role === 'admin' || role === 'super-admin') return false;
    const created = safeToDate(userData.createdAt);
    if (!created || created.getTime() > cutoffMs) return false;
    if (orderUserIds.has(userId) || topupUserIds.has(userId)) return false;
    if (referralUserIds.has(userId)) return false;
    return true;
}

async function deleteUsersInBatches(userIds) {
    const { db, doc, writeBatch } = window.firebase;
    let deleted = 0;
    for (let i = 0; i < userIds.length; i += FIRESTORE_BATCH_DELETE_SIZE) {
        const chunk = userIds.slice(i, i + FIRESTORE_BATCH_DELETE_SIZE);
        const batch = writeBatch(db);
        chunk.forEach((uid) => batch.delete(doc(db, 'users', uid)));
        await batch.commit();
        deleted += chunk.length;
    }
    return deleted;
}

window.purgeInactiveUsers = async () => {
    if (!window.__isSuperAdmin) {
        return showToast(t('admin.purge_inactive_super_only'));
    }

    const btn = document.getElementById('btn-purge-inactive-users');
    if (btn) btn.disabled = true;
    showToast(t('admin.purge_inactive_scanning'));

    try {
        const cutoffMs = Date.now() - INACTIVE_USER_MIN_AGE_MS;
        const selfUid = window.currentUser?.uid || '';

        const [userDocs, orderDocs, topupDocs, referralEarningDocs, referralCodeDocs] = await Promise.all([
            fetchAllFirestoreDocs('users'),
            fetchAllFirestoreDocs('orders'),
            fetchAllFirestoreDocs('topups'),
            fetchAllFirestoreDocs('referralEarnings'),
            fetchAllFirestoreDocsSimple('referralCodes')
        ]);

        const orderUserIds = collectUserIdsFromDocs(orderDocs);
        const topupUserIds = collectUserIdsFromDocs(topupDocs);
        const referralUserIds = buildReferralProtectedUserIds(userDocs, referralEarningDocs, referralCodeDocs);

        const toDelete = [];
        for (const d of userDocs) {
            if (isInactiveGhostUser(d.data(), d.id, cutoffMs, orderUserIds, topupUserIds, referralUserIds, selfUid)) {
                toDelete.push({ id: d.id, email: d.data()?.email || '', displayName: d.data()?.displayName || '' });
            }
        }

        if (toDelete.length === 0) {
            showToast(t('admin.purge_inactive_none'));
            return;
        }

        const previewLines = toDelete.slice(0, 8).map((u) =>
            `• ${escapeHTML(u.displayName || t('common.guest'))} — ${escapeHTML(u.email || u.id)}`
        ).join('<br>');
        const moreNote = toDelete.length > 8
            ? `<br><i>…${t('admin.purge_inactive_and_more', { count: toDelete.length - 8 })}</i>`
            : '';

        window.niceConfirm({
            title: t('admin.purge_inactive_confirm_title'),
            message: t('admin.purge_inactive_confirm_msg', { count: toDelete.length }) +
                `<br><br><div style="text-align:left;font-size:0.85rem;opacity:0.9;max-height:180px;overflow:auto;">${previewLines}${moreNote}</div>`,
            icon: '🧹',
            onConfirm: async () => {
                const btn2 = document.getElementById('btn-purge-inactive-users');
                if (btn2) btn2.disabled = true;
                showToast(t('admin.purge_inactive_deleting', { count: toDelete.length }));
                try {
                    const deleted = await deleteUsersInBatches(toDelete.map((u) => u.id));
                    FB_CACHE.adminUsers = (FB_CACHE.adminUsers || []).filter((u) => !toDelete.some((x) => x.id === u.id));
                    if (FB_CACHE.adminUsersFull) {
                        FB_CACHE.adminUsersFull = FB_CACHE.adminUsersFull.filter((u) => !toDelete.some((x) => x.id === u.id));
                    }
                    renderAdminUsers();
                    showToast(t('admin.purge_inactive_done', { count: deleted }));
                } catch (e) {
                    console.error('purgeInactiveUsers:', e);
                    showToast(t('common.error_with_msg', { msg: e.message }));
                } finally {
                    if (btn2) btn2.disabled = false;
                }
            }
        });
    } catch (e) {
        console.error('purgeInactiveUsers scan:', e);
        showToast(t('common.error_with_msg', { msg: e.message }));
    } finally {
        if (btn) btn.disabled = false;
    }
};

window.approveTopup = async (topupId, userId, coins) => {
    if (!confirm(t('admin.confirm_approve_topup', { coins }))) return;

    const { db, doc, getDoc, runTransaction, serverTimestamp } = window.firebase;

    // Snapshot topup data before mutation (used later for referral)
    let topupSnapshot = null;
    try {
        const tSnap = await getDoc(doc(db, "topups", topupId));
        if (tSnap.exists()) topupSnapshot = tSnap.data();
    } catch (e) {
        console.warn('Could not pre-read topup doc:', e.message);
    }

    try {
        await runTransaction(db, async (transaction) => {
            const userRef = doc(db, "users", userId);
            const topupRef = doc(db, "topups", topupId);
            const userSnap = await transaction.get(userRef);
            if (!userSnap.exists()) throw "User không tồn tại!";

            const newCoins = (userSnap.data().coins || 0) + coins;
            transaction.update(userRef, { coins: newCoins, updatedAt: serverTimestamp() });
            transaction.update(topupRef, { status: 'approved' });
        });
        showToast(t('admin.toast_topup_approved'));

        // Affiliate / Referral - non-blocking, isolated
        try {
            await payReferralCommissionClient(topupId, userId, coins, 'admin', {
                userEmail: topupSnapshot ? topupSnapshot.userEmail : '',
                userName: topupSnapshot ? topupSnapshot.userName : '',
                baseAmount: topupSnapshot ? topupSnapshot.amount : null,
                currency: 'VND'
            });
        } catch (refErr) {
            console.error('[Referral] Admin commission error (non-blocking):', refErr);
            // Soft-fail; admin can still retry / inspect referralEarnings doc
        }
    } catch (e) {
        console.error(e);
        showToast(t('admin.toast_topup_approve_error'));
    }
};

window.rejectTopup = async (topupId) => {
    if (!confirm(t('admin.confirm_reject_topup'))) return;
    const { db, doc, updateDoc } = window.firebase;
    try {
        await updateDoc(doc(db, "topups", topupId), { status: 'rejected' });
        showToast(t('admin.toast_topup_rejected'));
    } catch (e) {
        showToast(t('admin.toast_update_error'));
    }
};

let currentAdminOrderId = null;
window.openAdminDetail = async (orderId) => {
    currentAdminOrderId = orderId;
    const { db, doc, getDoc } = window.firebase;
    const snap = await getDoc(doc(db, "orders", orderId));
    const d = snap.data();

    const shortOrderId = snap.id.substring(snap.id.length - 6).toUpperCase();
    document.getElementById('admin-order-details').innerHTML = `
        <div class="admin-info-grid">
            <div class="info-item">
                <span class="info-label">${t('admin.detail_order_id')}</span>
                <span class="info-value" style="font-family: monospace; font-weight: bold; color: var(--accent-primary);">#${shortOrderId}</span>
            </div>
            <div class="info-item">
                <span class="info-label">${t('admin.detail_customer')}</span>
                <span class="info-value">${d.userName} (${d.userEmail})</span>
            </div>
            <div class="info-item">
                <span class="info-label">${t('admin.detail_package')}</span>
                <span class="info-value">${d.packageName}</span>
            </div>
            <div class="info-item">
                <span class="info-label">${t('admin.detail_service_type')}</span>
                <span class="info-value" style="color: var(--accent); font-weight: bold;">${SERVICE_TYPE_MAP()[d.serviceType] || d.serviceType}</span>
            </div>
            <div class="info-item">
                <span class="info-label">${t('admin.detail_aspect')}</span>
                <span class="info-value">${d.aspectRatio || '16:9'}</span>
            </div>
            <div class="info-item">
                <span class="info-label">${t('admin.detail_char_image')}</span>
                <div class="admin-preview-box" onclick="window.viewFullImage('${d.characterImageLink}')">
                    <img src="${d.characterImageLink}">
                    <div class="preview-overlay">${t('modals.preview_expand')}</div>
                </div>
                <button class="download-pill-btn image-btn" style="margin-top: 10px; width: fit-content;" onclick="window.downloadUrl(event, '${d.characterImageLink}')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
                    ${t('admin.detail_download_char')}
                </button>
            </div>
            <div class="info-item">
                <span class="info-label">${t('admin.detail_ref_video')}</span>
                <div class="admin-preview-box" onclick="window.open('${d.referenceVideoLink}', '_blank')">
                    <video src="${d.referenceVideoLink}" muted loop onmouseover="this.play()" onmouseout="this.pause()"></video>
                    <div class="preview-overlay">${t('admin.detail_view_video')}</div>
                </div>
                <button class="download-pill-btn video-btn" style="margin-top: 10px; width: fit-content;" onclick="window.downloadUrl(event, '${d.referenceVideoLink}')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                    ${t('admin.detail_download_ref')}
                </button>
            </div>
            ${d.resultLink ? `
            <div class="info-item">
                <span class="info-label">${t('admin.detail_result_video')}</span>
                <div class="admin-preview-box" onclick="window.open('${d.resultLink}', '_blank')">
                    <video src="${d.resultLink}" muted loop onmouseover="this.play()" onmouseout="this.pause()"></video>
                    <div class="preview-overlay">${t('admin.detail_view_video')}</div>
                </div>
                <button class="download-pill-btn video-btn" style="margin-top: 10px; width: fit-content;" onclick="window.downloadUrl(event, '${d.resultLink}')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                    ${t('admin.detail_download_result')}
                </button>
            </div>
            ` : ''}
        </div>
    `;

    document.getElementById('admin-status').value = d.status;
    document.getElementById('admin-result-link').value = d.resultLink || "";
    document.getElementById('admin-note').value = d.adminNote || "";

    openModal('admin-detail-modal');
};

document.getElementById('admin-update-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const { db, doc, getDoc, updateDoc, serverTimestamp } = window.firebase;
    const newStatus = document.getElementById('admin-status').value;
    const resultLink = document.getElementById('admin-result-link').value;

    try {
        // 1. Update Firestore
        await updateDoc(doc(db, "orders", currentAdminOrderId), {
            status: newStatus,
            resultLink: resultLink,
            adminNote: document.getElementById('admin-note').value,
            updatedAt: serverTimestamp()
        });

        showToast(t('admin.toast_order_updated'));
        closeModal('admin-detail-modal');

        // 2. If status is completed, send automated email
        const snap = await getDoc(doc(db, "orders", currentAdminOrderId));
        if (snap.exists()) {
            const orderData = snap.data();
            const shortId = currentAdminOrderId.substring(currentAdminOrderId.length - 6).toUpperCase();
            
            // Bắn email
            if (newStatus === 'completed' && orderData.userEmail) {
                sendCompletionEmail(currentAdminOrderId, orderData);
            }

            // Bắn Telegram thông báo trạng thái cập nhật thủ công
            let teleMsg = '';
            if (newStatus === 'processing') {
                teleMsg = `⚙️ <b>ĐƠN HÀNG ĐANG XỬ LÝ (Mã #${shortId})</b>\n👤 Khách: ${escapeHTML(orderData.userName || 'Khách hàng')}\n📧 Email: ${escapeHTML(orderData.userEmail || 'N/A')}\n⏳ Trạng thái: Admin chuyển trạng thái sang xử lý.`;
            } else if (newStatus === 'completed') {
                teleMsg = `✅ <b>ĐƠN HÀNG HOÀN THÀNH (Mã #${shortId})</b>\n👤 Khách: ${escapeHTML(orderData.userName || 'Khách hàng')}\n📧 Email: ${escapeHTML(orderData.userEmail || 'N/A')}\n📹 Kết quả: <a href="${resultLink}">Xem kết quả</a>`;
            } else if (newStatus === 'failed') {
                teleMsg = `❌ <b>ĐƠN HÀNG THẤT BẠI (Mã #${shortId})</b>\n👤 Khách: ${escapeHTML(orderData.userName || 'Khách hàng')}\n📧 Email: ${escapeHTML(orderData.userEmail || 'N/A')}\n📝 Lý do: ${escapeHTML(document.getElementById('admin-note').value || 'Không hợp lệ')}`;
            }
            if (teleMsg) {
                sendTelegramMessage(teleMsg);
            }
        }
    } catch (error) {
        console.error(error);
        showToast(t('admin.toast_order_update_error'));
    }
});

let currentTopupStatus = 'pending';
let currentOrderStatus = 'pending';

window.switchTopupSubTab = (status) => {
    currentTopupStatus = status;
    document.querySelectorAll('#admin-tab-topups .sub-tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-status') === status);
    });
    window.currentAdminTopupPage = 1;
    // Invalidate full cache vì status đã đổi (data set khác)
    delete FB_CACHE.adminTopupsFull;
    delete FB_CACHE.adminTopupsFullStatus;
    // [TỐI ƯU] Đổi sub-tab -> chỉ subscribe lại topups (orders/users không động vào)
    subscribeAdminTopups();
};

window.switchOrderSubTab = (status) => {
    currentOrderStatus = status;
    document.querySelectorAll('#admin-tab-orders .sub-tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-status') === status);
    });
    window.currentAdminOrderPage = 1;
    delete FB_CACHE.adminOrdersFull;
    delete FB_CACHE.adminOrdersFullStatus;
    subscribeAdminOrders();
};

window.deleteOrder = async (event, orderId) => {
    event.stopPropagation();
    if (!confirm(t('admin.confirm_delete_order'))) return;
    const { db, doc, deleteDoc } = window.firebase;
    try {
        await deleteDoc(doc(db, "orders", orderId));
        showToast(t('admin.toast_order_deleted'));
    } catch (e) {
        console.error(e);
        showToast(t('admin.toast_order_delete_error'));
    }
};

window.deleteTopup = async (event, topupId) => {
    event.stopPropagation();
    if (!confirm(t('admin.confirm_delete_topup'))) return;
    const { db, doc, deleteDoc } = window.firebase;
    try {
        await deleteDoc(doc(db, "topups", topupId));
        showToast(t('admin.toast_topup_deleted'));
    } catch (e) {
        console.error(e);
        showToast(t('admin.toast_topup_delete_error'));
    }
};

// =====================================================================
// ADMIN PANEL — KIẾN TRÚC TỐI ƯU FIREBASE READS
// =====================================================================
// Trước đây loadAdminPanel() làm 2 việc cùng lúc và bị gọi loạn xạ:
//   - Tạo onSnapshot mới cho TOPUPS + ORDERS (KHÔNG unsub cái cũ -> leak)
//   - Render UI dựa trên search/pagination
// Bị gọi từ: search keystroke (mỗi ký tự), sub-tab switch, đổi trang,
// và TỆ NHẤT là từ user-profile listener (mỗi lần coin đổi).
//
// Giải pháp:
//   1) Tách rõ "subscribe" vs "render". Subscribe gắn vào FB_LISTENERS registry.
//   2) Search input -> debounce 300ms -> chỉ render lại từ cache, KHÔNG re-subscribe.
//   3) Pagination -> chỉ render lại, KHÔNG re-subscribe.
//   4) Switch sub-tab (đổi status filter) -> unsub cũ + sub query mới (vì where khác).
//   5) Switch tab (orders/topups/users) -> unsub các tab khác (Mức 3: subscribe per active tab).
//   6) Tất cả query admin có orderBy('createdAt','desc') + limit(100) (Mức 2).

let adminActiveTab = 'orders';            // 'orders' | 'topups' | 'users' | 'referrals' | 'bots'
let adminSubscribedOrderStatus = null;    // status đang sub cho orders
let adminSubscribedTopupStatus = null;    // status đang sub cho topups
let adminSearchDebounceTimer = null;
const ADMIN_QUERY_LIMIT = 100;            // chỉ realtime-listen 100 doc mới nhất

// =====================================================================
// SEARCH IN FULL COLLECTION (one-shot, không listener)
// =====================================================================
// Default search chỉ tìm trong limit(100) realtime cache. Nếu admin cần tìm
// đơn cũ hơn (ngoài top 100), bấm nút "Tìm trong toàn bộ" -> 1 lần getDocs
// không limit, cache vào FB_CACHE.adminXxxFull, search trên đó.
// Cache full bị huỷ khi đổi sub-tab (vì where status khác).
window.fetchAllAdminCollection = async function (type) {
    if (!window.__isAdmin) return;
    const { db, collection, query, where, getDocs, orderBy } = window.firebase;

    let q;
    let cacheKey, statusKey, statusVal;

    if (type === 'orders') {
        statusVal = currentOrderStatus;
        q = query(collection(db, 'orders'), where('status', '==', statusVal), orderBy('createdAt', 'desc'));
        cacheKey = 'adminOrdersFull';
        statusKey = 'adminOrdersFullStatus';
    } else if (type === 'topups') {
        statusVal = currentTopupStatus;
        q = query(collection(db, 'topups'), where('status', '==', statusVal), orderBy('createdAt', 'desc'));
        cacheKey = 'adminTopupsFull';
        statusKey = 'adminTopupsFullStatus';
    } else if (type === 'users') {
        q = query(collection(db, 'users'), orderBy('createdAt', 'desc'));
        cacheKey = 'adminUsersFull';
        statusKey = null;
    } else {
        return;
    }

    showToast(t('admin.toast_loading_all'));
    try {
        const snapshot = await getDocs(q);
        FB_CACHE[cacheKey] = snapshot.docs.map(d => ({ id: d.id, ...d.data() }));
        if (statusKey) FB_CACHE[statusKey] = statusVal;

        if (type === 'orders') renderAdminOrders();
        else if (type === 'topups') renderAdminTopups();
        else if (type === 'users') renderAdminUsers();

        showToast(t('admin.toast_loaded_records', { count: snapshot.size }));
    } catch (e) {
        console.error('Fetch all error:', e);
        showToast(t('admin.toast_load_error', { msg: e.message }));
    }
};

function setupAdminSearchInputOnce() {
    if (window.adminSearchInited) return;
    const input = document.getElementById('admin-search-input');
    if (!input) return;
    input.addEventListener('input', () => {
        // Debounce: gõ liền tù tì 5 ký tự chỉ render 1 lần
        clearTimeout(adminSearchDebounceTimer);
        adminSearchDebounceTimer = setTimeout(() => {
            // Reset về trang 1 mỗi khi search đổi
            window.currentAdminOrderPage = 1;
            window.currentAdminTopupPage = 1;
            window.currentAdminUserPage = 1;
            window.currentAdminReferralPage = 1;
            if (adminActiveTab === 'orders') renderAdminOrders();
            else if (adminActiveTab === 'topups') renderAdminTopups();
            else if (adminActiveTab === 'users') renderAdminUsers();
            else if (adminActiveTab === 'referrals') renderAdminReferrals();
            else if (adminActiveTab === 'bots') renderAdminBots();
        }, 300);
    });
    window.adminSearchInited = true;
}

// Entry point chính: gọi khi admin VÀO trang admin panel (showAdminPanel)
// hoặc khi cần re-load full panel (vd: sau xoá đơn).
function loadAdminPanel() {
    console.log("Loading Admin Panel...");
    if (!window.__isAdmin) return;
    setupAdminSearchInputOnce();
    refreshActiveAdminSubscription();
}

// Đảm bảo CHỈ tab đang active có subscription. Các tab khác được unsub.
function refreshActiveAdminSubscription() {
    if (!window.__isAdmin) {
        fbUnsub('adminOrders');
        fbUnsub('adminTopups');
        fbUnsub('adminUsers');
        fbUnsub('adminReferrals');
        fbUnsub('adminReferralAllowlist');
        fbUnsub('adminBots');
        fbUnsub('adminRenderProvider');
        return;
    }

    if (adminActiveTab === 'orders') {
        fbUnsub('adminTopups');
        fbUnsub('adminUsers');
        fbUnsub('adminReferrals');
        fbUnsub('adminBots');
        fbUnsub('adminRenderProvider');
        subscribeAdminOrders();
    } else if (adminActiveTab === 'topups') {
        fbUnsub('adminOrders');
        fbUnsub('adminUsers');
        fbUnsub('adminReferrals');
        fbUnsub('adminBots');
        fbUnsub('adminRenderProvider');
        subscribeAdminTopups();
    } else if (adminActiveTab === 'users') {
        fbUnsub('adminOrders');
        fbUnsub('adminTopups');
        fbUnsub('adminReferrals');
        fbUnsub('adminBots');
        fbUnsub('adminRenderProvider');
        subscribeAdminUsers();
    } else if (adminActiveTab === 'referrals') {
        fbUnsub('adminOrders');
        fbUnsub('adminTopups');
        fbUnsub('adminUsers');
        fbUnsub('adminBots');
        fbUnsub('adminRenderProvider');
        subscribeAdminReferrals();
        subscribeAdminReferralAllowlist();
    } else if (adminActiveTab === 'bots') {
        fbUnsub('adminOrders');
        fbUnsub('adminTopups');
        fbUnsub('adminUsers');
        fbUnsub('adminReferrals');
        subscribeAdminBots();
    }
}

// ----- TOPUPS -----
function subscribeAdminTopups() {
    const { db, collection, query, where, onSnapshot, orderBy, limit } = window.firebase;
    const status = currentTopupStatus;

    // Đã sub cho status này rồi -> chỉ render từ cache (zero read)
    if (fbHas('adminTopups') && adminSubscribedTopupStatus === status) {
        renderAdminTopups();
        return;
    }
    adminSubscribedTopupStatus = status;

    const q = query(
        collection(db, "topups"),
        where("status", "==", status),
        orderBy("createdAt", "desc"),
        limit(ADMIN_QUERY_LIMIT)
    );
    fbSub('adminTopups', onSnapshot(q, (snapshot) => {
        FB_CACHE.adminTopups = snapshot.docs.map(d => ({ id: d.id, ...d.data() }));
        FB_CACHE.adminTopupsTruncated = snapshot.size === ADMIN_QUERY_LIMIT;
        renderAdminTopups();
    }, (error) => {
        console.error("Topups Snapshot Error:", error);
        showToast(t('admin.toast_topups_load_error', { msg: error.message }));
    }));
}

function renderAdminTopups() {
    const list = document.getElementById('admin-topups-list');
    if (!list) return;

    const searchVal = document.getElementById('admin-search-input')?.value.toLowerCase() || "";

    // Nếu user đã bấm "Tìm trong toàn bộ" cho status hiện tại -> dùng full cache
    const hasFullCache = !!FB_CACHE.adminTopupsFull && FB_CACHE.adminTopupsFullStatus === currentTopupStatus;
    const allDocs = (searchVal && hasFullCache)
        ? FB_CACHE.adminTopupsFull
        : (FB_CACHE.adminTopups || []);

    if (allDocs.length === 0) {
        list.innerHTML = `<tr><td colspan="5" style="text-align:center; opacity:0.5; padding:2rem;">${t('status.empty_topups_msg')}</td></tr>`;
        document.getElementById('admin-topups-pagination')?.remove();
        return;
    }

    const filteredDocs = allDocs.filter(d => {
        const text = `${d.userName} ${d.userEmail} ${d.transferContent} ${d.packageName}`.toLowerCase();
        return text.includes(searchVal);
    });

    if (filteredDocs.length === 0) {
        // Nếu đang search + data đã bị truncate + chưa load full -> mời user bấm tìm rộng
        if (searchVal && FB_CACHE.adminTopupsTruncated && !hasFullCache) {
            list.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:2rem;">
                <div style="opacity:0.7; margin-bottom: 1rem;">${t('admin.search_not_found_topups', { query: searchVal, limit: ADMIN_QUERY_LIMIT })}</div>
                <button class="btn-primary" onclick="window.fetchAllAdminCollection('topups')" style="padding: 8px 16px;">${t('admin.search_full_btn')}</button>
            </td></tr>`;
        } else {
            list.innerHTML = `<tr><td colspan="5" style="text-align:center; opacity:0.5; padding:2rem;">${t('admin.search_no_results')}</td></tr>`;
        }
        document.getElementById('admin-topups-pagination')?.remove();
        return;
    }

    // Group by User (sort users by their latest request)
    const userLatestTime = {};
    filteredDocs.forEach(d => {
        const time = d.createdAt?.toMillis ? d.createdAt.toMillis() : (d.createdAt || 0);
        if (!userLatestTime[d.userId] || time > userLatestTime[d.userId]) {
            userLatestTime[d.userId] = time;
        }
    });

    const dataList = [...filteredDocs].sort((a, b) => {
        if (a.userId !== b.userId) {
            return userLatestTime[b.userId] - userLatestTime[a.userId];
        }
        const timeA = a.createdAt?.toMillis ? a.createdAt.toMillis() : (a.createdAt || 0);
        const timeB = b.createdAt?.toMillis ? b.createdAt.toMillis() : (b.createdAt || 0);
        return timeB - timeA;
    });

    const ITEMS_PER_PAGE = 10;
    if (!window.currentAdminTopupPage) window.currentAdminTopupPage = 1;
    const totalPages = Math.ceil(dataList.length / ITEMS_PER_PAGE);

    if (window.currentAdminTopupPage > totalPages && totalPages > 0) {
        window.currentAdminTopupPage = totalPages;
    }

    const startIndex = (window.currentAdminTopupPage - 1) * ITEMS_PER_PAGE;
    const pageData = dataList.slice(startIndex, startIndex + ITEMS_PER_PAGE);

    let lastUserId = null;
    let groupColor = 'transparent';
    const groupColors = ['rgba(255, 255, 255, 0.03)', 'transparent'];
    let colorIdx = 0;

    list.innerHTML = pageData.map(d => {
        if (d.userId !== lastUserId) {
            groupColor = groupColors[colorIdx % 2];
            colorIdx++;
            lastUserId = d.userId;
        }
        const safeUrl = d.proofLink ? d.proofLink.replace(/'/g, "\\'") : '';
        const createdDateObj = safeToDate(d.createdAt);
        const dateStr = createdDateObj ? createdDateObj.toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' }) : '';
        return `
            <tr style="background: ${groupColor}; transition: background 0.3s ease;">
                <td>
                    <div>${escapeHTML(d.userName) || 'N/A'}</div>
                    <small style="opacity:0.6;">${escapeHTML(d.userEmail) || ''}</small>
                    ${dateStr ? `<div style="font-size:0.7rem; color:#9ca3af; margin-top:2px;">🕐 ${dateStr}</div>` : ''}
                </td>
                <td>${escapeHTML(d.packageName) || ''}<br><strong>${d.amount ? d.amount.toLocaleString() : 0}đ</strong></td>
                <td style="color: #ffde00; font-weight: 700;">${escapeHTML(d.transferContent) || ''}</td>
                <td>
                    <div class="proof-thumbnail" style="width: 50px; height: 50px; border-radius: 4px; overflow: hidden; border: 1px solid var(--glass-border); cursor: pointer;" onclick="window.viewFullImage('${safeUrl}')">
                        <img src="${d.proofLink}" style="width: 100%; height: 100%; object-fit: cover;" onerror="this.src='https://via.placeholder.com/50?text=Lỗi'">
                    </div>
                </td>
                <td>
                    <div style="display: flex; gap: 4px; align-items: center;">
                        ${currentTopupStatus === 'pending' ? `
                            <button class="btn-primary" style="padding: 4px 8px; font-size:0.75rem; background: #27ae60;" onclick="window.approveTopup('${d.id}', '${d.userId}', ${d.coins})">${t('admin.approve_btn')}</button>
                            <button class="btn-secondary" style="padding: 4px 8px; font-size:0.75rem; background: #c0392b;" onclick="window.rejectTopup('${d.id}')">${t('admin.reject_btn')}</button>
                        ` : `
                            <span class="status-badge status-${d.status}">${STATUS_MAP()[d.status] || d.status}</span>
                        `}
                        <button class="btn-delete" style="padding: 6px; background: rgba(255,59,48,0.1); border: 1px solid rgba(255,59,48,0.2); border-radius: 6px; cursor: pointer; color: #ff3b30;" onclick="window.deleteTopup(event, '${d.id}')" title="${t('common.delete')}">
                            <svg style="width:14px; height:14px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');

    // Pagination Controls
    let paginationContainer = document.getElementById('admin-topups-pagination');
    if (!paginationContainer) {
        paginationContainer = document.createElement('div');
        paginationContainer.id = 'admin-topups-pagination';
        paginationContainer.style.display = 'flex';
        paginationContainer.style.justifyContent = 'center';
        paginationContainer.style.alignItems = 'center';
        paginationContainer.style.gap = '15px';
        paginationContainer.style.marginTop = '20px';
        list.parentElement.parentElement.appendChild(paginationContainer);
    }

    // Note + nút "Tìm trong toàn bộ" khi đang search và data bị truncate
    let infoNote = '';
    if (hasFullCache) {
        infoNote = `<span style="font-size:0.7rem; color: #4ade80; margin-left:10px;">${t('admin.search_full_active', { count: FB_CACHE.adminTopupsFull.length })}</span>`;
    } else if (FB_CACHE.adminTopupsTruncated) {
        infoNote = `<span style="font-size:0.7rem; opacity:0.6; margin-left:10px;">${t('admin.search_truncated_hint', { limit: ADMIN_QUERY_LIMIT })}${searchVal ? ` — <a href="#" onclick="event.preventDefault(); window.fetchAllAdminCollection('topups')" style="color:#ffde00;">${t('admin.search_full_btn')}</a>` : ''}</span>`;
    }

    if (totalPages > 1) {
        paginationContainer.innerHTML = `
            <button class="btn-secondary" style="padding: 6px 12px;" onclick="window.changeAdminTopupPage(${window.currentAdminTopupPage - 1})" ${window.currentAdminTopupPage === 1 ? 'disabled' : ''}>${t('common.pagination_prev')}</button>
            <span>${t('common.pagination_page', { current: window.currentAdminTopupPage, total: totalPages })}${infoNote}</span>
            <button class="btn-secondary" style="padding: 6px 12px;" onclick="window.changeAdminTopupPage(${window.currentAdminTopupPage + 1})" ${window.currentAdminTopupPage === totalPages ? 'disabled' : ''}>${t('common.pagination_next')}</button>
        `;
    } else {
        paginationContainer.innerHTML = infoNote;
    }
}

// ----- ORDERS -----
function subscribeAdminOrders() {
    const { db, collection, query, where, onSnapshot, orderBy, limit } = window.firebase;
    const status = currentOrderStatus;

    if (fbHas('adminOrders') && adminSubscribedOrderStatus === status) {
        renderAdminOrders();
        return;
    }
    adminSubscribedOrderStatus = status;

    const q = query(
        collection(db, "orders"),
        where("status", "==", status),
        orderBy("createdAt", "desc"),
        limit(ADMIN_QUERY_LIMIT)
    );
    fbSub('adminOrders', onSnapshot(q, (snapshot) => {
        FB_CACHE.adminOrders = snapshot.docs.map(d => ({ id: d.id, ...d.data() }));
        FB_CACHE.adminOrdersTruncated = snapshot.size === ADMIN_QUERY_LIMIT;
        renderAdminOrders();
    }, (error) => {
        console.error("Orders Snapshot Error:", error);
        showToast(t('admin.toast_orders_load_error', { msg: error.message }));
    }));
}

function renderAdminOrders() {
    const list = document.getElementById('admin-orders-list');
    if (!list) return;

    const searchVal = document.getElementById('admin-search-input')?.value.toLowerCase() || "";

    // Nếu user đã bấm "Tìm trong toàn bộ" cho status hiện tại -> dùng full cache
    const hasFullCache = !!FB_CACHE.adminOrdersFull && FB_CACHE.adminOrdersFullStatus === currentOrderStatus;
    const allDocs = (searchVal && hasFullCache)
        ? FB_CACHE.adminOrdersFull
        : (FB_CACHE.adminOrders || []);

    if (allDocs.length === 0) {
        list.innerHTML = `<tr><td colspan="5" style="text-align:center; opacity:0.5; padding:2rem;">${t('status.empty_orders_msg')}</td></tr>`;
        document.getElementById('admin-orders-pagination')?.remove();
        return;
    }

    const filteredDocs = allDocs.filter(d => {
        const orderId = d.id.substring(d.id.length - 6).toUpperCase();
        const text = `${orderId} ${d.userName} ${d.userEmail} ${d.packageName} ${d.serviceType}`.toLowerCase();
        return text.includes(searchVal);
    });

    if (filteredDocs.length === 0) {
        if (searchVal && FB_CACHE.adminOrdersTruncated && !hasFullCache) {
            list.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:2rem;">
                <div style="opacity:0.7; margin-bottom: 1rem;">${t('admin.search_not_found_orders', { query: searchVal, limit: ADMIN_QUERY_LIMIT })}</div>
                <button class="btn-primary" onclick="window.fetchAllAdminCollection('orders')" style="padding: 8px 16px;">${t('admin.search_full_btn')}</button>
            </td></tr>`;
        } else {
            list.innerHTML = `<tr><td colspan="6" style="text-align:center; opacity:0.5; padding:2rem;">${t('admin.search_no_results')}</td></tr>`;
        }
        document.getElementById('admin-orders-pagination')?.remove();
        return;
    }

    // Group by User (sort users by their latest request)
    const userLatestTime = {};
    filteredDocs.forEach(d => {
        const time = d.createdAt?.toMillis ? d.createdAt.toMillis() : (d.createdAt || 0);
        if (!userLatestTime[d.userId] || time > userLatestTime[d.userId]) {
            userLatestTime[d.userId] = time;
        }
    });

    const dataList = [...filteredDocs].sort((a, b) => {
        if (a.userId !== b.userId) {
            return userLatestTime[b.userId] - userLatestTime[a.userId];
        }
        const timeA = a.createdAt?.toMillis ? a.createdAt.toMillis() : (a.createdAt || 0);
        const timeB = b.createdAt?.toMillis ? b.createdAt.toMillis() : (b.createdAt || 0);
        return timeB - timeA;
    });

    const ITEMS_PER_PAGE = 10;
    if (!window.currentAdminOrderPage) window.currentAdminOrderPage = 1;
    const totalPages = Math.ceil(dataList.length / ITEMS_PER_PAGE);

    if (window.currentAdminOrderPage > totalPages && totalPages > 0) {
        window.currentAdminOrderPage = totalPages;
    }

    const startIndex = (window.currentAdminOrderPage - 1) * ITEMS_PER_PAGE;
    const pageData = dataList.slice(startIndex, startIndex + ITEMS_PER_PAGE);

    let lastUserId = null;
    let groupColor = 'transparent';
    const groupColors = ['rgba(255, 255, 255, 0.03)', 'transparent'];
    let colorIdx = 0;

    list.innerHTML = pageData.map(d => {
        if (d.userId !== lastUserId) {
            groupColor = groupColors[colorIdx % 2];
            colorIdx++;
            lastUserId = d.userId;
        }
        const orderId = d.id.substring(d.id.length - 6).toUpperCase();
        const createdDateObj = safeToDate(d.createdAt);
        const dateStr = createdDateObj ? createdDateObj.toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' }) : '';
        return `
            <tr style="background: ${groupColor}; transition: background 0.3s ease;">
                <td style="font-family: monospace; font-weight: bold; color: var(--accent-primary);">
                    #${orderId}
                    ${dateStr ? `<div style="font-size:0.7rem; color:#9ca3af; font-weight:normal; margin-top:4px;">🕐 ${dateStr}</div>` : ''}
                </td>
                <td>${escapeHTML(d.userName) || t('common.guest')}<br><small>${escapeHTML(d.userEmail) || ''}</small></td>
                <td>${escapeHTML(d.packageName) || ''} (${SERVICE_TYPE_MAP()[d.serviceType] || d.serviceType})</td>
                <td>${t('common.coin_amount', { count: d.costCoins || 0 })}</td>
                <td>
                    <div style="display: flex; gap: 6px; align-items: center;">
                        <button class="btn-secondary" style="padding:4px 8px; font-size:0.75rem;" onclick="window.openAdminDetail('${d.id}')">${t('admin.update_btn')}</button>
                        <button class="download-pill-btn image-btn" style="padding: 4px; border-radius: 6px;" title="${t('admin.download_image_title')}" onclick="window.downloadUrl(event, '${d.characterImageLink}')">
                            <svg style="width:14px;height:14px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><polyline points="21 15 16 10 5 21"></polyline></svg>
                        </button>
                        <button class="download-pill-btn video-btn" style="padding: 4px; border-radius: 6px;" title="${t('admin.download_ref_title')}" onclick="window.downloadUrl(event, '${d.referenceVideoLink}')">
                            <svg style="width:14px;height:14px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline></svg>
                        </button>
                        <button class="btn-delete" style="padding: 6px; background: rgba(255,59,48,0.1); border: 1px solid rgba(255,59,48,0.2); border-radius: 6px; cursor: pointer; color: #ff3b30;" onclick="window.deleteOrder(event, '${d.id}')" title="${t('admin.delete_order_title')}">
                            <svg style="width:14px; height:14px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');

    // Pagination Controls
    let paginationContainer = document.getElementById('admin-orders-pagination');
    if (!paginationContainer) {
        paginationContainer = document.createElement('div');
        paginationContainer.id = 'admin-orders-pagination';
        paginationContainer.style.display = 'flex';
        paginationContainer.style.justifyContent = 'center';
        paginationContainer.style.alignItems = 'center';
        paginationContainer.style.gap = '15px';
        paginationContainer.style.marginTop = '20px';
        list.parentElement.parentElement.appendChild(paginationContainer);
    }

    let infoNote = '';
    if (hasFullCache) {
        infoNote = `<span style="font-size:0.7rem; color: #4ade80; margin-left:10px;">${t('admin.search_full_active', { count: FB_CACHE.adminOrdersFull.length })}</span>`;
    } else if (FB_CACHE.adminOrdersTruncated) {
        infoNote = `<span style="font-size:0.7rem; opacity:0.6; margin-left:10px;">${t('admin.search_truncated_hint', { limit: ADMIN_QUERY_LIMIT })}${searchVal ? ` — <a href="#" onclick="event.preventDefault(); window.fetchAllAdminCollection('orders')" style="color:#ffde00;">${t('admin.search_full_btn')}</a>` : ''}</span>`;
    }

    if (totalPages > 1) {
        paginationContainer.innerHTML = `
            <button class="btn-secondary" style="padding: 6px 12px;" onclick="window.changeAdminOrderPage(${window.currentAdminOrderPage - 1})" ${window.currentAdminOrderPage === 1 ? 'disabled' : ''}>${t('common.pagination_prev')}</button>
            <span>${t('common.pagination_page', { current: window.currentAdminOrderPage, total: totalPages })}${infoNote}</span>
            <button class="btn-secondary" style="padding: 6px 12px;" onclick="window.changeAdminOrderPage(${window.currentAdminOrderPage + 1})" ${window.currentAdminOrderPage === totalPages ? 'disabled' : ''}>${t('common.pagination_next')}</button>
        `;
    } else {
        paginationContainer.innerHTML = infoNote;
    }
}

// [TỐI ƯU] Đổi trang -> chỉ render lại từ cache, KHÔNG re-subscribe
window.changeAdminOrderPage = (newPage) => {
    window.currentAdminOrderPage = newPage;
    renderAdminOrders();
};

window.changeAdminTopupPage = (newPage) => {
    window.currentAdminTopupPage = newPage;
    renderAdminTopups();
};

window.openUserOrderDetail = async (orderId) => {
    const { db, doc, getDoc } = window.firebase;
    const snap = await getDoc(doc(db, "orders", orderId));
    if (!snap.exists()) return;
    const d = snap.data();
    const shortId = snap.id.substring(snap.id.length - 6).toUpperCase();
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

window.handleAdminResultUpload = async () => {
    const fileInput = document.getElementById('admin-file-result');
    const file = fileInput.files[0];
    const statusDiv = document.getElementById('admin-upload-status');
    const btn = document.getElementById('btn-admin-upload');

    if (!file) return showToast(t('admin.upload_video'));

    try {
        btn.disabled = true;
        btn.innerText = t('admin.uploading');
        statusDiv.style.display = 'block';
        statusDiv.innerText = t('admin.upload_start');

        const uploadedUrl = await uploadFile(file, "results");

        document.getElementById('admin-result-link').value = uploadedUrl;
        statusDiv.innerHTML = `<span style="color: #27ae60;">${t('admin.upload_success')}</span>`;
        showToast(t('admin.toast_upload_success'));
    } catch (error) {
        console.error(error);
        statusDiv.innerHTML = `<span style="color: #c0392b;">❌ ${t('common.error')}: ${error.message}</span>`;
        showToast(t('admin.toast_upload_error'));
    } finally {
        btn.disabled = false;
        btn.innerText = t('admin.btn_upload');
    }
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

// --- Google Analytics / Firebase Tracking Helper ---
function trackAnalyticsEvent(eventName, params = {}) {
    const { analytics, logEvent } = window.firebase;
    if (analytics) {
        logEvent(analytics, eventName, params);
        console.log(`📊 Firebase Analytics: ${eventName}`, params);
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

async function enrichReferralReferrers() {
    const rows = FB_CACHE.adminReferrals || [];
    if (!rows.length || !window.__isAdmin) return false;

    if (!FB_CACHE.referrerProfiles) FB_CACHE.referrerProfiles = {};

    const needFetch = [...new Set(
        rows
            .filter(r => r.referrerId && (
                !r.referrerName || r.referrerName === 'N/A' || !r.referrerEmail
            ) && !FB_CACHE.referrerProfiles[r.referrerId])
            .map(r => r.referrerId)
    )];

    if (needFetch.length === 0) return false;

    const { db, doc, getDoc } = window.firebase;
    await Promise.all(needFetch.map(async (uid) => {
        try {
            const snap = await getDoc(doc(db, 'users', uid));
            if (snap.exists()) {
                const data = snap.data();
                FB_CACHE.referrerProfiles[uid] = {
                    referrerName: data.displayName || (data.email ? data.email.split('@')[0] : uid.slice(0, 10)),
                    referrerEmail: data.email || ''
                };
            } else {
                FB_CACHE.referrerProfiles[uid] = {
                    referrerName: `${uid.slice(0, 10)}…`,
                    referrerEmail: ''
                };
            }
        } catch (e) {
            console.warn('[Referral] enrich referrer failed:', uid, e.message);
            FB_CACHE.referrerProfiles[uid] = {
                referrerName: `${uid.slice(0, 10)}…`,
                referrerEmail: ''
            };
        }
    }));

    FB_CACHE.adminReferrals = rows.map(r => {
        const profile = r.referrerId ? FB_CACHE.referrerProfiles[r.referrerId] : null;
        if (!profile) return r;
        return {
            ...r,
            referrerName: (r.referrerName && r.referrerName !== 'N/A') ? r.referrerName : profile.referrerName,
            referrerEmail: r.referrerEmail || profile.referrerEmail
        };
    });
    return true;
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

async function ensureReferralCode(uid) {
    const { db, doc, getDoc, setDoc, updateDoc, serverTimestamp } = window.firebase;
    const userRef = doc(db, "users", uid);
    const userSnap = await getDoc(userRef);
    if (!userSnap.exists()) throw new Error('User doc not found');

    const existing = userSnap.data().referralCode;
    if (existing && /^[A-Z0-9]{6,12}$/.test(existing)) {
        // Verify the mapping doc still exists (might be missing for legacy code path)
        try {
            const mapSnap = await getDoc(doc(db, "referralCodes", existing));
            if (!mapSnap.exists()) {
                await setDoc(doc(db, "referralCodes", existing), {
                    uid: uid,
                    createdAt: serverTimestamp()
                });
            }
        } catch (e) {
            console.warn('[Referral] Could not verify mapping doc:', e.message);
        }
        return existing;
    }

    for (let attempt = 0; attempt < 5; attempt++) {
        const candidate = generateReferralCode();
        const mapRef = doc(db, "referralCodes", candidate);
        const mapSnap = await getDoc(mapRef);
        if (mapSnap.exists()) continue;

        await setDoc(mapRef, { uid: uid, createdAt: serverTimestamp() });
        await updateDoc(userRef, { referralCode: candidate });
        return candidate;
    }
    throw new Error('Could not allocate unique referral code after 5 attempts');
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
    const statEarnedCoins = document.getElementById('referral-stat-earned-coins');
    const statEarnedUsd = document.getElementById('referral-stat-earned-usd');
    const statTopups = document.getElementById('referral-stat-topups');

    if (linkInput) linkInput.value = t('common.loading') || 'Loading...';
    if (codeDisplay) codeDisplay.innerText = '...';

    try {
        const code = await ensureReferralCode(currentUser.uid);
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

    // Subscribe to referralEarnings for this user
    // [TỐI ƯU] Dùng FB_LISTENERS registry. fbSub tự unsub cái cũ trước khi tạo mới.
    const { db, collection, query, where, onSnapshot, orderBy, limit } = window.firebase;

    const q = query(
        collection(db, "referralEarnings"),
        where("referrerId", "==", currentUser.uid),
        orderBy("createdAt", "desc"),
        limit(200)
    );

    fbSub('referralEarnings', onSnapshot(q, (snapshot) => {
        if (!listEl) return;

        if (snapshot.empty) {
            listEl.innerHTML = `<tr><td colspan="5" style="text-align:center; opacity:0.5; padding:2rem;">${t('referral.empty')}</td></tr>`;
            if (statInvited) statInvited.innerText = '0';
            if (statEarned) statEarned.innerText = '0đ';
            if (statEarnedCoins) statEarnedCoins.innerText = '0 Coin';
            if (statEarnedUsd) statEarnedUsd.style.display = 'none';
            if (statTopups) statTopups.innerText = '0';
            return;
        }

        const rows = [];
        const uniqueFriends = new Set();
        let totalCommissionVnd = 0;
        let totalCommissionCoins = 0;
        let totalCommissionUsd = 0;
        let totalTopups = 0;

        snapshot.docs.forEach(docSnap => {
            const d = docSnap.data();
            const money = getReferralMoneyFields(d);
            uniqueFriends.add(d.referredUserId);
            totalCommissionCoins += d.commissionCoins || 0;
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
                    <td style="color:#ffde00; font-weight:700;">
                        <div>${commissionMoney}</div>
                        <small style="opacity:0.75; font-weight:500;">+${d.commissionCoins || 0} Coin</small>
                    </td>
                    <td>${gatewayLabel}</td>
                    <td>${dateStr}</td>
                </tr>
            `);
        });

        listEl.innerHTML = rows.join('');
        if (statInvited) statInvited.innerText = String(uniqueFriends.size);
        if (statEarned) statEarned.innerText = totalCommissionVnd > 0 ? formatReferralMoney(totalCommissionVnd, 'VND') : '0đ';
        if (statEarnedCoins) statEarnedCoins.innerText = `+${totalCommissionCoins} Coin`;
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
        console.error('[Referral] earnings snapshot error:', err);
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
    const msg = t('referral.share_msg') || 'Tham gia Nhay Cloud cùng mình - biến ảnh thành video AI cực chất!';
    const url = `https://t.me/share/url?url=${encodeURIComponent(input.value)}&text=${encodeURIComponent(msg)}`;
    window.open(url, '_blank');
};

/**
 * Client-side commission payment. Called from admin approveTopup flow.
 * Idempotent: uses topupId as referralEarnings doc ID.
 * Wrapped in try/catch by caller; this function may throw on hard errors.
 */
async function payReferralCommissionClient(topupId, referredUserId, baseCoins, gateway, snapshotData) {
    const { db, doc, getDoc, runTransaction, serverTimestamp } = window.firebase;

    if (!topupId || !referredUserId || !baseCoins || baseCoins <= 0) return;

    const commissionCoins = Math.floor(baseCoins * REFERRAL_COMMISSION_RATE);
    if (commissionCoins <= 0) return;

    const baseAmount = snapshotData && snapshotData.baseAmount ? Number(snapshotData.baseAmount) : null;
    const currency = (snapshotData && snapshotData.currency) || 'VND';
    const commissionAmount = computeReferralCommissionAmount(baseAmount, currency);

    const earningRef = doc(db, "referralEarnings", topupId);
    const earningSnap = await getDoc(earningRef);
    if (earningSnap.exists()) {
        console.log('[Referral] Commission already paid for topup:', topupId);
        return;
    }

    const referredUserRef = doc(db, "users", referredUserId);
    const referredUserSnap = await getDoc(referredUserRef);
    if (!referredUserSnap.exists()) return;
    const referredData = referredUserSnap.data();
    const referrerId = referredData.referredBy;
    if (!referrerId) return;
    if (referrerId === referredUserId) return;

    const referrerRef = doc(db, "users", referrerId);
    const referrerSnapPre = await getDoc(referrerRef);
    if (!referrerSnapPre.exists()) return;
    const referrerData = referrerSnapPre.data();
    const allowSnap = await getDoc(doc(db, 'referralAllowlist', normalizeReferralAllowlistEmail(referrerData.email || '')));
    if (!allowSnap.exists()) {
        console.log('[Referral] Referrer not on allowlist — skip commission:', referrerData.email);
        return;
    }

    await runTransaction(db, async (transaction) => {
        const earningInTxn = await transaction.get(earningRef);
        if (earningInTxn.exists()) return;

        const referrerSnap = await transaction.get(referrerRef);
        if (!referrerSnap.exists()) return;
        const currentCoins = referrerSnap.data().coins || 0;

        transaction.update(referrerRef, {
            coins: currentCoins + commissionCoins,
            updatedAt: serverTimestamp()
        });

        const earningPayload = {
            referrerId: referrerId,
            referrerName: referrerData.displayName || (referrerData.email ? referrerData.email.split('@')[0] : '') || 'N/A',
            referrerEmail: referrerData.email || '',
            referredUserId: referredUserId,
            referredUserEmail: (snapshotData && snapshotData.userEmail) || referredData.email || '',
            referredUserName: (snapshotData && snapshotData.userName) || referredData.displayName || '',
            topupId: topupId,
            baseCoins: baseCoins,
            commissionCoins: commissionCoins,
            commissionRate: REFERRAL_COMMISSION_RATE,
            gateway: gateway || 'unknown',
            currency: currency,
            payoutStatus: 'credited',
            createdAt: serverTimestamp()
        };
        if (baseAmount && baseAmount > 0) {
            earningPayload.baseAmount = baseAmount;
            earningPayload.commissionAmount = commissionAmount;
        }
        transaction.set(earningRef, earningPayload);
    });

    console.log(`[Referral] Paid ${commissionCoins} coin + ${commissionAmount} ${currency} commission to ${referrerId} for topup ${topupId}`);
}
window.payReferralCommissionClient = payReferralCommissionClient;

