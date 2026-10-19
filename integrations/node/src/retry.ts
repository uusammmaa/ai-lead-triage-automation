export class RetryableError extends Error {
  constructor(
    message: string,
    readonly retryAfterMs?: number,
  ) {
    super(message);
    this.name = "RetryableError";
  }
}

export interface RetryOptions {
  retries: number;
  baseDelayMs: number;
  maxDelayMs: number;
  sleep?: (ms: number) => Promise<void>;
  onRetry?: (attempt: number, delayMs: number, error: unknown) => void;
}

export const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Exponential backoff with full jitter. Only RetryableError is retried. */
export async function withRetry<T>(fn: (attempt: number) => Promise<T>, opts: RetryOptions): Promise<T> {
  const sleep = opts.sleep ?? defaultSleep;
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn(attempt);
    } catch (error) {
      if (!(error instanceof RetryableError) || attempt >= opts.retries) throw error;
      const backoff = Math.min(opts.maxDelayMs, opts.baseDelayMs * 2 ** attempt);
      const delay = Math.max(error.retryAfterMs ?? 0, Math.round(backoff / 2 + (Math.random() * backoff) / 2));
      opts.onRetry?.(attempt + 1, delay, error);
      await sleep(delay);
    }
  }
}

/** Map an HTTP response to success, a retryable failure, or a permanent one. */
export async function checkResponse(res: Response, what: string): Promise<Response> {
  if (res.ok) return res;
  const body = (await res.text().catch(() => "")).slice(0, 300);
  if (res.status === 429 || res.status >= 500) {
    const retryAfter = Number(res.headers.get("retry-after"));
    throw new RetryableError(
      `${what} failed with ${res.status}: ${body}`,
      Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : undefined,
    );
  }
  throw new Error(`${what} failed with ${res.status}: ${body}`);
}

/** fetch wrapper that turns network errors and timeouts into RetryableError. */
export async function fetchWithTimeout(
  fetchImpl: typeof fetch,
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  try {
    return await fetchImpl(url, { ...init, signal: AbortSignal.timeout(timeoutMs) });
  } catch (error) {
    throw new RetryableError(`request to ${new URL(url).host} failed: ${(error as Error).message}`);
  }
}
