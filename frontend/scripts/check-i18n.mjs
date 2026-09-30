// Localization audit — run: node scripts/check-i18n.mjs  (exit code 1 on failure)
//  1. every key exists in en/kn/hi (TypeScript also enforces this via the Dict type)
//  2. no Kannada/Hindi value is left identical to English, except identifiers that are not translated
//  3. every placeholder {x} in English also appears in the translation
//  4. no hard-coded English UI text in JSX (text between tags, or placeholder/title/aria-label attributes)
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../src/", import.meta.url));
const parse = (f) => {
  const src = readFileSync(join(root, "lib/i18n", f), "utf8");
  const out = {};
  for (const m of src.matchAll(/^\s*"?([\w+]+)"?:\s*"((?:[^"\\]|\\.)*)",?\s*$/gm)) out[m[1]] = m[2];
  return out;
};
const en = parse("en.ts"), kn = parse("kn.ts"), hi = parse("hi.ts");
// values that are legitimately the same in every language (identifiers, proper names, acronyms, language names)
const SAME_OK = new Set(["role_dlsa_admin", "lang_en", "lang_kn", "lang_hi", "docType_fir", "field_cnr", "cnr",
  "draftLang_en", "draftLang_kn", "emailPlaceholder"]);
const problems = [];
for (const [name, d] of [["kn", kn], ["hi", hi]]) {
  for (const k of Object.keys(en)) {
    if (!(k in d)) problems.push(`${name}: missing key ${k}`);
    else if (d[k] === en[k] && !SAME_OK.has(k)) problems.push(`${name}: untranslated ${k} = "${en[k]}"`);
    else {
      for (const ph of en[k].match(/\{\w+\}/g) ?? []) if (!d[k].includes(ph)) problems.push(`${name}: ${k} lost placeholder ${ph}`);
    }
  }
  for (const k of Object.keys(d)) if (!(k in en)) problems.push(`${name}: extra key ${k}`);
}

// hard-coded JSX text
const files = [];
const walk = (dir) => { for (const f of readdirSync(dir)) { const p = join(dir, f); statSync(p).isDirectory() ? walk(p) : p.endsWith(".tsx") && files.push(p); } };
walk(join(root, "app")); walk(join(root, "components"));
const ALLOWED_TEXT = [/^[\s·—→✓✗⚠“”"'(),.:;%|/?!+\-−×≥<>=_#0-9]*$/, /^(s\/o|d\/o|w\/o|CNR|p\.|DOCX|PDF)$/];
for (const f of files) {
  const src = readFileSync(f, "utf8");
  for (const m of src.matchAll(/>([^<>{}\n]*[A-Za-z][^<>{}\n]*)</g)) {
    const txt = m[1].trim();
    if (!txt || ALLOWED_TEXT.some((r) => r.test(txt))) continue;
    if (/^[\w.]+\s*=>/.test(txt) || /[=&|]{2}/.test(txt)) continue; // code, not text
    if (txt.startsWith("(") || /^[a-z]\w*$/.test(txt)) continue;     // TypeScript generics such as api<Doc>(...)
    if (/(^|\W)(new\s+)?(Promise|useState|useRef|Record|Array|Set|Map)$/.test(txt)) continue; // e.g. new Promise<string>(...)
    problems.push(`hard-coded text in ${f.slice(root.length)}: "${txt}"`);
  }
  for (const m of src.matchAll(/\b(placeholder|title|aria-label|alt)="([^"]*[A-Za-z][^"]*)"/g)) {
    if (m[2] === "303(2)") continue; // example section number (an identifier)
    problems.push(`hard-coded ${m[1]} in ${f.slice(root.length)}: "${m[2]}"`);
  }
}
const keys = Object.keys(en).length;
if (problems.length) {
  console.error(problems.join("\n"));
  console.error(`\n${problems.length} localization problem(s); ${keys} keys per language.`);
  process.exit(1);
}
console.log(`OK: ${keys} keys × 3 languages, no untranslated values, no hard-coded UI text in ${files.length} files.`);
