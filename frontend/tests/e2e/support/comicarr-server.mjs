import { spawn } from "node:child_process";
import { mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const ADMIN_USERNAME = process.env.COMICARR_E2E_USERNAME ?? "e2e-admin";
export const ADMIN_PASSWORD =
  process.env.COMICARR_E2E_PASSWORD ?? "comicarr-e2e-password";

const currentFile = fileURLToPath(import.meta.url);
export const frontendRoot = resolve(dirname(currentFile), "../../..");
export const repoRoot = resolve(frontendRoot, "..");

const keepDataValues = new Set(["1", "true", "yes"]);

function keepData() {
  return keepDataValues.has(
    String(process.env.COMICARR_E2E_KEEP_DATA ?? "").toLowerCase(),
  );
}

function delay(ms) {
  return new Promise((resolveDelay) => {
    setTimeout(resolveDelay, ms);
  });
}

function quoteIniValue(value) {
  return String(value).replaceAll("\\", "/");
}

function envDataDirForMode(mode) {
  if (mode === "seeded") {
    return process.env.COMICARR_E2E_DATADIR;
  }
  if (mode === "fresh") {
    return process.env.COMICARR_E2E_FULL_DATADIR;
  }
  return undefined;
}

async function prepareDataDir({ dataDir, mode, port }) {
  const resolvedDataDir =
    dataDir ??
    envDataDirForMode(mode) ??
    join(tmpdir(), `comicarr-e2e-${mode}-${port}`);

  const absoluteDataDir = resolve(resolvedDataDir);
  if (!keepData()) {
    await rm(absoluteDataDir, { recursive: true, force: true });
  }

  await mkdir(absoluteDataDir, { recursive: true });
  await Promise.all(
    ["cache", "comics", "downloads", "import", "logs", "manga"].map((name) =>
      mkdir(join(absoluteDataDir, name), { recursive: true }),
    ),
  );

  return absoluteDataDir;
}

async function writeSeededConfig(dataDir, port) {
  const configPath = join(dataDir, "config.ini");

  await writeFile(
    configPath,
    `[General]
config_version = 15
minimal_ini = False
auto_update = False
launch_browser = False
destination_dir = ${quoteIniValue(join(dataDir, "downloads"))}
manga_destination_dir = ${quoteIniValue(join(dataDir, "manga"))}
encrypt_passwords = False
migration_dismissed = True

[Interface]
http_host = 127.0.0.1
http_port = ${port}
http_username = ${ADMIN_USERNAME}
http_password = ${ADMIN_PASSWORD}
authentication = 2
enable_https = False

[Import]
comic_dir = ${quoteIniValue(join(dataDir, "comics"))}
manga_dir = ${quoteIniValue(join(dataDir, "manga"))}
import_dir = ${quoteIniValue(join(dataDir, "import"))}
imp_move = False
imp_rename = False
imp_metadata = False

[Scheduler]
search_interval = 1440
download_scan_interval = 360
rss_checkinterval = 360
import_scan_interval = 360

[Logs]
log_dir = ${quoteIniValue(join(dataDir, "logs"))}
log_level = 0

[Git]
check_github = False
check_github_on_startup = False

[CV]
comicvine_enabled = False
cv_verify = False
cv_only = False

[Metron]
use_metron_search = False

[MangaDex]
mangadex_enabled = False
`,
    "utf8",
  );
}

export async function waitForHealth(baseURL, timeout = 120_000, getOutput) {
  const deadline = Date.now() + timeout;
  let lastError = "";

  while (Date.now() < deadline) {
    try {
      const response = await fetch(new URL("/api/health", baseURL));
      if (response.ok) {
        return;
      }
      lastError = `HTTP ${response.status}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }

    await delay(500);
  }

  const output = getOutput ? `\n\nProcess output:\n${getOutput()}` : "";
  throw new Error(
    `Comicarr did not become healthy at ${baseURL}: ${lastError}${output}`,
  );
}

function extractSetupToken(output) {
  return output.match(/Setup token:\s*([^\s]+)/)?.[1] ?? null;
}

export class ComicarrServer {
  constructor({ dataDir, mode, port, streamOutput = false }) {
    this.child = null;
    this.dataDir = dataDir;
    this.exitPromise = null;
    this.mode = mode;
    this.output = [];
    this.port = port;
    this.streamOutput = streamOutput;
    this.baseURL = `http://127.0.0.1:${port}`;
  }

  async start() {
    const python = process.env.COMICARR_E2E_PYTHON ?? "python3";
    const args = [
      "Comicarr.py",
      "--nolaunch",
      "--quiet",
      "--datadir",
      this.dataDir,
      "--port",
      String(this.port),
    ];

    this.output = [];
    this.child = spawn(python, args, {
      cwd: repoRoot,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: "1",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });

    this.child.stdout.on("data", (chunk) => {
      const text = chunk.toString();
      this.output.push(text);
      if (this.streamOutput) {
        process.stderr.write(text);
      }
    });
    this.child.stderr.on("data", (chunk) => {
      const text = chunk.toString();
      this.output.push(text);
      if (this.streamOutput) {
        process.stderr.write(text);
      }
    });
    this.exitPromise = new Promise((resolveExit) => {
      this.child.once("exit", (code, signal) => {
        resolveExit({ code, signal });
      });
    });

    return this;
  }

  outputText() {
    return this.output.join("");
  }

  async waitForReady(timeout) {
    if (!this.child) {
      throw new Error("Comicarr process has not been started");
    }

    await Promise.race([
      waitForHealth(this.baseURL, timeout, () => this.outputText()),
      this.exitPromise.then(({ code, signal }) => {
        throw new Error(
          `Comicarr exited before health check passed (code ${code}, signal ${signal}).\n\n${this.outputText()}`,
        );
      }),
    ]);
    return this;
  }

  async waitForSetupToken(timeout = 30_000) {
    const deadline = Date.now() + timeout;

    while (Date.now() < deadline) {
      const token = extractSetupToken(this.outputText());
      if (token) {
        return token;
      }
      await delay(250);
    }

    throw new Error(`Setup token was not printed.\n\n${this.outputText()}`);
  }

  async stop() {
    if (!this.child) {
      return;
    }

    const child = this.child;
    this.child = null;

    if (child.exitCode === null && child.signalCode === null) {
      child.kill("SIGTERM");
      const timeout = delay(8_000).then(() => "timeout");
      const result = await Promise.race([this.exitPromise, timeout]);
      if (result === "timeout" && child.exitCode === null) {
        child.kill("SIGKILL");
        await this.exitPromise;
      }
    }
  }

  async cleanup() {
    await this.stop();
    if (!keepData()) {
      await rm(this.dataDir, { recursive: true, force: true });
    }
  }

  async restart({ downtimeMs = 2_500, timeout = 120_000 } = {}) {
    await this.stop();
    await delay(downtimeMs);
    await this.start();
    await this.waitForReady(timeout);
  }
}

export async function startComicarr(options = {}) {
  const mode = options.mode ?? "seeded";
  const port = Number(options.port ?? process.env.COMICARR_E2E_PORT ?? "18090");
  const dataDir = await prepareDataDir({
    dataDir: options.dataDir,
    mode,
    port,
  });

  if (mode === "seeded") {
    await writeSeededConfig(dataDir, port);
  }

  const server = new ComicarrServer({
    dataDir,
    mode,
    port,
    streamOutput: options.streamOutput ?? false,
  });
  await server.start();
  return server;
}

async function runAsWebServer() {
  const mode = process.argv[2] ?? "seeded";
  const server = await startComicarr({ mode, streamOutput: true });
  await server.waitForReady();

  const shutdown = async () => {
    await server.stop();
    if (!keepData()) {
      await rm(server.dataDir, { recursive: true, force: true });
    }
    process.exit(0);
  };

  process.once("SIGINT", shutdown);
  process.once("SIGTERM", shutdown);

  await new Promise(() => {});
}

if (
  process.argv[1] &&
  pathToFileURL(process.argv[1]).href === import.meta.url
) {
  runAsWebServer().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
