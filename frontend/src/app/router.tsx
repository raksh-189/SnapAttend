/** Role-guarded route tree. Placeholder pages are swapped as features land. */

import { createBrowserRouter } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { LoginPage } from '@/features/auth/components/LoginPage'
import { ProtectedRoute } from '@/features/auth/components/ProtectedRoute'
import { DashboardPage } from '@/features/dashboard/DashboardPage'

function Placeholder({ title }: { title: string }) {
  return (
    <div>
      <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
      <p className="mt-1 text-sm text-slate-500">Coming soon.</p>
    </div>
  )
}

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <AppShell />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'classes', element: <Placeholder title="Classes" /> },
      { path: 'students', element: <Placeholder title="Students" /> },
      { path: 'attendance', element: <Placeholder title="Attendance" /> },
    ],
  },
])
