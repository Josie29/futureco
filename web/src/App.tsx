import { Suspense, lazy } from "react"
import { useQuery } from "@tanstack/react-query"
import { Navigate, Route, Routes, useLocation } from "react-router-dom"
import { getRoster } from "@/api/client"
import { AppHeader } from "@/components/AppHeader"
import { LoginScreen } from "@/features/auth/LoginScreen"
import { SessionProvider, useSession } from "@/features/auth/session"

// Both routes are split. The console never pays for the inspector — cheap
// today, but phase 2's instance explorer brings a graph engine with it — and
// the inspector loads without pulling the console's data layer in behind it.
const Console = lazy(() => import("@/pages/Console"))
const AdminGraph = lazy(() => import("@/features/admin/AdminGraph"))
const TracesView = lazy(() => import("@/features/traces/TracesView"))

function RouteFallback() {
  return (
    <div className="flex flex-1 items-center justify-center p-8 text-sm text-dim">Loading</div>
  )
}

/**
 * Unauthenticated visits redirect, and come back to where they were headed.
 *
 * The session is read synchronously from `localStorage` in the provider's
 * state initialiser, so there is no first render where a signed-in coach looks
 * signed out. If that ever becomes async, this guard needs a pending state —
 * without one it would bounce every deep link on reload.
 */
function RequireSession({ children }: { children: React.ReactNode }) {
  const { session } = useSession()
  const location = useLocation()
  if (!session) {
    const from = `${location.pathname}${location.search}`
    return <Navigate to="/login" replace state={{ from }} />
  }
  return <>{children}</>
}

/**
 * The console needs a member in the URL, so bare `/` picks the one that needs
 * attention first — the same order the rail sorts by.
 */
function FirstMember() {
  const { data: roster, isPending, isError } = useQuery({ queryKey: ["roster"], queryFn: getRoster })

  if (isPending) return <RouteFallback />
  if (isError || !roster?.length) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <p className="max-w-sm text-center text-sm text-dim">
          Couldn't load your roster. Reload to try again.
        </p>
      </div>
    )
  }

  const first = [...roster].sort((a, b) => Number(b.needs_attention) - Number(a.needs_attention))[0]
  return <Navigate to={`/m/${first.id}`} replace />
}

function Shell() {
  const { session } = useSession()

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-ground text-ink">
      {session && <AppHeader />}

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/login" element={<LoginScreen />} />
            <Route
              path="/"
              element={
                <RequireSession>
                  <FirstMember />
                </RequireSession>
              }
            />
            {/* The active member lives in the URL, so a reload or a shared
                link restores exactly what the coach was looking at. */}
            <Route
              path="/m/:memberId"
              element={
                <RequireSession>
                  <Console />
                </RequireSession>
              }
            />
            {/* Written for an engineer, not a coach — it shows the Cypher. */}
            <Route
              path="/traces"
              element={
                <RequireSession>
                  <TracesView />
                </RequireSession>
              }
            />
            <Route
              path="/admin/graph"
              element={
                <RequireSession>
                  <AdminGraph />
                </RequireSession>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <SessionProvider>
      <Shell />
    </SessionProvider>
  )
}
