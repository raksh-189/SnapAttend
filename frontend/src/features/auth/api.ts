/** Auth feature API calls + TanStack Query hooks. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import type { TokenPair, User } from '@/types/api'

export function useLogin() {
  const setTokens = useAuthStore((s) => s.setTokens)
  const setUser = useAuthStore((s) => s.setUser)
  return useMutation({
    mutationFn: async (creds: { email: string; password: string }) => {
      const { data } = await api.post<TokenPair>('/auth/login', creds)
      setTokens(data.access_token, data.refresh_token)
      const me = await api.get<User>('/auth/me')
      setUser(me.data)
      return me.data
    },
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  const clear = useAuthStore((s) => s.clear)
  return useMutation({
    mutationFn: async () => {
      const refreshToken = useAuthStore.getState().refreshToken
      if (refreshToken) {
        await api.post('/auth/logout', { refresh_token: refreshToken }).catch(() => {
          // Token already dead server-side — local logout is what matters.
        })
      }
    },
    onSettled: () => {
      clear()
      queryClient.clear() // drop every cached query owned by the old session
    },
  })
}

/** Re-validates the persisted session on app load. */
export function useMe(enabled: boolean) {
  const setUser = useAuthStore((s) => s.setUser)
  return useQuery({
    queryKey: ['auth', 'me'],
    enabled,
    retry: false,
    queryFn: async () => {
      const { data } = await api.get<User>('/auth/me')
      setUser(data)
      return data
    },
  })
}
