/** Root providers: TanStack Query + router. */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router-dom'
import { router } from '@/app/router'
import { useMe } from '@/features/auth/api'
import { useAuthStore } from '@/stores/authStore'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

function SessionLoader() {
  // Re-validate the persisted session once on load (also refreshes the
  // access token via the 401 interceptor if it expired while away).
  const hasToken = useAuthStore((s) => s.accessToken !== null)
  useMe(hasToken)
  return <RouterProvider router={router} />
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <SessionLoader />
    </QueryClientProvider>
  )
}
