/** App shell: sidebar navigation + topbar + content outlet. */

import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui'
import { useLogout } from '@/features/auth/api'
import { useAuthStore } from '@/stores/authStore'

const NAV = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/classes', label: 'Classes' },
  { to: '/students', label: 'Students' },
  { to: '/attendance', label: 'Attendance' },
]

export function AppShell() {
  const user = useAuthStore((s) => s.user)
  const logout = useLogout()
  const navigate = useNavigate()

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-56 shrink-0 flex-col border-r border-slate-200 bg-white sm:flex">
        <div className="px-5 py-5">
          <span className="text-lg font-bold tracking-tight">
            Attend<span className="text-brand-600">AI</span>
          </span>
        </div>
        <nav className="flex-1 space-y-1 px-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `block rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-brand-50 text-brand-700'
                    : 'text-slate-600 hover:bg-slate-100'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-200 p-4">
          <p className="truncate text-sm font-medium text-slate-900">
            {user?.full_name}
          </p>
          <p className="truncate text-xs text-slate-500">{user?.email}</p>
          <Button
            variant="ghost"
            className="mt-2 w-full"
            onClick={() =>
              logout.mutate(undefined, { onSettled: () => navigate('/login') })
            }
          >
            Sign out
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile topbar (sidebar collapses below sm) */}
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 sm:hidden">
          <span className="font-bold">
            Attend<span className="text-brand-600">AI</span>
          </span>
          <Button
            variant="ghost"
            onClick={() =>
              logout.mutate(undefined, { onSettled: () => navigate('/login') })
            }
          >
            Sign out
          </Button>
        </header>
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
