/** Country → language for tier-1 / tier-2 ad markets. Fallback: en. */
window.LANG_CONFIG = {
    supported: ['vi', 'en'],
    flags: {
        vi: '🇻🇳',
        en: '🌎'
    },
    /** ISO 3166-1 alpha-2 → locale code */
    countryToLang: {
        VN: 'vi'
        // everything else → en
    },
    langFromCountry(country) {
        return String(country || '').toUpperCase() === 'VN' ? 'vi' : 'en';
    }
};
