#!/usr/bin/env node
// CI gate for localization. Two checks, both read-only unless --update:
//
// 1. Every catalog matches what `lingui extract` would write, checked
//    with `lingui check sync`. A new or changed message that was not
//    extracted fails here, so translators never miss a string.
//
// 2. Unlocalized text only shrinks. eslint.i18n.config.js flags string
//    literals and JSX text that are not wrapped in a Lingui macro. The count
//    per file must not exceed i18n-baseline.json; a file that got *better*
//    must lower its entry (a stale entry fails too, so the baseline tracks
//    reality). Fix the code, then run `npm run i18n:update` to rewrite the
//    catalog and lower the baseline. It never raises a count.
//
// See docs/architecture/i18n.md. Contributor-only gate: no changeset.
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { ESLint } from "eslint";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BASELINE = path.join(ROOT, "i18n-baseline.json");
const update = process.argv.includes("--update");

const LINGUI = path.join(ROOT, "node_modules/@lingui/cli/dist/lingui.js");

function checkCatalog() {
  const args = update ? ["extract", "--clean"] : ["check", "sync", "--clean"];
  try {
    execFileSync(process.execPath, [LINGUI, ...args], { cwd: ROOT, stdio: "pipe" });
    return true;
  } catch (error) {
    console.error(String(error.stdout || error.stderr || error.message).trim());
    console.error(
      "i18n: src/locales catalogs are out of date. Run `npm run i18n:update`.",
    );
    return false;
  }
}

async function scanUnlocalized() {
  const eslint = new ESLint({
    cwd: ROOT,
    overrideConfigFile: path.join(ROOT, "eslint.i18n.config.js"),
  });
  const results = await eslint.lintFiles(["src/**/*.{ts,tsx}"]);
  const counts = {};
  for (const result of results) {
    const n = result.messages.filter(
      (m) => m.ruleId === "lingui/no-unlocalized-strings",
    ).length;
    if (n) counts[path.relative(ROOT, result.filePath).split(path.sep).join("/")] = n;
  }
  return { counts, results };
}

function sorted(obj) {
  return Object.fromEntries(Object.entries(obj).sort(([a], [b]) => a.localeCompare(b)));
}

async function checkBaseline() {
  const { counts, results } = await scanUnlocalized();
  const baseline = existsSync(BASELINE)
    ? JSON.parse(readFileSync(BASELINE, "utf8"))
    : {};
  const grew = [];
  const stale = [];
  for (const [file, n] of Object.entries(counts)) {
    const allowed = baseline[file] ?? 0;
    if (n > allowed) grew.push([file, n, allowed]);
  }
  for (const [file, allowed] of Object.entries(baseline)) {
    const n = counts[file] ?? 0;
    if (n < allowed) stale.push([file, n, allowed]);
  }

  if (update) {
    const next = {};
    for (const [file, allowed] of Object.entries(baseline)) {
      const n = Math.min(counts[file] ?? 0, allowed);
      if (n) next[file] = n;
    }
    writeFileSync(BASELINE, `${JSON.stringify(sorted(next), null, 2)}\n`);
  } else if (stale.length) {
    console.error("i18n: these files now have fewer unlocalized strings than the baseline.");
    console.error("Run `npm run i18n:update` to lower i18n-baseline.json:");
    for (const [file, n, allowed] of stale) console.error(`  ${file}: ${allowed} -> ${n}`);
  }

  if (grew.length) {
    console.error("i18n: new user-facing text must be wrapped for translation (t``, <Trans>, msg``).");
    for (const [file, n, allowed] of grew) {
      console.error(`  ${file}: ${n} unlocalized, baseline allows ${allowed}`);
      const result = results.find((r) => r.filePath.endsWith(file));
      const lines = readFileSync(path.join(ROOT, file), "utf8").split("\n");
      for (const m of result.messages.slice(0, 5)) {
        console.error(`    ${m.line}:${m.column}  ${lines[m.line - 1].trim().slice(0, 100)}`);
      }
    }
    return false;
  }
  return update || stale.length === 0;
}

const catalogOk = checkCatalog();
const baselineOk = await checkBaseline();
if (!catalogOk || !baselineOk) process.exit(1);
console.log(update ? "i18n: catalog and baseline updated." : "i18n: catalog current, no new unlocalized text.");
