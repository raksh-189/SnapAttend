/** Route guard: requires a live session; optionally a specific role. */

import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import type { UserRole } from '@/types/api'

export function ProtectedRoute({
  children,
  role,
}: {
  children: ReactNode
  role?: UserRole
}) {
  const { user, accessToken } = useAuthStore()
  const location = useLocation()

  if (!accessToken) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  if (role && user && user.role !== role) {
    return <Navigate to="/" replace />
  }
  return children
}
