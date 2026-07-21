/** Axios instance with auth header injection and 401 → refresh → retry.
 *
 * Refresh strategy: rotating refresh tokens (backend revokes the old one on
 * every /auth/refresh), so concurrent 401s must share ONE refresh promise —
 * firing two refreshes with the same token trips the backend's reuse
 * detection and revokes the whole session family.
 */

import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/stores/authStore'
import type { TokenPair } from '@/types/api'

export const api = axios.create({ baseURL: '/api/v1' })

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

let refreshing: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  const { refreshToken, setTokens, clear } = useAuthStore.getState()
  if (!refreshToken) {
    clear()
    throw new Error('No refresh token')
  }
  try {
    // Bare axios — the interceptor'd instance would loop on failure.
    const { data } = await axios.post<TokenPair>('/api/v1/auth/refresh', {
      refresh_token: refreshToken,
    })
    setTokens(data.access_token, data.refresh_token)
    return data.access_token
  } catch (err) {
    clear() // refresh rejected → session is dead; force re-login
    throw err
  }
}

api.interceptors.response.use(undefined, async (error: AxiosError) => {
  const original = error.config as InternalAxiosRequestConfig & { _retried?: boolean }
  const status = error.response?.status
  const isAuthRoute = original?.url?.startsWith('/auth/')

  if (status === 401 && original && !original._retried && !isAuthRoute) {
    original._retried = true
    refreshing ??= refreshAccessToken().finally(() => {
      refreshing = null
    })
    const token = await refreshing // throws → caller sees the original 401
    original.headers.Authorization = `Bearer ${token}`
    return api(original)
  }
  return Promise.reject(error)
})

/** Extract the backend error envelope {detail, code}; fall back gracefully. */
export function apiErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: unknown })?.detail
    if (typeof detail === 'string') return detail
    if (err.response?.status === 401) return 'Invalid credentials'
  }
  return 'Something went wrong — please try again'
}
