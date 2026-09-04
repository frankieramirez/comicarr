// Measure the production entry's complete static JS dependency closure.
// Usage: node scripts/measure_initial_js.mjs frontend/dist [another/dist]
// Build each directory with: npm --prefix frontend run build -- --manifest
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { gzipSync } from "node:zlib";

for (const directory of process.argv.slice(2)) {
  const root = resolve(directory);
  const manifest = JSON.parse(readFileSync(resolve(root, ".vite/manifest.json"), "utf8"));
  const seen = new Set();
  const files = new Set();
  function visit(key) {
    if (seen.has(key)) return;
    seen.add(key);
    const chunk = manifest[key];
    files.add(chunk.file);
    for (const imported of chunk.imports ?? []) visit(imported);
  }
  for (const [key, chunk] of Object.entries(manifest)) {
    if (chunk.isEntry) visit(key);
  }
  let rawBytes = 0;
  let gzipBytes = 0;
  for (const file of files) {
    const bytes = readFileSync(resolve(root, file));
    rawBytes += bytes.length;
    gzipBytes += gzipSync(bytes).length;
  }
  console.log(JSON.stringify({ directory: root, files: files.size, rawBytes, gzipBytes }, null, 2));
}
