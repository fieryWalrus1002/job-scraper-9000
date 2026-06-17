export interface Principal {
  userId: string
  userDetails: string // email
  userRoles: string[]
}

const DEV_STUB: Principal = {
  userId: 'dev-stub',
  userDetails: 'dev@localhost',
  userRoles: ['dev-bypass'],
}

export async function fetchPrincipal(): Promise<Principal | null> {
  if (import.meta.env.DEV && import.meta.env.VITE_AUTH_BYPASS === '1') {
    return DEV_STUB
  }
  let res: Response
  try {
    res = await fetch('/.auth/me')
  } catch (err) {
    // Network / CORS failure — the request never completed. This is NOT an
    // unauthenticated state; swallowing it would lock the user out silently.
    console.error('fetchPrincipal: transport failure reaching /.auth/me', err)
    throw err
  }
  // 401/403 are the genuine "not signed in" responses → treat as anonymous.
  if (res.status === 401 || res.status === 403) return null
  // Any other non-OK status (5xx, unexpected) is a real failure, not a
  // logged-out state. Fail loudly so it surfaces instead of redirect-looping.
  if (!res.ok) {
    const err = new Error(`fetchPrincipal: /.auth/me returned ${res.status} ${res.statusText}`)
    console.error(err)
    throw err
  }
  const data = (await res.json()) as { clientPrincipal?: Principal | null }
  return data.clientPrincipal ?? null
}
