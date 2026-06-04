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
  try {
    const res = await fetch('/.auth/me')
    if (!res.ok) return null
    const data = (await res.json()) as { clientPrincipal?: Principal | null }
    return data.clientPrincipal ?? null
  } catch {
    return null
  }
}
