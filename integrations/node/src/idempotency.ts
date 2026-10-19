import type { TriageResult } from "./types.js";

export interface LeadRecord {
  result: TriageResult;
  /** Sinks that already ran successfully for this lead, so a retry skips them. */
  completed: string[];
  updatedAt: number;
}

/** Swap for Redis or a database table when running more than one worker. */
export interface IdempotencyStore {
  get(key: string): Promise<LeadRecord | undefined>;
  set(key: string, record: LeadRecord): Promise<void>;
}

export class MemoryIdempotencyStore implements IdempotencyStore {
  private readonly records = new Map<string, LeadRecord>();

  constructor(
    private readonly ttlMs = 24 * 60 * 60 * 1000,
    private readonly now: () => number = Date.now,
  ) {}

  async get(key: string): Promise<LeadRecord | undefined> {
    const record = this.records.get(key);
    if (!record) return undefined;
    if (this.now() - record.updatedAt > this.ttlMs) {
      this.records.delete(key);
      return undefined;
    }
    return record;
  }

  async set(key: string, record: LeadRecord): Promise<void> {
    this.records.set(key, { ...record, updatedAt: this.now() });
  }
}

/** Collapses concurrent deliveries of the same lead into one in-flight run. */
export class InFlight<T> {
  private readonly running = new Map<string, Promise<T>>();

  run(key: string, fn: () => Promise<T>): { promise: Promise<T>; joined: boolean } {
    const existing = this.running.get(key);
    if (existing) return { promise: existing, joined: true };
    const promise = fn().finally(() => this.running.delete(key));
    this.running.set(key, promise);
    return { promise, joined: false };
  }
}
