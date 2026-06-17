import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { fetchPrincipal } from '../lib/auth'

function mockFetch(impl: (input: RequestInfo | URL) => Promise<Response>) {
  vi.stubGlobal('fetch', vi.fn(impl))
}

function jsonResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

describe('fetchPrincipal', () => {
  beforeEach(() => {
    // Tests run with import.meta.env.DEV=true; disable the dev auth bypass so
    // we exercise the real /.auth/me fetch path.
    vi.stubEnv('VITE_AUTH_BYPASS', '0')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
  })

  it('returns the clientPrincipal when present', async () => {
    const principal = { userId: 'u1', userDetails: 'a@b.com', userRoles: ['authenticated'] }
    mockFetch(async () => jsonResponse({ clientPrincipal: principal }))
    await expect(fetchPrincipal()).resolves.toEqual(principal)
  })

  it('returns null when clientPrincipal is null (logged out)', async () => {
    mockFetch(async () => jsonResponse({ clientPrincipal: null }))
    await expect(fetchPrincipal()).resolves.toBeNull()
  })

  it('returns null for 401/403 (genuine auth failures)', async () => {
    mockFetch(async () => new Response(null, { status: 401 }))
    await expect(fetchPrincipal()).resolves.toBeNull()
  })

  it('throws on a 5xx server error rather than reporting logged-out', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetch(async () => new Response(null, { status: 500, statusText: 'Internal Server Error' }))
    await expect(fetchPrincipal()).rejects.toThrow(/500/)
  })

  it('throws on a transport failure (network/CORS)', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetch(async () => {
      throw new TypeError('Failed to fetch')
    })
    await expect(fetchPrincipal()).rejects.toThrow(/Failed to fetch/)
  })
})
