import { describe, expect, it, vi } from "vitest";

import { checkResponse, RetryableError, withRetry } from "../src/retry.js";

describe("withRetry", () => {
  it("retries RetryableError with growing backoff, then succeeds", async () => {
    const delays: number[] = [];
    let calls = 0;
    const value = await withRetry(
      async () => {
        calls++;
        if (calls < 3) throw new RetryableError("503");
        return "ok";
      },
      { retries: 3, baseDelayMs: 100, maxDelayMs: 10_000, sleep: async (ms) => void delays.push(ms) },
    );
    expect(value).toBe("ok");
    expect(calls).toBe(3);
    expect(delays).toHaveLength(2);
    expect(delays[0]).toBeGreaterThanOrEqual(50);
    expect(delays[0]).toBeLessThanOrEqual(100);
    expect(delays[1]).toBeGreaterThanOrEqual(100);
    expect(delays[1]).toBeLessThanOrEqual(200);
  });

  it("does not retry permanent errors", async () => {
    const fn = vi.fn(async () => {
      throw new Error("400 bad request");
    });
    await expect(withRetry(fn, { retries: 3, baseDelayMs: 1, maxDelayMs: 1, sleep: async () => {} })).rejects.toThrow(
      "400",
    );
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("gives up after the configured retries", async () => {
    const fn = vi.fn(async () => {
      throw new RetryableError("still down");
    });
    await expect(withRetry(fn, { retries: 2, baseDelayMs: 1, maxDelayMs: 1, sleep: async () => {} })).rejects.toThrow(
      "still down",
    );
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it("honours Retry-After when it is longer than the backoff", async () => {
    const delays: number[] = [];
    let first = true;
    await withRetry(
      async () => {
        if (first) {
          first = false;
          throw new RetryableError("429", 5_000);
        }
        return 1;
      },
      { retries: 1, baseDelayMs: 10, maxDelayMs: 10, sleep: async (ms) => void delays.push(ms) },
    );
    expect(delays).toEqual([5_000]);
  });
});

describe("checkResponse", () => {
  it("treats 5xx and 429 as retryable, 4xx as permanent", async () => {
    await expect(checkResponse(new Response("x", { status: 503 }), "core")).rejects.toBeInstanceOf(RetryableError);
    await expect(checkResponse(new Response("x", { status: 429 }), "core")).rejects.toBeInstanceOf(RetryableError);
    const permanent = checkResponse(new Response("x", { status: 401 }), "core");
    await expect(permanent).rejects.not.toBeInstanceOf(RetryableError);
  });
});
