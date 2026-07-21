/** Dashboard — placeholder until the attendance/classes features land. */

import { useAuthStore } from '@/stores/authStore'

export function DashboardPage() {
  const user = useAuthStore((s) => s.user)
  return (
    <div>
      <h1 className="text-xl font-semibold text-slate-900">
        Welcome back{user ? `, ${user.full_name.split(' ')[0]}` : ''}
      </h1>
      <p className="mt-1 text-sm text-slate-500">
        Today's classes and pending reviews will appear here.
      </p>
    </div>
  )
}
