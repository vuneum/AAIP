import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { AAIPClient } from '../src/index';

// ── Helpers ───────────────────────────────────────────────────────────────────

function mockFetch(status: number, body: unknown): void {
  global.fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response);
}

// ── Client construction ───────────────────────────────────────────────────────

describe('AAIPClient — construction', () => {
  it('instantiates with an API key', () => {
    const client = new AAIPClient({ apiKey: 'test-key-123' });
    expect(client).toBeDefined();
  });

  it('instantiates without an API key (unauthenticated)', () => {
    const client = new AAIPClient({});
    expect(client).toBeDefined();
  });

  it('accepts a custom base URL', () => {
    const client = new AAIPClient({ apiKey: 'k', baseUrl: 'https://custom.api.example.com' });
    expect(client).toBeDefined();
  });
});

// ── register() ───────────────────────────────────────────────────────────────

describe('AAIPClient.register()', () => {
  beforeEach(() => { vi.clearAllMocks(); });
  afterEach(() => { vi.restoreAllMocks(); });

  it('returns a result on HTTP 200', async () => {
    mockFetch(200, { agent_id: 'agent-001', status: 'registered' });
    const client = new AAIPClient({ apiKey: 'key' });
    const result = await client.register({
      agent_name: 'TestAgent',
      owner: 'TestOrg',
      endpoint: 'https://api.example.com/agent',
      capabilities: ['nlp'],
      framework: 'custom',
    });
    expect(result).toBeDefined();
    expect(global.fetch).toHaveBeenCalledOnce();
  });

  it('throws on HTTP 401', async () => {
    mockFetch(401, { detail: 'Unauthorized' });
    const client = new AAIPClient({ apiKey: 'bad-key' });
    await expect(client.register({
      agent_name: 'Agent',
      owner: 'Owner',
      endpoint: 'https://example.com',
      capabilities: [],
      framework: 'custom',
    })).rejects.toThrow();
  });

  it('throws on HTTP 500', async () => {
    mockFetch(500, { detail: 'internal error' });
    const client = new AAIPClient({ apiKey: 'key' });
    await expect(client.register({
      agent_name: 'Agent',
      owner: 'Owner',
      endpoint: 'https://example.com',
      capabilities: [],
      framework: 'custom',
    })).rejects.toThrow();
  });
});

// ── getReputation() ───────────────────────────────────────────────────────────

describe('AAIPClient.getReputation()', () => {
  beforeEach(() => { vi.clearAllMocks(); });
  afterEach(() => { vi.restoreAllMocks(); });

  it('returns reputation data on HTTP 200', async () => {
    mockFetch(200, { agent_id: 'agent-001', score: 87.5, trend: 'up' });
    const client = new AAIPClient({ apiKey: 'key' });
    const result = await client.getReputation('agent-001');
    expect(result).toBeDefined();
  });

  it('throws on HTTP 404', async () => {
    mockFetch(404, { detail: 'agent not found' });
    const client = new AAIPClient({ apiKey: 'key' });
    await expect(client.getReputation('nonexistent')).rejects.toThrow();
  });
});

// ── discover() ────────────────────────────────────────────────────────────────

describe('AAIPClient.discover()', () => {
  beforeEach(() => { vi.clearAllMocks(); });
  afterEach(() => { vi.restoreAllMocks(); });

  it('returns agent list on HTTP 200', async () => {
    mockFetch(200, {
      agents: [{ agent_id: 'a1', capabilities: ['nlp'] }],
      total: 1,
    });
    const client = new AAIPClient({ apiKey: 'key' });
    const result = await client.discover({ capability: 'nlp' });
    expect(result).toBeDefined();
    expect(global.fetch).toHaveBeenCalledOnce();
  });
});