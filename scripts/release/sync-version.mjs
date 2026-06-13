import { readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');

async function readJson(path) {
  return JSON.parse(await readFile(resolve(repoRoot, path), 'utf8'));
}

async function writeJson(path, data) {
  await writeFile(resolve(repoRoot, path), `${JSON.stringify(data, null, 2)}\n`);
}

function replaceProjectVersion(toml, version) {
  let inProject = false;
  let replaced = false;

  const lines = toml.split('\n').map((line) => {
    if (/^\[.+\]\s*$/.test(line)) {
      inProject = line.trim() === '[project]';
    }

    if (inProject && /^version\s*=/.test(line)) {
      replaced = true;
      return `version = "${version}"`;
    }

    return line;
  });

  if (!replaced) {
    throw new Error('Could not find [project] version in pyproject.toml');
  }

  return lines.join('\n');
}

function replaceUvPackageVersion(lockfile, version) {
  const packagePattern = /(\[\[package\]\][\s\S]*?name = "comicarr"[\s\S]*?version = ")[^"]+(")/;

  if (!packagePattern.test(lockfile)) {
    throw new Error('Could not find comicarr package entry in uv.lock');
  }

  const updated = lockfile.replace(packagePattern, `$1${version}$2`);
  const updatedPackagePattern = new RegExp(
    String.raw`\[\[package\]\][\s\S]*?name = "comicarr"[\s\S]*?version = "${version.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}"`,
  );

  if (!updatedPackagePattern.test(updated)) {
    throw new Error('Could not update comicarr package version in uv.lock');
  }

  return updated;
}

const rootPackage = await readJson('package.json');
const version = rootPackage.version;

if (!/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(version)) {
  throw new Error(`Invalid package version: ${version}`);
}

const pyprojectPath = resolve(repoRoot, 'pyproject.toml');
const pyproject = await readFile(pyprojectPath, 'utf8');
await writeFile(pyprojectPath, replaceProjectVersion(pyproject, version));

const frontendPackage = await readJson('frontend/package.json');
frontendPackage.version = version;
await writeJson('frontend/package.json', frontendPackage);

const frontendLock = await readJson('frontend/package-lock.json');
frontendLock.version = version;
if (frontendLock.packages?.['']) {
  frontendLock.packages[''].version = version;
}
await writeJson('frontend/package-lock.json', frontendLock);

const rootLockPath = resolve(repoRoot, 'package-lock.json');
try {
  const rootLock = await readJson('package-lock.json');
  rootLock.version = version;
  if (rootLock.packages?.['']) {
    rootLock.packages[''].version = version;
  }
  await writeJson('package-lock.json', rootLock);
} catch (error) {
  if (error.code !== 'ENOENT') {
    throw error;
  }
}

const uvLockPath = resolve(repoRoot, 'uv.lock');
const uvLock = await readFile(uvLockPath, 'utf8');
await writeFile(uvLockPath, replaceUvPackageVersion(uvLock, version));

console.log(`Synced Comicarr release version to ${version}`);
