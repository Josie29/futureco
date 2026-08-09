import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react"
import { clearSession, readSession, writeSession } from "@/features/auth/storage"
import type { Coach, Session } from "@/types"

/**
 * Mock coach auth. "Mock auth is fine" (ASSESSMENT.md:72), so this is
 * deliberately trivial: a coach is picked, the choice is kept in
 * `localStorage`, and unauthenticated routes redirect.
 *
 * It earns its place by proving the boundary exists, and the boundary is now
 * real: every member call carries `X-Coach-Id`, and the API answers 404 unless
 * a `coaches` edge joins that coach to that member. A member id in a URL is not
 * authority to read that member.
 *
 * Storage lives in `./storage`, so the API layer can read the same key without
 * importing this context.
 */

interface SessionValue {
  session: Session | null
  signIn: (coach: Coach) => void
  signOut: () => void
}

const SessionContext = createContext<SessionValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(readSession)

  const signIn = useCallback((coach: Coach) => {
    const next: Session = { coach, signed_in_at: new Date().toISOString() }
    writeSession(next)
    setSession(next)
  }, [])

  const signOut = useCallback(() => {
    clearSession()
    setSession(null)
  }, [])

  const value = useMemo(() => ({ session, signIn, signOut }), [session, signIn, signOut])
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

/**
 * The current session.
 *
 * @throws Error when called outside a SessionProvider, which is a wiring bug
 *   rather than a runtime condition.
 */
export function useSession(): SessionValue {
  const value = useContext(SessionContext)
  if (!value) throw new Error("useSession must be used inside a SessionProvider")
  return value
}
