import { appendFile, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const outputPath = process.env.GITHUB_OUTPUT;

function git(args) {
  return execFileSync('git', args, {
    cwd: repoRoot,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  }).trim();
}

async function setOutput(name, value) {
  if (!outputPath) {
    console.log(`${name}=${value}`);
    return;
  }

  await appendFile(outputPath, `${name}=${value}\n`);
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function extractReleaseNotes(changelog, version) {
  const heading = new RegExp(`^## \\[?${escapeRegExp(version)}\\]?(?:\\([^)]*\\))?(?:\\s+\\([^)]*\\))?.*$`, 'm');
  const match = changelog.match(heading);

  if (!match || match.index === undefined) {
    return null;
  }

  const sectionStart = match.index + match[0].length;
  const rest = changelog.slice(sectionStart);
  const nextHeading = rest.search(/^## /m);
  const section = nextHeading === -1 ? rest : rest.slice(0, nextHeading);

  return section.trim();
}

const rootPackage = JSON.parse(await readFile(resolve(repoRoot, 'package.json'), 'utf8'));
const version = rootPackage.version;
const tagName = `v${version}`;

try {
  git(['fetch', '--tags', '--force']);
} catch (error) {
  console.warn(`Could not refresh git tags: ${error.message}`);
}

const existingTag = git(['tag', '--list', tagName]);
if (existingTag === tagName) {
  await setOutput('should_release', 'false');
  await setOutput('version', version);
  await setOutput('tag_name', tagName);
  console.log(`${tagName} already exists; skipping GitHub Release and Docker publish.`);
  process.exit(0);
}

const changelogPath = resolve(repoRoot, 'CHANGELOG.md');
let changelog;
try {
  changelog = await readFile(changelogPath, 'utf8');
} catch (error) {
  if (error.code === 'ENOENT') {
    await setOutput('should_release', 'false');
    await setOutput('version', version);
    await setOutput('tag_name', tagName);
    console.log(`${changelogPath} not found; skipping release.`);
    process.exit(0);
  }

  throw error;
}

const releaseNotes = extractReleaseNotes(changelog, version);

if (!releaseNotes) {
  await setOutput('should_release', 'false');
  await setOutput('version', version);
  await setOutput('tag_name', tagName);
  console.log(`CHANGELOG.md has no ${version} section; skipping release.`);
  process.exit(0);
}

const notesDir = await mkdtemp(join(tmpdir(), 'comicarr-release-'));
const notesPath = join(notesDir, 'release-notes.md');
await writeFile(notesPath, `${releaseNotes}\n`);

await setOutput('should_release', 'true');
await setOutput('version', version);
await setOutput('tag_name', tagName);
await setOutput('release_notes_path', notesPath);

console.log(`Prepared ${tagName} release metadata from CHANGELOG.md.`);
