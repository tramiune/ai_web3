(function applyLegalI18n() {
    const LANG_KEY = 'app_lang';
    const saved = (localStorage.getItem(LANG_KEY) || '').trim();
    const supported = window.LANG_CONFIG?.supported || ['vi', 'en', 'es', 'pt', 'th', 'id'];
    const lang = supported.includes(saved) ? saved : 'vi';

    function lookup(path, locale) {
        let value = window.TRANSLATIONS?.[locale];
        if (!value) return null;
        for (const key of path.split('.')) {
            if (value && Object.prototype.hasOwnProperty.call(value, key)) {
                value = value[key];
            } else {
                return null;
            }
        }
        return value;
    }

    function t(path) {
        return lookup(path, lang) || lookup(path, 'en') || lookup(path, 'vi');
    }

    document.documentElement.lang = lang;

    const titleKey = document.body.getAttribute('data-page-title');
    if (titleKey) {
        const title = t(titleKey);
        if (title) document.title = title;
    }

    document.querySelectorAll('[data-i18n]').forEach(el => {
        const translation = t(el.getAttribute('data-i18n'));
        if (translation) el.innerHTML = translation;
    });
})();
