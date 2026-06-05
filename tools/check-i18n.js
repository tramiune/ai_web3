const fs = require('fs');
const vm = require('vm');

function get(obj, p) {
  return p.split('.').reduce((a, k) => {
    if (!a) return undefined;
    return Object.prototype.hasOwnProperty.call(a, k) ? a[k] : undefined;
  }, obj);
}

const script = fs.readFileSync('public/script.js', 'utf8');
const html = fs.readFileSync('public/index.html', 'utf8');
const translationsSrc = fs.readFileSync('public/translations.js', 'utf8');

const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(translationsSrc, sandbox, { timeout: 2000 });
const T = sandbox.window.TRANSLATIONS || {};

const keys = new Set();

for (const m of script.matchAll(/\bt\(['"]([a-zA-Z0-9_.-]+)['"]/g)) {
  keys.add(m[1]);
}
for (const m of html.matchAll(/data-i18n\s*=\s*"([^"]+)"/g)) {
  keys.add(m[1]);
}

const miss = { vi: [], en: [] };
for (const k of Array.from(keys).sort()) {
  for (const lang of ['vi', 'en']) {
    const v = get(T[lang], k);
    if (v === undefined || v === null || v === '') miss[lang].push(k);
  }
}

console.log('TOTAL_KEYS', keys.size);
console.log('MISSING_VI', miss.vi.length);
if (miss.vi.length) console.log(miss.vi.join('\n'));
console.log('MISSING_EN', miss.en.length);
if (miss.en.length) console.log(miss.en.join('\n'));

