/**
 * Dedicated binary helper for Support bundle download.
 *
 * Not the JSON-only apiRequest path. Accepts no caller options or filename.
 */

import { ApiError, sanitizeApiErrorBody } from "@/lib/api";

export const SUPPORT_BUNDLE_FILENAME = "comicarr-support-bundle-v1.zip";
export const SUPPORT_BUNDLE_MAX_BYTES = 512 * 1024;
export const SUPPORT_BUNDLE_CONTRACT = "1";

export type SupportBundleStatus = "complete" | "partial";

export type SupportBundleResult =
  | { ok: true; status: SupportBundleStatus }
  | { ok: false; error: ApiError; retryAfterSeconds?: number };

const CSRF_HEADERS = {
  "X-Requested-With": "ComicarrFrontend",
} as const;

const SAFETY_DETAIL =
  "Comicarr stopped the download because the bundle did not pass its safety checks. No file was downloaded.";

function contentDispositionMatches(header: string | null): boolean {
  if (!header) return false;
  const lower = header.toLowerCase();
  if (!lower.includes("attachment")) return false;
  return (
    header.includes(SUPPORT_BUNDLE_FILENAME) ||
    lower.includes(SUPPORT_BUNDLE_FILENAME.toLowerCase())
  );
}

function mediaTypeIsZip(header: string | null): boolean {
  if (!header) return false;
  const type = header.split(";")[0]?.trim().toLowerCase();
  return type === "application/zip" || type === "application/x-zip-compressed";
}

async function parseJsonError(
  response: Response,
): Promise<{ detail?: string; code?: string; retryable?: boolean }> {
  try {
    const body = await response.json();
    const sanitized = sanitizeApiErrorBody(body) ?? {};
    return {
      detail:
        typeof sanitized.detail === "string" ? sanitized.detail : undefined,
      code: typeof sanitized.code === "string" ? sanitized.code : undefined,
      retryable:
        typeof sanitized.retryable === "boolean"
          ? sanitized.retryable
          : undefined,
    };
  } catch {
    return {};
  }
}

function safetyError(status = 500): ApiError {
  const err = new ApiError(status, SAFETY_DETAIL, {
    code: "support_bundle_validation_failed",
    retryable: false,
  });
  err.isRetryable = false;
  return err;
}

function triggerDownload(blob: Blob): void {
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = SUPPORT_BUNDLE_FILENAME;
    anchor.rel = "noopener";
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * Create a Support bundle and dispatch a browser download of the fixed filename.
 *
 * @param signal Optional AbortSignal for cancellation.
 */
export async function downloadSupportBundle(
  signal?: AbortSignal,
): Promise<SupportBundleResult> {
  let response: Response;
  try {
    response = await fetch("/api/system/support-bundle", {
      method: "POST",
      credentials: "include",
      headers: { ...CSRF_HEADERS },
      signal,
    });
  } catch (error) {
    if (
      signal?.aborted ||
      (error instanceof DOMException && error.name === "AbortError")
    ) {
      const err = new ApiError(0, "Support bundle download canceled.");
      err.isRetryable = false;
      return { ok: false, error: err };
    }
    const err = new ApiError(
      0,
      "The connection was interrupted. No file was downloaded.",
    );
    err.isRetryable = true;
    return { ok: false, error: err };
  }

  if (!response.ok) {
    const parsed = await parseJsonError(response);
    let message = parsed.detail;
    if (response.status === 401) {
      message =
        "Your session has expired. Sign in again before creating a support bundle.";
    } else if (response.status === 403) {
      message =
        "Comicarr blocked the request. Refresh the page before trying again.";
    } else if (!message) {
      message =
        response.status === 409
          ? "Another support bundle is being created. Try again in a moment."
          : "Comicarr could not create the support bundle. Try again.";
    }
    const err = new ApiError(response.status, message, {
      code: parsed.code,
      retryable: parsed.retryable,
      detail: parsed.detail,
    });
    if (typeof parsed.retryable === "boolean") {
      err.isRetryable = parsed.retryable;
    } else if (response.status === 409 || response.status === 503) {
      err.isRetryable = true;
    } else if (
      response.status === 500 &&
      parsed.code === "support_bundle_validation_failed"
    ) {
      err.isRetryable = false;
    }
    const retryAfterHeader = response.headers.get("Retry-After");
    const retryAfterSeconds = retryAfterHeader
      ? Number.parseInt(retryAfterHeader, 10)
      : undefined;
    return {
      ok: false,
      error: err,
      retryAfterSeconds:
        Number.isFinite(retryAfterSeconds) && (retryAfterSeconds as number) > 0
          ? (retryAfterSeconds as number)
          : undefined,
    };
  }

  const contract = response.headers.get("X-Comicarr-Support-Bundle-Contract");
  const statusHeader = response.headers.get("X-Comicarr-Support-Bundle-Status");
  const disposition = response.headers.get("Content-Disposition");
  const contentType = response.headers.get("Content-Type");

  if (
    contract !== SUPPORT_BUNDLE_CONTRACT ||
    (statusHeader !== "complete" && statusHeader !== "partial") ||
    !mediaTypeIsZip(contentType) ||
    !contentDispositionMatches(disposition)
  ) {
    return { ok: false, error: safetyError(response.status) };
  }

  let buffer: ArrayBuffer;
  try {
    buffer = await response.arrayBuffer();
  } catch {
    return {
      ok: false,
      error: new ApiError(
        0,
        "The connection was interrupted. No file was downloaded.",
      ),
    };
  }

  if (buffer.byteLength < 1 || buffer.byteLength > SUPPORT_BUNDLE_MAX_BYTES) {
    return { ok: false, error: safetyError(response.status) };
  }

  try {
    const blob = new Blob([buffer], { type: "application/zip" });
    triggerDownload(blob);
  } catch {
    return { ok: false, error: safetyError(response.status) };
  }

  return { ok: true, status: statusHeader };
}
